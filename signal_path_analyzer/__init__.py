"""Signal-path analysis primitives."""

from .analyzer import analyze_tracks
from .model import DelayProfile, NetSummary, TrackSample

__all__ = ["DelayProfile", "NetSummary", "TrackSample", "analyze_tracks"]
__version__ = "0.16.5"
NATIVE_BUILD_ID = "0.16.5-unrouted-gap-navigator-20261117"

