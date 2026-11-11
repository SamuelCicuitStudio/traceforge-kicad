"""Signal-path analysis primitives."""

from .analyzer import analyze_tracks
from .model import DelayProfile, NetSummary, TrackSample

__all__ = ["DelayProfile", "NetSummary", "TrackSample", "analyze_tracks"]
__version__ = "0.13.3"
NATIVE_BUILD_ID = "0.13.3-timing-profile-validation-20261111"

