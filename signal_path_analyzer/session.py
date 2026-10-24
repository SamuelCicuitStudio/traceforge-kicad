"""Shared state for the net-chain actions: project files, timing model, chain config, evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .chains import (
    ChainDef,
    Config,
    GroupResult,
    chain_nets,
    detect_chains,
    drc_rules,
    evaluate,
    find_config,
    load_config,
    merge_drc,
    net_delay,
)
from .kicad_adapter import board_names, series_parts, snapshot
from .profiles import ProjectTiming, load_project_timing, load_stackup_z


@dataclass
class Session:
    board: Any
    project_dir: Path
    board_file: Path
    timing: ProjectTiming
    z: dict
    config: Optional[Config]
    config_file: Optional[Path]

    @classmethod
    def open(cls, board: Any) -> Session:
        project_dir = Path(board.document.project.path)
        board_file = project_dir / Path(board.document.board_filename).name
        pro = board_file.with_suffix(".kicad_pro")
        timing = load_project_timing(pro) if pro.exists() else ProjectTiming()
        cfg_file = find_config(project_dir)
        config = load_config(cfg_file) if cfg_file else None
        return cls(board, project_dir, board_file, timing, load_stackup_z(board_file), config,
                   cfg_file)

    @property
    def die_ps_per_mm(self) -> float:
        return self.config.pad_to_die_ps_per_mm if self.config else 0.0

    def all_nets(self) -> list[str]:
        if not self.config:
            return []
        return sorted({n for g in self.config.groups for c in g.chains for n in c.nets})

    def evaluate(self) -> list[GroupResult]:
        """Live snapshot of every configured chain -> per-group results."""

        if not self.config:
            return []
        geo = snapshot(self.board, self.all_nets())
        delays = {n: net_delay(g, self.timing, self.z, self.die_ps_per_mm) for n, g in geo.items()}
        return evaluate(self.config, delays, geo)

    def resolve_chain(
        self, net: Optional[str] = None, ref: Optional[str] = None
    ) -> tuple[list[str], list[str], Optional[ChainDef]]:
        """Chain of a net or series part: from the config, else auto-detected via series parts."""

        if self.config:
            cfg = self.config
            chain = cfg.chain_for_net(net) if net else cfg.chain_for_series(ref or "")
            if chain:
                return list(chain.nets), list(chain.series), chain
        links = detect_chains(series_parts(self.board))
        if ref and not net:
            net = next((n[0] for r, n in links if r == ref), None)
        if not net:
            return [], [], None
        nets, refs = chain_nets(net, links)
        return sorted(nets), sorted(refs), None

    def write_drc_targets(self, results: list[GroupResult]) -> Path:
        dru = self.board_file.with_suffix(".kicad_dru")
        existing = dru.read_text(encoding="utf-8") if dru.exists() else "(version 1)\n"
        section = drc_rules(results, board_names(self.board, self.all_nets()))
        dru.write_text(merge_drc(existing, section), encoding="utf-8", newline="\n")
        return dru
