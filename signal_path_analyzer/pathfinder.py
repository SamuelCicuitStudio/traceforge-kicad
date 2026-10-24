"""Create signal chains between components (Altium "Create xSignals Between Components").

From each pad of a source (driver) component, follow the netlist through series parts until a pad
of a destination component is reached. Series parts: resistors <= max_ohms (including 0R), 4-pad
common-mode chokes and, optionally, 2-pad capacitors (AC coupling). The walk never passes through
any other part, so ICs, connectors and pull/termination networks end it. Power/ground-like nets
(too many pads, or named like a rail) are skipped.

Found chains are named and grouped by interface templates, with suggested limits. Pure Python.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Optional

from .chains import ChainDef, Config, GroupDef, series_ohms

Part = tuple[str, str, Mapping[str, str]]  # reference, value, {pad number: net}

RAIL = re.compile(r"(^|/)(GND|AGND|DGND|PGND|VSS|VDD|VCC|VBUS|V\d|\+?\d+V\d*)", re.I)


@dataclass
class FoundChain:
    name: str
    nets: tuple[str, ...]  # driver side first
    series: tuple[str, ...]
    source_pad: str  # "U6.AP33"
    dest_pad: str
    group: str = ""
    pair: Optional[str] = None
    keep: bool = True


@dataclass
class GroupSuggestion:
    name: str
    skew_ps: Optional[float]
    pair_skew_ps: Optional[float]
    stub_max_ps: Optional[float]
    chains: list[FoundChain] = field(default_factory=list)


def _is_rail(net: str, pads_on_net: int, max_pads: int) -> bool:
    return pads_on_net > max_pads or bool(RAIL.search(net))


def _through_pairs(ref: str, value: str, pads: Mapping[str, str], max_ohms: float,
                   with_caps: bool) -> list[tuple[str, str]]:
    """Net pairs a series part connects straight through."""

    nets = [n for _, n in sorted(pads.items()) if n]
    up = ref.upper()
    if len(pads) == 2 and len(set(nets)) == 2:
        if up.startswith("R"):
            ohms = series_ohms(value)
            if ohms is not None and ohms <= max_ohms:
                return [(nets[0], nets[1])]
        if with_caps and up.startswith("C"):
            return [(nets[0], nets[1])]
        return []
    if up.startswith(("L", "FL", "T")) and len(pads) == 4 and len(set(nets)) == 4:
        return _choke_pairs(nets)
    return []


def _choke_pairs(nets: list[str]) -> list[tuple[str, str]]:
    """Pair a common-mode choke's windings: _P with _P and _N with _N when names say so."""

    def pol(n: str) -> str:
        m = re.search(r"(_P|_N|\+|-)$", n)
        return m.group(1).replace("+", "_P").replace("-", "_N") if m else ""

    p = [n for n in nets if pol(n) == "_P"]
    n_ = [n for n in nets if pol(n) == "_N"]
    if len(p) == 2 and len(n_) == 2:
        return [(p[0], p[1]), (n_[0], n_[1])]
    return [(nets[0], nets[1]), (nets[2], nets[3])]  # pads 1-2 and 3-4


def find_chains(parts: Iterable[Part], sources: Iterable[str], destinations: Iterable[str],
                max_ohms: float = 100.0, with_caps: bool = False,
                max_rail_pads: int = 12) -> list[FoundChain]:
    parts = list(parts)
    src, dst = set(sources), set(destinations)
    pads_on: dict[str, list[str]] = {}
    for ref, _, pads in parts:
        for num, net in pads.items():
            if net:
                pads_on.setdefault(net, []).append(f"{ref}.{num}")
    bridges: dict[str, list[tuple[str, str]]] = {}  # net -> [(series ref, other net)]
    for ref, value, pads in parts:
        if ref in src or ref in dst:
            continue
        for a, b in _through_pairs(ref, value, pads, max_ohms, with_caps):
            bridges.setdefault(a, []).append((ref, b))
            bridges.setdefault(b, []).append((ref, a))

    found, seen = [], set()
    for ref, _, pads in parts:
        if ref not in src:
            continue
        for num, start in sorted(pads.items()):
            if not start or _is_rail(start, len(pads_on.get(start, [])), max_rail_pads):
                continue
            # breadth-first through series parts; first destination reached wins
            queue = [(start, (start,), ())]
            visited = {start}
            while queue:
                net, path, series = queue.pop(0)
                hits = [p for p in pads_on.get(net, []) if p.split(".")[0] in dst]
                if hits:
                    key = (path, series)
                    if key not in seen:
                        seen.add(key)
                        found.append(FoundChain("", path, series, f"{ref}.{num}", hits[0]))
                    break
                for part, other in bridges.get(net, []):
                    if other in visited or _is_rail(other, len(pads_on.get(other, [])),
                                                    max_rail_pads):
                        continue
                    visited.add(other)
                    queue.append((other, path + (other,), series + (part,)))
    name_and_group(found)
    return found


# ---------------------------------------------------------------- naming and grouping templates

def _leaf(net: str) -> str:
    return net.rstrip("/").split("/")[-1]


Limits = tuple[Optional[float], Optional[float], Optional[float]]  # skew, pair skew, stub max (ps)
TEMPLATES: list[tuple[re.Pattern, str, Limits]] = [
    # (pattern on the chain name, group name template, (skew, pair skew, stub max) ps)
    (re.compile(r"DDR_?DQS?(\d)([A-Z])?_(?:P|N)$"), "DDR_{1}_BYTE{0}", (3.5, 0.6, None)),
    (re.compile(r"DDR_?DQ(\d+)_([A-Z])$"), "DDR_{1}_BYTE{dq}", (3.5, 0.6, None)),
    (re.compile(r"DDR_?DM(\d)_([A-Z])$"), "DDR_{1}_BYTE{0}", (3.5, 0.6, None)),
    (re.compile(r"DDR_?(?:CA\d+|CKE\d*|CS\d*N?|ODT\d*(?:_CA)?)_([A-Z])$", re.I), "DDR_{0}_CA",
     (7.0, 0.6, None)),
    (re.compile(r"DDR_?CLK([A-Z])_(?:P|N)$"), "DDR_{0}_CA", (7.0, 0.6, None)),
    (re.compile(r"(RXD\d|RXDV|RX_?CTL|RXC(?:LK)?)", re.I), "RGMII_RX", (20.0, None, 15.0)),
    (re.compile(r"GMAC\d?_(TXD\d|TXEN|TX_?CTL|TXCLK)", re.I), "RGMII_TX", (20.0, None, 15.0)),
    (re.compile(r"HDMI.*TX", re.I), "HDMI", (30.0, 0.7, 12.0)),
    (re.compile(r"MIPI_(CSI|DSI)\w*?(?:RX|TX)", re.I), "MIPI_{0}", (10.0, 0.7, None)),
    (re.compile(r"USB\w*?_?(OTG\d|HOST\d)", re.I), "USB_{0}", (None, 0.7, 15.0)),
    (re.compile(r"^(EMMC|SDMMC\d?|SDIO\d?|FSPI|QSPI|SPI\d?)", re.I), "{0}", (15.0, None, 12.0)),
]
DEFAULT_LIMITS = (20.0, 1.0, 15.0)


def _clean(leaf: str) -> str:
    # strip "_PHY"/"_PORT"/"_CON" segment markers that only say which side of the part a net is
    return re.sub(r"_(PORT|CON|PHY|R)(?=_[PN]$|$)", "", leaf)


def _chain_name(c: FoundChain) -> str:
    """Prefer a net name that matches an interface template (e.g. FSPI_CLK over FLASH_SCLK)."""

    leaves = [_clean(_leaf(n)) for n in reversed(c.nets)]
    for leaf in leaves:
        if any(p.search(leaf) for p, _, _ in TEMPLATES):
            return leaf
    return leaves[0]


def _group_for(name: str) -> tuple[str, tuple]:
    for pat, template, limits in TEMPLATES:
        m = pat.search(name)
        if m:
            g = m.groups()
            dq = int(g[0]) // 8 if "{dq}" in template else None
            return template.format(*[x.upper() if x else "" for x in g], dq=dq), limits
    base = re.sub(r"(\d+|_[PN])+$", "", name).rstrip("_") or name
    return base, DEFAULT_LIMITS


def name_and_group(chains: list[FoundChain]) -> None:
    names: dict[str, int] = {}
    for c in chains:
        n = _chain_name(c)
        names[n] = names.get(n, 0) + 1
        c.name = n if names[n] == 1 else f"{n}_{names[n]}"
        c.group = _group_for(c.name)[0]
    by = {c.name: c for c in chains}
    for c in chains:
        m = re.match(r"^(.*?)(_P|_N)$", c.name)
        if m:
            mate = m.group(1) + ("_N" if m.group(2) == "_P" else "_P")
            c.pair = mate if mate in by else None


def suggest_groups(chains: Iterable[FoundChain]) -> list[GroupSuggestion]:
    out: dict[str, GroupSuggestion] = {}
    for c in chains:
        if not c.keep:
            continue
        if c.group not in out:
            _, (skew, pskew, stub) = _group_for(c.name)
            has_pair = c.pair is not None
            out[c.group] = GroupSuggestion(c.group, skew, pskew if has_pair or pskew else None,
                                           stub if len(c.nets) > 1 else None)
        g = out[c.group]
        g.chains.append(c)
        if len(c.nets) > 1 and g.stub_max_ps is None:
            g.stub_max_ps = _group_for(c.name)[1][2] or DEFAULT_LIMITS[2]
    return sorted(out.values(), key=lambda g: g.name)


def merge_into(config: Optional[Config], groups: Iterable[GroupSuggestion],
               die_ps_per_mm: float = 6.952) -> Config:
    """Add suggested groups to a config; an existing group with the same name is replaced."""

    new = {g.name: GroupDef(g.name, tuple(ChainDef(g.name, c.name, c.nets, c.series, c.pair)
                                          for c in g.chains),
                            g.skew_ps, g.pair_skew_ps, g.stub_max_ps) for g in groups}
    kept = [g for g in (config.groups if config else []) if g.name not in new]
    base = config.pad_to_die_ps_per_mm if config else die_ps_per_mm
    return Config(sorted(kept + list(new.values()), key=lambda g: g.name), base, auto=False)


def orient_by_placement(chains: Iterable[FoundChain],
                        pad_xy: Mapping[str, tuple[float, float]],
                        part_xy: Mapping[str, tuple[float, float]]) -> int:
    """Put the driver side first: a series terminator is placed next to its driver.

    For a chain with series parts, the endpoint pad nearer to the first/last series part is taken as
    the driver. Returns how many chains were reversed. Chains without positions are left as found.
    """

    flipped = 0
    for c in chains:
        if not c.series or c.source_pad not in pad_xy or c.dest_pad not in pad_xy:
            continue
        first, last = part_xy.get(c.series[0]), part_xy.get(c.series[-1])
        if first is None or last is None:
            continue
        d_src = _dist(pad_xy[c.source_pad], first)
        d_dst = _dist(pad_xy[c.dest_pad], last)
        if d_dst < d_src:
            c.nets, c.series = tuple(reversed(c.nets)), tuple(reversed(c.series))
            c.source_pad, c.dest_pad = c.dest_pad, c.source_pad
            flipped += 1
    return flipped


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def mark_untimed(chains: Iterable[FoundChain], netclass_of: Mapping[str, Optional[str]],
                 timed_classes: Iterable[str]) -> None:
    """Untick chains whose nets are in no timing-controlled netclass (resets, I2C, GPIO...)."""

    timed = set(timed_classes)
    for c in chains:
        c.keep = any(netclass_of.get(n) in timed for n in c.nets)


def dedupe(chains: Iterable[FoundChain]) -> list[FoundChain]:
    """Drop the same path found from both ends (keep the first, i.e. the oriented one)."""

    seen, out = set(), []
    for c in chains:
        key = frozenset(c.nets)
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out
