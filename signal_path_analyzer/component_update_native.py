"""Explicit selected-footprint library refresh, separate from library installation."""

from __future__ import annotations

import uuid
from collections import defaultdict
from pathlib import Path

import pcbnew

from .component_library import digest, discover, read_bytes, table_libraries, within
from .stitching_native import refill, transaction
from .traceforge_layout_clone import _snapshot_fp

_preview = None


def _models(fp):
    return [
        dict(
            path=m.m_Filename,
            offset=[m.m_Offset.x, m.m_Offset.y, m.m_Offset.z],
            rotation=[m.m_Rotation.x, m.m_Rotation.y, m.m_Rotation.z],
            scale=[m.m_Scale.x, m.m_Scale.y, m.m_Scale.z],
        )
        for m in fp.Models()
    ]


def _state(board, fp):
    data = _snapshot_fp(board, fp)
    data["fields"] = [
        (
            f.GetName(),
            f.GetText(),
            f.IsVisible(),
            f.GetPosition().x,
            f.GetPosition().y,
            f.GetLayer(),
            f.GetTextAngleDegrees(),
        )
        for f in fp.GetFields()
    ]
    data["models"] = _models(fp)
    data["attributes"] = fp.GetAttributes()
    return data


def _selected(board):
    selected = [item for item in pcbnew.GetCurrentSelection() if isinstance(item, pcbnew.FOOTPRINT)]
    if not selected:
        raise ValueError("Select the PCB footprints to update first.")
    if len(selected) > 50:
        raise ValueError("Update at most 50 selected footprints per reviewed operation.")
    return sorted(selected, key=lambda fp: fp.GetReference())


def _candidate(board, old, library, models):
    if old.IsLocked():
        raise ValueError("Locked footprint; unlock it before updating.")
    parent = old.GetParentGroup()
    group = (
        pcbnew.Cast_to_PCB_GROUP(pcbnew.Cast_to_BOARD_ITEM(parent.AsEdaItem())) if parent else None
    )
    if group and group.IsLocked():
        raise ValueError("Parent group is locked.")
    new = pcbnew.FootprintLoad(str(library.parent), library.stem)
    if new is None:
        raise ValueError("KiCad could not load the assigned project footprint.")
    new.SetParent(board)
    new.SetPosition(old.GetPosition())
    if new.IsFlipped() != old.IsFlipped():
        new.Flip(new.GetPosition(), False)
    new.SetOrientation(old.GetOrientation())
    new.SetFPID(old.GetFPID())
    new.SetPath(old.GetPath())
    new.SetAttributes(old.GetAttributes())
    new.SetLocked(old.IsLocked())
    # A library UUID is not a placed-instance UUID. Reusing it across selected
    # instances would create duplicate pad/graphic IDs on the board.
    for item in list(new.Pads()) + list(new.GraphicalItems()) + list(new.GetFields()):
        item.SetUuid(pcbnew.KIID())
    new.SetUuid(old.m_Uuid)
    original_fields = {f.GetName(): f for f in old.GetFields()}
    for field in list(new.GetFields()):
        if field.GetName() not in original_fields:
            new.Remove(field)
    for name, field in original_fields.items():
        if new.HasField(name):
            copied = new.GetField(name)
            copied.CopyFrom(field)
            copied.SetParent(new)
        else:
            copied = field.CloneField()
            copied.SetParent(new)
            new.Add(copied)
    if not models:
        new.Models().clear()
        for model in old.Models():
            new.Models().push_back(model)
    old_pads, new_pads = defaultdict(list), defaultdict(list)
    for pad in old.Pads():
        if pad.GetNumber():
            old_pads[pad.GetNumber()].append(pad)
    for pad in new.Pads():
        if pad.GetNumber():
            new_pads[pad.GetNumber()].append(pad)
    if set(old_pads) != set(new_pads):
        raise ValueError("Electrical pad numbers differ; current footprint preserved.")
    for number, pads in old_pads.items():
        nets = {p.GetNetCode() for p in pads}
        if len(nets) != 1:
            raise ValueError("Same-number pads carry conflicting nets.")
        for pad in new_pads[number]:
            pad.SetNet(pads[0].GetNet())
    return new, old_pads, new_pads


def _contact_guard(board, old, new, old_pads, new_pads, selected):
    """Keep every routed contact and reject new foreign-net copper collisions."""
    tracks = list(board.GetTracks())
    other_pads = [
        p for fp in board.GetFootprints() if fp.m_Uuid.AsString() not in selected for p in fp.Pads()
    ]
    contacts = 0
    for number, pads in old_pads.items():
        replacements = new_pads[number]
        for pad in pads:
            for track in tracks + other_pads:
                if pad.GetNetCode() <= 0:
                    continue
                if pad.GetNetCode() != track.GetNetCode():
                    continue
                for layer in board.GetEnabledLayers().CuStack():
                    if not pad.IsOnLayer(layer) or not track.IsOnLayer(layer):
                        continue
                    copper = track.GetEffectiveShape(layer)
                    if pad.GetEffectiveShape(layer).Collide(copper, 0):
                        if not any(
                            p.IsOnLayer(layer) and p.GetEffectiveShape(layer).Collide(copper, 0)
                            for p in replacements
                        ):
                            raise ValueError("Updated pad loses a routed copper contact: " + number)
                        contacts += 1
    # Only new collisions are rejected: pre-existing board problems remain
    # visible to DRC and cannot make a model/legend-only update impossible.
    for pad in new.Pads():
        for other in tracks + other_pads:
            if pad.GetNetCode() > 0 and pad.GetNetCode() == other.GetNetCode():
                continue
            if not pad.GetBoundingBox().Intersects(other.GetBoundingBox()):
                continue
            for layer in board.GetEnabledLayers().CuStack():
                if not pad.IsOnLayer(layer) or not other.IsOnLayer(layer):
                    continue
                shape = other.GetEffectiveShape(layer)
                if not pad.GetEffectiveShape(layer).Collide(shape, 0):
                    continue
                prior = old_pads.get(pad.GetNumber(), [])
                if not any(
                    p.IsOnLayer(layer) and p.GetEffectiveShape(layer).Collide(shape, 0)
                    for p in prior
                ):
                    raise ValueError("Updated pad introduces a foreign-net copper collision.")
    return contacts


def _prepare(board, selected, use_models):
    root = Path(discover(board.GetFileName())["root"])
    libraries = {x["nickname"]: Path(x["path"]) for x in table_libraries(root, "fp-lib-table")}
    rows, prepared, files = [], [], {}
    selected_ids = {fp.m_Uuid.AsString() for fp in selected}
    for old in selected:
        ref = old.GetReference()
        row = dict(reference=ref, footprint=old.GetFPID().GetUniStringLibId(), status="blocked")
        try:
            nick, name = row["footprint"].split(":", 1)
            if nick not in libraries:
                raise ValueError("Assigned footprint is not in a registered project-local library.")
            path = within(root, libraries[nick] / (name + ".kicad_mod"))
            if not path.is_file():
                raise ValueError("Assigned library footprint is missing.")
            new, old_pads, new_pads = _candidate(board, old, path, use_models)
            contacts = _contact_guard(board, old, new, old_pads, new_pads, selected_ids)
            # Check candidate-to-candidate collisions as well as existing copper.
            for previous_old, previous_new in prepared:
                # Direct same-net pad-to-pad connections can exist without a
                # track. Check them against both proposed definitions too.
                for before in old.Pads():
                    for previous in previous_old.Pads():
                        if before.GetNetCode() <= 0 or before.GetNetCode() != previous.GetNetCode():
                            continue
                        if not before.GetBoundingBox().Intersects(previous.GetBoundingBox()):
                            continue
                        for layer in board.GetEnabledLayers().CuStack():
                            if not before.IsOnLayer(layer) or not previous.IsOnLayer(layer):
                                continue
                            if not before.GetEffectiveShape(layer).Collide(
                                previous.GetEffectiveShape(layer), 0
                            ):
                                continue
                            left = [
                                p
                                for p in new.Pads()
                                if p.GetNumber() == before.GetNumber() and p.IsOnLayer(layer)
                            ]
                            right = [
                                p
                                for p in previous_new.Pads()
                                if p.GetNumber() == previous.GetNumber() and p.IsOnLayer(layer)
                            ]
                            if not any(
                                a.GetEffectiveShape(layer).Collide(b.GetEffectiveShape(layer), 0)
                                for a in left
                                for b in right
                            ):
                                raise ValueError(
                                    "Updated selected pads lose a direct copper contact."
                                )
                for pad in new.Pads():
                    for other in previous_new.Pads():
                        if pad.GetNetCode() > 0 and pad.GetNetCode() == other.GetNetCode():
                            continue
                        for layer in board.GetEnabledLayers().CuStack():
                            if (
                                pad.IsOnLayer(layer)
                                and other.IsOnLayer(layer)
                                and pad.GetEffectiveShape(layer).Collide(
                                    other.GetEffectiveShape(layer), 0
                                )
                            ):
                                raise ValueError("Updated selected footprints collide on copper.")
            prepared.append((old, new))
            files[str(path)] = digest(read_bytes(path))
            row.update(
                status="ready",
                pads=sum(map(len, new_pads.values())),
                checked_contacts=contacts,
                old=_state(board, old),
                new=_state(board, new),
                models="library models" if use_models else "existing models preserved",
            )
        except (ValueError, OSError) as exc:
            row["reason"] = str(exc)
        rows.append(row)
    return rows, prepared, files


def dispatch(board, operation, payload, revision):
    global _preview
    if operation == "component_update_preview":
        selected = _selected(board)
        models = bool(payload.get("library_models", False))
        rows, _prepared, files = _prepare(board, selected, models)
        snapshot = [_state(board, fp) for fp in selected]
        _preview = dict(
            token=uuid.uuid4().hex,
            board=board.GetFileName(),
            revision=revision(),
            state=snapshot,
            models=models,
            files=files,
        )
        return dict(
            token=_preview["token"], rows=rows, ready=all(row["status"] == "ready" for row in rows)
        )
    if operation != "component_update_apply":
        raise ValueError("Unknown selected-footprint update operation.")
    plan = _preview
    if not plan or payload.get("token") != plan["token"]:
        raise ValueError("Preview the selected footprint updates first.")
    selected = _selected(board)
    if (
        board.GetFileName() != plan["board"]
        or revision() != plan["revision"]
        or [_state(board, fp) for fp in selected] != plan["state"]
    ):
        raise ValueError("Board or selection changed since preview; preview again.")
    if any(digest(read_bytes(Path(path))) != value for path, value in plan["files"].items()):
        raise ValueError("Library changed since preview; preview again.")
    rows, prepared, _files = _prepare(board, selected, plan["models"])
    if not all(row["status"] == "ready" for row in rows):
        raise ValueError("An update is blocked; preview the checks again.")

    def apply(live):
        if revision() != plan["revision"]:
            raise ValueError("Board changed before the undoable update.")
        for old, new in prepared:
            group = old.GetParentGroup()
            if group:
                group.RemoveItem(old)
            live.RemoveNative(old)
            live.Add(new)
            if group:
                group.AddItem(new)
            new.SetSelected()
        refill(live)
        pcbnew.Refresh()
        return dict(
            updated=[row["reference"] for row in rows],
            note="Placement, nets, fields and routing retained; run DRC after updating.",
        )

    result = transaction(board, apply)
    _preview = None
    return result
