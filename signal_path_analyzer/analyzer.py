"""Pure signal-path calculations with no KiCad runtime dependency."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Optional

from .model import DelayProfile, NetSummary, TrackSample


def analyze_tracks(
    tracks: Iterable[TrackSample], profile: Optional[DelayProfile] = None
) -> list[NetSummary]:
    """Aggregate routed track length and, when fully known, propagation delay."""

    active_profile = profile or DelayProfile()
    grouped: dict[str, list[TrackSample]] = defaultdict(list)
    for track in tracks:
        grouped[track.net_name].append(track)

    summaries = []
    for net_name in sorted(grouped):
        net_tracks = grouped[net_name]
        length_mm = sum(track.length_mm for track in net_tracks)
        delays = [
            active_profile.delay_for(track.layer_name, track.length_mm)
            for track in net_tracks
        ]
        delay_ps = sum(delays) if delays and all(value is not None for value in delays) else None
        summaries.append(
            NetSummary(
                net_name=net_name,
                track_count=len(net_tracks),
                length_mm=length_mm,
                delay_ps=delay_ps,
                layers=tuple(sorted({track.layer_name for track in net_tracks})),
            )
        )
    return summaries

