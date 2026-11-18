"""Stable tool routing; numeric IDs are retained only for older launchers."""

from __future__ import annotations

LEGACY_TO_TOOL = {
    0: "signals.paths",
    1: "vias.stitching",
    2: "routing.fanout",
    3: "routing.cleanup",
    4: "layout.rotate",
    5: "view",
    6: "manufacturing",
    7: "about",
    8: "layout.clone",
    9: "layout.references",
    10: "signals.unrouted",
}
TOOLS = set(LEGACY_TO_TOOL.values()) | {
    "components.search",
    "components.assets",
    "components.library",
    "manufacturing.cost",
    "vias.fencing",
    "vias.array",
    "vias.sizes",
    "vias.inspector",
    "routing.teardrops",
    "routing.corners",
}


def tool_id(value):
    if isinstance(value, int) or str(value).isdigit():
        try:
            return LEGACY_TO_TOOL[int(value)]
        except KeyError as exc:
            raise ValueError("Unknown legacy TraceForge tool") from exc
    if value not in TOOLS:
        raise ValueError("Unknown TraceForge tool: " + str(value))
    return value


def legacy_index(value):
    value = tool_id(value)
    if value.startswith("vias."):
        return 1
    if value in ("routing.teardrops", "routing.corners"):
        return 3
    if value.startswith("components."):
        return 11
    if value == "manufacturing.cost":
        return 6
    return next(k for k, v in LEGACY_TO_TOOL.items() if v == value)
