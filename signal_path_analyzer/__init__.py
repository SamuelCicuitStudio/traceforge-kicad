"""Signal-path analysis primitives."""

from .analyzer import analyze_tracks
from .model import DelayProfile, NetSummary, TrackSample

__all__ = ["DelayProfile", "NetSummary", "TrackSample", "analyze_tracks"]
__version__ = "0.13.1"
NATIVE_BUILD_ID = "0.13.1-via-pad-scan-20261111"

