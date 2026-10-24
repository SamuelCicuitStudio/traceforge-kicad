# TraceForge - KiCad 10 PCB tools

TraceForge 0.6 uses KiCad 10's embedded `pcbnew` interface for all board access.
The colored wxPython panel runs separately and talks to an authenticated native helper
inside PCB Editor. KiCad's official IPC API and the kicad-python SDK are not required.

## Install on Windows

1. Keep this checkout in a permanent directory.
2. Run `tools/install_native_bridge.ps1` from PowerShell.
3. Save your work and restart PCB Editor once.
4. Open your board and click the native **TraceForge** toolbar button, or use
   **Tools > External Plugins > TraceForge**.
5. Click **Refresh** or press **F5** while the panel has focus.

The installer creates a junction under
`%APPDATA%/kicad/10.0/scripting/plugins/traceforge_native_bridge`.
KiCad's bundled Python and wxPython run the panel; no pip runtime dependencies are needed.
The previous official-IPC `plugin.json` is archived under `docs/legacy/` and is no longer
registered. The native toolbar has the same light/dark TraceForge icons.

## Panel features

- Manual timing snapshots, including unsaved board routing and tuning changes.
- Green matched, amber tuning warning, red error, blue routed, and gray pending states,
  with symbols and live snapshot counts in light and dark themes.
- Chain track length, tunable length and stub length in mm, alongside delay, target,
  delta, differential-pair skew and stub timing in ps.
- Click a chain to highlight it and automatically zoom. Differential partners are included.
  Native zoom uses the editor's zoom presets and focus controls, without official API calls.
  After the initial fit, automatic selection preserves magnification for nearby or shorter
  chains and zooms out only when more room is needed. **Zoom selection** explicitly refits.
- Highlights clear on the next click or key action in PCB Editor. Only Forge-owned flags
  are restored; unrelated selection flags are preserved.
- Stable table refresh preserves scroll, row selection and collapsed groups.
- Highlight group, clear highlight, explicit zoom, CSV export and DRC target generation.
- Signal Chain Editor: find paths between ICs/connectors through series parts, review
  groups and timing limits, and save the board-specific configuration.
- Configurable keyboard shortcuts in the PCB canvas while the panel is open.

All board operations run through the native helper on KiCad's GUI thread. The panel accepts
one operation at a time and does not poll or automatically retry failed operations.
Zone stitching and parallel routing remain planned features, not implemented routing tools.

## Chains and timing

Chains are saved as `<board>.traceforge.json`. Legacy `xsignals.json` files are also read;
without either, TraceForge can detect chains from board parts and timing netclasses.
The editor follows resistors up to a selected resistance, common-mode chokes and optional
AC-coupling capacitors. Rails and unrelated ICs stop the search.

QSPI `FLASH_CS` is a separate monitoring group with no automatic length target.
Interface templates supply suggestions, not validated board timing requirements.
Review limits and the driver/stub orientation before writing DRC targets.

Timing uses per-layer propagation profiles from `.kicad_pro`, via barrel height from
the stackup and configured pad-to-die lengths. Profiles must be validated for fabrication.
The current model sums net copper, including branches and disconnected segments; it does
not reproduce KiCad's point-to-point tuner and pad clipping exactly. Via delay currently
uses the whole via barrel. Millimeter columns sum tracks/arcs only and exclude via barrels,
component internals and package lengths. Unrouted paths remain pending.

## Native commands

The native plugin registers four distinct actions:

- TraceForge: open or activate the colored panel.
- TraceForge: Highlight Signal Chain: highlight the current PCB selection's chain.
- TraceForge: Export Signal Paths: write `<board>.signal-paths.csv`.
- TraceForge: Signal Timing Monitor: open the optional older timing dashboard.

Each launcher passes its own editor endpoint and board filename to the external process.
With multiple PCB Editors open, launch from the intended board's native button. Standalone
launch without a specified board rejects ambiguous editor connections.

The panel shortcuts are Ctrl+Alt+H (chain), Ctrl+Alt+G (group), Ctrl+Alt+C (clear),
Ctrl+Alt+W (DRC targets), Ctrl+Alt+E (export), and Ctrl+Alt+T (show/hide).
Change them through **Shortcuts**. Settings are stored in `%APPDATA%/TraceForge/settings.json`;
logs are in `%APPDATA%/TraceForge/traceforge.log`.

## Development and checks

Install development dependencies with `python -m pip install -e ".[dev]"`, then run
`python -m pytest -q` and `python -m ruff check .`.

Run KiCad's bundled Python with
`tools/check_native_bridge.py BOARD.kicad_pcb` to test a separate in-memory board copy,
unsaved geometry changes, highlight cleanup, native transport and main-thread dispatch.
This test does not save or alter the source board file.

See [native board access](docs/NATIVE-BOARD-ACCESS.md) for transport and installation details.
The earlier [API reliability audit](docs/API-RELIABILITY-AUDIT.md) records the migration history.

## Compatibility

This version targets **KiCad 10 on Windows**. It uses legacy pcbnew bindings that KiCad plans
to remove in version 11. There is no official IPC fallback. Keeping the panel and calculations
separate from the native helper gives a clear boundary for future backend migrations.
