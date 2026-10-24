"""Net chains (xSignals): whole-signal timing through series parts. No KiCad runtime needed."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .profiles import ProjectTiming, via_height

DRC_BEGIN = "# --- BEGIN xSignal targets (kicad-pcb-automation-toolkit) ---"
DRC_END = "# --- END xSignal targets ---"


@dataclass(frozen=True)
class ChainDef:
    group: str
    name: str
    nets: tuple[str, ...]
    series: tuple[str, ...] = ()
    pair: Optional[str] = None

    @property
    def stub(self) -> Optional[str]:
        return self.nets[0] if len(self.nets) > 1 else None

    @property
    def tunable(self) -> str:
        return self.nets[-1]


@dataclass(frozen=True)
class GroupDef:
    name: str
    chains: tuple[ChainDef, ...]
    skew_ps: Optional[float] = None
    pair_skew_ps: Optional[float] = None
    stub_max_ps: Optional[float] = None


@dataclass
class Config:
    groups: list[GroupDef]
    pad_to_die_ps_per_mm: float = 6.952
    auto: bool = False  # detected from the board, not loaded from xsignals.json

    def chain_for_net(self, net: str) -> Optional[ChainDef]:
        for group in self.groups:
            for chain in group.chains:
                if net in chain.nets:
                    return chain
        return None

    def chain_for_series(self, ref: str) -> Optional[ChainDef]:
        for group in self.groups:
            for chain in group.chains:
                if ref in chain.series:
                    return chain
        return None

    def group(self, name: str) -> Optional[GroupDef]:
        return next((g for g in self.groups if g.name == name), None)


def selection_paths(group: GroupDef, name: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Nets and series parts for one chain, including its differential partner."""
    chain = next(c for c in group.chains if c.name == name)
    members = [chain] + [c for c in group.chains if c.name == chain.pair]
    nets = tuple(dict.fromkeys(n for c in members for n in c.nets))
    refs = tuple(dict.fromkeys(r for c in members for r in c.series))
    return nets, refs


def load_config(path: Path) -> Config:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    groups = []
    for gname, g in data["groups"].items():
        chains = tuple(
            ChainDef(gname, cname, tuple(c["nets"]), tuple(c.get("series", ())), c.get("pair"))
            for cname, c in g["chains"].items()
        )
        groups.append(GroupDef(gname, chains, g.get("skew_ps"), g.get("pair_skew_ps"),
                               g.get("stub_max_ps")))
    return Config(groups, float(data.get("pad_to_die_ps_per_mm", 6.952)))


def board_config_path(board_file: Path) -> Path:
    """Where the Signal Chain Editor stores a board's chains: <board>.traceforge.json."""

    return Path(board_file).with_suffix(".traceforge.json")


def find_config(project_dir: Path, board_file: Optional[Path] = None) -> Optional[Path]:
    """The board's own TraceForge file first, then a legacy xsignals.json (imported on save)."""

    candidates = [board_config_path(board_file)] if board_file else []
    candidates += [project_dir / "xsignals.json", project_dir / "docs/design/xsignals.json"]
    return next((c for c in candidates if c.exists()), None)


# ---------------------------------------------------------------- geometry snapshot -> delay


@dataclass(frozen=True)
class TrackSeg:
    layer: str
    length_mm: float


@dataclass(frozen=True)
class ViaHop:
    layers: tuple[str, str]  # the via's own start and end copper layers (its barrel span)


@dataclass
class NetGeometry:
    netclass: Optional[str] = None
    tracks: list[TrackSeg] = field(default_factory=list)
    vias: list[ViaHop] = field(default_factory=list)
    die_mm: list[float] = field(default_factory=list)

    @property
    def routed(self) -> bool:
        return bool(self.tracks)


@dataclass(frozen=True)
class NetDelay:
    track_ps: float
    via_ps: float
    die_ps: float
    complete: bool  # every track layer had a profile delay

    @property
    def total_ps(self) -> float:
        return self.track_ps + self.via_ps + self.die_ps


def net_delay(geo: NetGeometry, timing: ProjectTiming, z: Mapping[str, float],
              die_ps_per_mm: float) -> NetDelay:
    profile = timing.profile_for_netclass(geo.netclass)
    track = via = 0.0
    complete = profile is not None
    for seg in geo.tracks:
        d = profile.track_delay(seg.layer, seg.length_mm) if profile else None
        if d is None:
            complete = False
        else:
            track += d
    if profile:
        for hop in geo.vias:
            via += via_height(z, *hop.layers) * profile.via_ps_per_mm
    die = sum(geo.die_mm) * die_ps_per_mm
    return NetDelay(track, via, die, complete)


# ---------------------------------------------------------------- evaluation


@dataclass(frozen=True)
class ChainResult:
    chain: ChainDef
    total_ps: float
    tunable_ps: float
    stub_ps: Optional[float]
    routed: bool
    target_ps: Optional[float] = None
    tolerance_ps: Optional[float] = None
    pair_skew_ps: Optional[float] = None
    length_mm: Optional[float] = None  # Sum of track/arc lengths on all chain nets.
    tunable_mm: Optional[float] = None
    stub_mm: Optional[float] = None

    @property
    def delta_ps(self) -> Optional[float]:
        return None if self.target_ps is None else self.total_ps - self.target_ps

    @property
    def status(self) -> str:
        if not self.routed:
            return "pending"
        if self.target_ps is None:
            return "routed"
        if abs(self.delta_ps) <= (self.tolerance_ps or 0) + 1e-9:
            return "ok"
        return "short" if self.delta_ps < 0 else "long"


@dataclass(frozen=True)
class GroupResult:
    group: GroupDef
    chains: tuple[ChainResult, ...]
    target_ps: Optional[float]
    stub_violations: tuple[str, ...]

    @property
    def spread_ps(self) -> Optional[float]:
        done = [c.total_ps for c in self.chains if c.routed]
        return max(done) - min(done) if len(done) > 1 else None


def evaluate(config: Config, delays: Mapping[str, NetDelay],
             geometry: Mapping[str, NetGeometry]) -> list[GroupResult]:
    out = []
    track_mm = {n: sum(seg.length_mm for seg in geo.tracks) for n, geo in geometry.items()}
    for group in config.groups:
        totals, routed = {}, {}
        for c in group.chains:
            totals[c.name] = sum(delays[n].total_ps for n in c.nets if n in delays)
            routed[c.name] = all(geometry.get(n) is not None and geometry[n].routed for n in c.nets)
        done = [totals[k] for k, ok in routed.items() if ok]
        target = max(done) if done and group.skew_ps is not None else None
        results, stubs = [], []
        for c in group.chains:
            tgt, tol, pskew = target, (group.skew_ps / 2 if group.skew_ps else None), None
            if c.pair and c.pair in totals:
                if routed[c.name] and routed[c.pair]:
                    pskew = totals[c.name] - totals[c.pair]
                    if group.skew_ps is None:  # pair-only group: match P to N
                        tgt = max(totals[c.name], totals[c.pair])
                    if group.pair_skew_ps is not None:
                        tol = group.pair_skew_ps / 2
            stub = delays[c.stub].total_ps if c.stub and c.stub in delays else None
            if stub is not None and group.stub_max_ps is not None and stub > group.stub_max_ps:
                stubs.append(c.name)
            tun = delays[c.tunable].total_ps if c.tunable in delays else 0.0
            results.append(ChainResult(c, totals[c.name], tun, stub, routed[c.name],
                                       tgt if routed[c.name] else None, tol, pskew,
                                       sum(track_mm.get(n, 0.0) for n in c.nets),
                                       track_mm.get(c.tunable, 0.0),
                                       track_mm.get(c.stub, 0.0) if c.stub else None))
        out.append(GroupResult(group, tuple(results), target, tuple(stubs)))
    return out


# ---------------------------------------------------------------- DRC targets


def drc_rules(results: Iterable[GroupResult],
              board_name: Optional[Mapping[str, str]] = None) -> str:
    """Rules that make KiCad's tuner bring each chain total to its group target.

    `board_name` maps a config net name to the board's own name ('/' inside a sheet or label name
    is stored as {slash}); DRC conditions must use the board form.
    """

    names = board_name or {}

    def _cond(net: str) -> str:
        return "A.NetName == '" + names.get(net, net) + "'"

    lines = [DRC_BEGIN]
    for g in results:
        for c in g.chains:
            if c.chain.stub and g.group.stub_max_ps is not None:
                lines.append(f'(rule "XSIG {g.group.name} {c.chain.name} stub"\n'
                             f'\t(condition "{_cond(c.chain.stub)}")\n'
                             f"\t(constraint length (max {g.group.stub_max_ps:.2f}ps)))")
            if c.target_ps is None or c.tolerance_ps is None:
                continue
            opt = c.tunable_ps + (c.target_ps - c.total_ps)
            lo, hi = opt - c.tolerance_ps, opt + c.tolerance_ps
            lines.append(f'(rule "XSIG {g.group.name} {c.chain.name} total"\n'
                         f'\t(condition "{_cond(c.chain.tunable)}")\n'
                         f"\t(constraint length (min {lo:.2f}ps) (opt {opt:.2f}ps) "
                         f"(max {hi:.2f}ps)))")
    lines.append(DRC_END)
    return "\n".join(lines)


LEGACY_BEGIN = "# --- BEGIN xSignal targets (tools/xsignals.py; regenerate after routing) ---"


def merge_drc(existing: str, section: str) -> str:
    """Replace any previous xSignal section (this toolkit's or the legacy script's)."""

    for begin in (DRC_BEGIN, LEGACY_BEGIN):
        if begin in existing:
            start = existing.index(begin)
            end = existing.index(DRC_END, start) + len(DRC_END)
            existing = existing[:start] + existing[end:].lstrip("\n")
    return existing.rstrip("\n") + "\n\n" + section + "\n"


# ---------------------------------------------------------------- auto-detection


_OHMS = re.compile(r"^(\d+(?:\.\d+)?)\s*([rkRK]|ohm|Ω)?(\d*)$")


def series_ohms(value: str) -> Optional[float]:
    v = value.strip().replace("Ω", "R")
    m = _OHMS.match(v)
    if not m:
        return None
    x = float(m.group(1))
    return x * 1000 if (m.group(2) or "").lower() == "k" else x


def detect_chains(parts: Iterable[tuple[str, str, Mapping[str, str]]],
                  max_ohms: float = 100.0) -> list[tuple[str, tuple[str, ...]]]:
    """Find series links: 2-pad R <= max_ohms (or 0R) and 4-pad common-mode chokes.

    `parts` yields (reference, value, {pad_number: net}). Returns (reference, nets) links.
    """

    links = []
    for ref, value, pads in parts:
        nets = tuple(n for n in pads.values() if n)
        if ref.upper().startswith("R") and len(pads) == 2 and len(set(nets)) == 2:
            ohms = series_ohms(value)
            if ohms is not None and ohms <= max_ohms:
                links.append((ref, nets))
        elif ref.upper().startswith(("L", "FL")) and len(pads) == 4 and len(set(nets)) == 4:
            links.append((ref, nets))
    return links


Link = tuple[str, tuple[str, ...]]


def chain_nets(start: str, links: Iterable[Link]) -> tuple[set[str], set[str]]:
    """All nets and series refs reachable from `start` through 2-terminal series links."""

    nets, refs, frontier = {start}, set(), [start]
    links = [(r, n) for r, n in links if len(n) == 2]
    while frontier:
        cur = frontier.pop()
        for ref, pair in links:
            if cur in pair:
                other = pair[1] if pair[0] == cur else pair[0]
                refs.add(ref)
                if other not in nets:
                    nets.add(other)
                    frontier.append(other)
    return nets, refs


_PAIR = re.compile(r"^(.*?)(_P|_N|\+|-)$")


def _leaf(net: str) -> str:
    return net.rstrip("/").split("/")[-1]


def auto_config(links: Iterable[Link], netclass_of: Mapping[str, Optional[str]],
                timed_classes: Iterable[str], die_ps_per_mm: float = 6.952) -> Config:
    """Chains found on the board: series links between nets of timing-controlled netclasses.

    Nets joined through any number of 2-terminal series parts form one chain; chains are grouped
    by netclass, and _P/_N (or +/-) chains become pairs. Driver side, stub limits and skew targets
    are unknown, so auto groups report timing and highlight but write no DRC targets until the
    config is saved and reviewed.
    """

    timed = set(timed_classes)
    two = [(r, n) for r, n in links if len(n) == 2]
    seen: set[str] = set()
    by_class: dict[str, list[ChainDef]] = {}
    for _, pair in two:
        for start in pair:
            if start in seen:
                continue
            nets, refs = chain_nets(start, two)
            seen |= nets
            classes = {netclass_of.get(n) for n in nets} & timed
            if not classes:
                continue
            group = sorted(classes)[0]
            name = min((_leaf(n) for n in nets), key=len)
            by_class.setdefault(group, []).append(
                ChainDef(group, name, tuple(sorted(nets)), tuple(sorted(refs))))
    groups = []
    for group, chains in sorted(by_class.items()):
        names = {c.name for c in chains}
        paired = []
        for c in sorted(chains, key=lambda c: c.name):
            m = _PAIR.match(c.name)
            mate = None
            if m:
                other = {"_P": "_N", "_N": "_P", "+": "-", "-": "+"}[m.group(2)]
                mate = m.group(1) + other if m.group(1) + other in names else None
            paired.append(ChainDef(c.group, c.name, c.nets, c.series, mate))
        any_pair = any(c.pair for c in paired)
        groups.append(GroupDef(group, tuple(paired), pair_skew_ps=1.0 if any_pair else None))
    return Config(groups, die_ps_per_mm, auto=True)


def config_to_json(config: Config) -> str:
    """Serialise a config (e.g. an auto-detected one) as an editable xsignals.json."""

    data = {"pad_to_die_ps_per_mm": config.pad_to_die_ps_per_mm, "groups": {}}
    for g in config.groups:
        gd = {k: v for k, v in (("skew_ps", g.skew_ps), ("pair_skew_ps", g.pair_skew_ps),
                                ("stub_max_ps", g.stub_max_ps)) if v is not None}
        gd["chains"] = {c.name: {k: v for k, v in (("nets", list(c.nets)),
                                                   ("series", list(c.series)),
                                                   ("pair", c.pair)) if v} for c in g.chains}
        data["groups"][g.name] = gd
    return json.dumps(data, indent=1) + "\n"
