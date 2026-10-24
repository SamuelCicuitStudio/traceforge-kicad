"""Small compatibility boundary around the KiCad IPC Python API (kipy)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from .chains import NetGeometry, TrackSeg, ViaHop
from .model import TrackSample


def _name(value: Any) -> str:
    return str(getattr(value, "name", value))


def canonical_layer(layer: int) -> str:
    """BoardLayer enum -> canonical KiCad name (BL_In2_Cu -> In2.Cu), independent of user names."""

    from kipy.proto.board.board_types_pb2 import BoardLayer

    name = BoardLayer.Name(layer)
    return name[3:].replace("_", ".", 1) if name.startswith("BL_") else name


def _length_nm(track: Any) -> float:
    return float(track.length() if callable(getattr(track, "length", None)) else track.length)


def collect_track_samples(board: Any) -> Iterable[TrackSample]:
    """Yield straight and arc track lengths from a live KiCad board."""

    for track in board.get_tracks():
        net_name = _name(getattr(track, "net", None)).strip()
        if not net_name or net_name in {"0", "None"}:
            continue
        yield TrackSample(net_name=net_name, layer_name=canonical_layer(track.layer),
                          length_mm=_length_nm(track) / 1_000_000.0)


def plain_name(board_name: str) -> str:
    """KiCad escapes '/' inside a sheet or label name as {slash}; configs use the plain form."""

    return board_name.replace("{slash}", "/")


def _nets_by_name(board: Any, names: Iterable[str]) -> list[Any]:
    wanted = {plain_name(n) for n in names}
    return [n for n in board.get_nets() if plain_name(n.name) in wanted]


def board_names(board: Any, names: Iterable[str]) -> dict[str, str]:
    """Plain (config) name -> the board's own net name, for rules that must match exactly."""

    return {plain_name(n.name): n.name for n in _nets_by_name(board, names)}


def snapshot(board: Any, net_names: Sequence[str]) -> dict[str, NetGeometry]:
    """Geometry of the given nets, keyed by plain name: tracks/arcs, via spans, pad-to-die."""

    from kipy.board_types import ArcTrack, Pad, Track, Via

    nets = _nets_by_name(board, net_names)
    if not nets:
        return {}
    classes = board.get_netclass_for_nets(nets)
    geo = {plain_name(n.name): NetGeometry(netclass=getattr(classes.get(n.name), "name", None))
           for n in nets}
    for item in board.get_items_by_net(nets):
        net = plain_name(_name(getattr(item, "net", None)))
        g = geo.get(net)
        if g is None:
            continue
        if isinstance(item, (Track, ArcTrack)):
            g.tracks.append(TrackSeg(canonical_layer(item.layer), _length_nm(item) / 1_000_000.0))
        elif isinstance(item, Via):
            drill = item.padstack.drill
            g.vias.append(ViaHop((canonical_layer(drill.start_layer),
                                  canonical_layer(drill.end_layer))))
        elif isinstance(item, Pad):
            die = getattr(item, "pad_to_die_length", 0) or 0
            if die:
                g.die_mm.append(float(die) / 1_000_000.0)
    return geo


def series_parts(board: Any) -> list[tuple[str, str, dict[str, str]]]:
    """(reference, value, {pad number: net}) for every footprint, used for chain auto-detection."""

    out = []
    for fp in board.get_footprints():
        ref = fp.reference_field.text.value
        value = fp.value_field.text.value
        pads = {p.number: plain_name(_name(p.net)) for p in fp.definition.pads}
        out.append((ref, value, pads))
    return out


def chain_items(board: Any, net_names: Sequence[str], refs: Sequence[str]) -> list[Any]:
    """Every copper item of the nets plus the series footprints, for selection highlighting."""

    nets = _nets_by_name(board, net_names)
    items = list(board.get_items_by_net(nets)) if nets else []
    wanted = set(refs)
    items += [fp for fp in board.get_footprints() if fp.reference_field.text.value in wanted]
    return items


def highlight(board: Any, items: Sequence[Any]) -> int:
    board.clear_selection()
    if items:
        board.add_to_selection(items)
    return len(items)
