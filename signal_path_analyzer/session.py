"""Shared state for the net-chain actions: project files, timing model, chain config, evaluation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .chains import (
    ChainDef,
    Config,
    GroupResult,
    auto_config,
    board_config_path,
    chain_nets,
    config_to_json,
    detect_chains,
    drc_rules,
    evaluate,
    find_config,
    load_config,
    merge_drc,
    net_delay,
)
from .kicad_adapter import board_names, netclass_of, positions, series_parts, snapshot
from .pathfinder import dedupe, find_chains, mark_untimed, name_and_group, orient_by_placement
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
    native: Any = None

    @classmethod
    def open(cls, board: Any) -> Session:
        project_dir = Path(board.document.project.path)
        board_file = project_dir / Path(board.document.board_filename).name
        pro = board_file.with_suffix(".kicad_pro")
        timing = load_project_timing(pro) if pro.exists() else ProjectTiming()
        cfg_file = find_config(project_dir, board_file)
        config = load_config(cfg_file) if cfg_file else None
        session = cls(board, project_dir, board_file, timing, load_stackup_z(board_file), config,
                      cfg_file)
        from .native_client import connect

        session.native = connect(board_file)
        logging.info("Board access backend: %s", "native" if session.native else "IPC API")
        if config is None:
            session.config = session.detect()
        return session

    def detect(self) -> Optional[Config]:
        """Auto-detected chains for a project without xsignals.json (None when nothing found)."""

        parts = self.native.call('parts') if self.native else series_parts(self.board)
        links = detect_chains(parts)
        nets = sorted({n for _, pair in links for n in pair})
        classes = self.native.call('netclasses') if self.native else netclass_of(self.board, nets)
        config = auto_config(links, classes,
                             self.timing.netclass_profile.keys())
        return config if config.groups else None

    def save_config(self, config: Optional[Config] = None) -> Path:
        """Store the chains in <board>.traceforge.json (also imports a legacy xsignals.json)."""

        if config is not None:
            self.config = config
        path = board_config_path(self.board_file)
        path.write_text(config_to_json(self.config), encoding="utf-8")
        self.config_file, self.config.auto = path, False
        return path

    def find_between(self, sources: list[str], destinations: list[str], max_ohms: float = 100.0,
                     with_caps: bool = False) -> list:
        """Signal chains from source to destination parts, driver side inferred from placement."""

        parts = self.native.call('parts') if self.native else series_parts(self.board)
        found = find_chains(parts, sources, destinations, max_ohms, with_caps)
        pads, parts_xy = self.native.call('positions') if self.native else positions(self.board)
        orient_by_placement(found, pads, parts_xy)
        found = dedupe(found)
        nets = sorted({n for c in found for n in c.nets})
        classes = self.native.call('netclasses') if self.native else netclass_of(self.board, nets)
        mark_untimed(found, classes, self.timing.netclass_profile.keys())
        name_and_group(found)  # names/pairs after orientation
        return found

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
        geo = (self.native.snapshot(self.all_nets()) if self.native else
               snapshot(self.board, self.all_nets()))
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
        parts = self.native.call('parts') if self.native else series_parts(self.board)
        links = detect_chains(parts)
        if ref and not net:
            net = next((n[0] for r, n in links if r == ref), None)
        if not net:
            return [], [], None
        nets, refs = chain_nets(net, links)
        return sorted(nets), sorted(refs), None

    def write_drc_targets(self, results: list[GroupResult]) -> Path:
        dru = self.board_file.with_suffix(".kicad_dru")
        existing = dru.read_text(encoding="utf-8") if dru.exists() else "(version 1)\n"
        names = (self.native.call('names') if self.native else
                 board_names(self.board, self.all_nets()))
        section = drc_rules(results, names)
        dru.write_text(merge_drc(existing, section), encoding="utf-8", newline="\n")
        return dru
