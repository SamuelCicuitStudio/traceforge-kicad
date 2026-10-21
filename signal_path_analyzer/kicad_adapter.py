"""Small compatibility boundary around the KiCad IPC Python API."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .model import TrackSample


def _name(value: Any) -> str:
    return str(getattr(value, "name", value))


def collect_track_samples(board: Any) -> Iterable[TrackSample]:
    """Yield straight and arc track lengths from a live KiCad board."""

    for track in board.get_tracks():
        net = getattr(track, "net", None)
        net_name = _name(net).strip()
        if not net_name or net_name in {"0", "None"}:
            continue
        length = track.length() if callable(getattr(track, "length", None)) else track.length
        yield TrackSample(
            net_name=net_name,
            layer_name=_name(track.layer),
            length_mm=float(length) / 1_000_000.0,
        )

