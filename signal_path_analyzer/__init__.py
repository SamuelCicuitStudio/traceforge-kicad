"""Signal-path analysis primitives."""

from .analyzer import analyze_tracks
from .model import DelayProfile, NetSummary, TrackSample

__all__ = ["DelayProfile", "NetSummary", "TrackSample", "analyze_tracks"]
__version__ = "0.13.0"
NATIVE_BUILD_ID = "0.13.0-dual-platform-20261111"

