"""Data model shared by the KiCad adapter and the analysis engine."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Optional


@dataclass(frozen=True)
class TrackSample:
    """One routed copper item reduced to the inputs needed by the analyzer."""

    net_name: str
    layer_name: str
    length_mm: float

    def __post_init__(self) -> None:
        if not self.net_name:
            raise ValueError("net_name must not be empty")
        if not self.layer_name:
            raise ValueError("layer_name must not be empty")
        if self.length_mm < 0:
            raise ValueError("length_mm must not be negative")


@dataclass(frozen=True)
class DelayProfile:
    """Propagation delay by copper layer, expressed in ps/mm."""

    layer_ps_per_mm: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized = dict(self.layer_ps_per_mm)
        if any(value <= 0 for value in normalized.values()):
            raise ValueError("all layer propagation values must be positive")
        object.__setattr__(self, "layer_ps_per_mm", MappingProxyType(normalized))

    def delay_for(self, layer_name: str, length_mm: float) -> Optional[float]:
        unit_delay = self.layer_ps_per_mm.get(layer_name)
        return None if unit_delay is None else unit_delay * length_mm


@dataclass(frozen=True)
class NetSummary:
    """Aggregated routed length and optional delay for one electrical net."""

    net_name: str
    track_count: int
    length_mm: float
    delay_ps: Optional[float]
    layers: tuple[str, ...]

