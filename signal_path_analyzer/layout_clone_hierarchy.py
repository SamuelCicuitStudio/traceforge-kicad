"""Repeated-sheet identity helpers; no net-name or reference-number guessing."""

from __future__ import annotations

from collections import Counter


def path_parts(value):
    if isinstance(value, str):
        return tuple(p for p in value.strip("/").split("/") if p)
    return tuple(value or ())


def common_sheet(paths):
    parents = [path_parts(p)[:-1] for p in paths]
    if not parents or any(not p for p in parents):
        return ()
    shared = []
    for entries in zip(*parents):
        if len(set(entries)) != 1:
            break
        shared.append(entries[0])
    return tuple(shared)


def relative_keys(snapshot):
    items = snapshot["items"]
    root = path_parts(snapshot.get("hierarchy_root")) or common_sheet(
        p.get("schematic_path") for p in items
    )
    # A root-sheet selection is not a repeated hierarchical block.
    if not root:
        return {}
    result = {}
    for item in items:
        path = path_parts(item.get("schematic_path"))
        if path[: len(root)] != root or len(path) <= len(root):
            return {}
        result[item["ref"]] = path[len(root) :]
    return result


def correspondences(source, target):
    a, b = relative_keys(source), relative_keys(target)
    strict = source.get("scope") == "hierarchy" or target.get("scope") == "hierarchy"
    if not a or not b:
        if strict:
            raise ValueError(
                "Repeated-sheet cloning needs valid schematic paths in both instances."
            )
        return {}
    ca, cb = Counter(a.values()), Counter(b.values())
    if strict and (any(n != 1 for n in ca.values()) or any(n != 1 for n in cb.values())):
        raise ValueError("Duplicate relative symbol paths in repeated sheet instances.")
    inverse = {key: ref for ref, key in b.items() if cb[key] == 1}
    if strict and set(a.values()) != set(b.values()):
        raise ValueError(
            "Sheet instances have different relative symbol paths. "
            "Synchronize the PCB from the schematic, or use selected-items matching."
        )
    return {ref: inverse[key] for ref, key in a.items() if ca[key] == 1 and key in inverse}
