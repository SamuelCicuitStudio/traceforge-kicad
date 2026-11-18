"""Undoable selected-reference metadata assignment; electrical/physical objects stay intact."""

from __future__ import annotations

import uuid

import pcbnew

from . import component_schema as schema
from .component_info import INFO_FIELDS
from .stitching_native import transaction

_preview = None


def footprints(board, refs):
    wanted = set(refs)
    found = {fp.GetReference(): fp for fp in board.GetFootprints() if fp.GetReference() in wanted}
    if set(found) != wanted:
        raise ValueError(
            "References not in the active PCB: " + ", ".join(sorted(wanted - set(found)))
        )
    return [found[r] for r in sorted(wanted)]


def state(fp):
    return (
        fp.m_Uuid.AsString(),
        fp.GetReference(),
        fp.GetValue(),
        fp.GetFPID().GetUniStringLibId(),
        sorted((str(f.GetName()), str(f.GetText()), bool(f.IsVisible())) for f in fp.GetFields()),
    )


def write_fields(fp, props):
    fields = list(fp.GetFields())
    for key, value in props.items():
        aliases = {schema.fold(x) for x in [key] + schema.SCHEMA["fields"][key]["aliases"]}
        matches = [f for f in fields if schema.fold(f.GetName()) in aliases]
        field = next((f for f in matches if f.GetName() == key), matches[0] if matches else None)
        if field:
            field.SetName(key)
            field.SetText(value)
            field.SetVisible(False)
            for duplicate in matches:
                if duplicate != field:
                    duplicate.SetText("")
        else:
            fp.SetField(key, value)
            fp.GetField(key).SetVisible(False)


def dispatch(board, operation, payload, revision):
    global _preview
    if operation == "component_info_preview":
        refs = payload.get("refs", [])
        selected = footprints(board, refs)
        props = {k: str(v) for k, v in payload.get("properties", {}).items() if k in INFO_FIELDS}
        if not all(props.get(k) for k in ("MPN", "Manufacturer", "LCSC Part #")):
            raise ValueError("Complete exact supplier identity is required")
        expected = {p["reference"]: p for p in payload.get("expected", [])}
        for fp in selected:
            previous = expected.get(fp.GetReference(), {})
            if previous.get("value") is not None and previous["value"] != fp.GetValue():
                raise ValueError(
                    fp.GetReference() + " PCB value differs from BOM; synchronize first"
                )
            old = schema.properties({f.GetName(): f.GetText() for f in fp.GetFields()})
            prior = schema.properties(previous.get("properties", {}))
            if old.get("MPN") and prior.get("MPN") and old["MPN"] != prior["MPN"]:
                raise ValueError(
                    fp.GetReference() + " PCB identity differs from BOM; synchronize first"
                )
        _preview = dict(
            token=uuid.uuid4().hex,
            board=board.GetFileName(),
            revision=revision(),
            states=[state(fp) for fp in selected],
            refs=refs,
            properties=props,
        )
        return dict(token=_preview["token"], references=refs)
    if operation != "component_info_apply":
        raise ValueError("Unknown metadata operation")
    preview = _preview
    if not preview or payload.get("token") != preview["token"]:
        raise ValueError("Information assignment preview expired")
    selected = footprints(board, preview["refs"])
    if (
        board.GetFileName() != preview["board"]
        or revision() != preview["revision"]
        or [state(fp) for fp in selected] != preview["states"]
    ):
        raise ValueError("PCB changed during assignment; select the part again")

    def apply(live):
        for fp in footprints(live, preview["refs"]):
            write_fields(fp, preview["properties"])
        pcbnew.Refresh()
        return dict(updated=preview["refs"], properties=preview["properties"])

    result = transaction(board, apply)
    _preview = None
    return result
