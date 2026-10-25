# TraceForge 0.7.0

Initial review release for KiCad 10 on Windows.

## Included

- Native pcbnew board access without the official IPC API dependency.
- Signals / xSignals tab with manual timing snapshots, chain lengths, differential
  pair highlighting, stable automatic zoom, chain editing and CSV export.
- Via Stitching tab with symmetric and staggered grids, via presets/netclass/custom
  sizes, spacing/offsets, setbacks, selected-zone/drawing and whole-board regions.
- Rectangle/polygon drawing and colored preview in the board overview.
- UUID-based stitching sets with selection, removal, regeneration and Undo/Redo.
- Light/dark themes and colored status indicators.

## Install

Download `TraceForge-0.7.0-KiCad10-Windows.zip`, verify its SHA256 against
`SHA256SUMS.txt`, and extract it to a permanent folder. Run
`tools/install_native_bridge.ps1` in PowerShell, then restart PCB Editor. Open a saved
board and launch TraceForge from its toolbar button or Tools > External Plugins.
No administrator access or pip runtime dependencies are required.

Keep `<board>.traceforge-stitching.json` alongside the saved PCB to retain stitching
set ownership and settings. Keep signal-chain configuration alongside the board too.

## Known limits

- KiCad 10/Windows only; legacy bindings are planned for removal in KiCad 11.
- Region drawing is in the tab overview, not directly in the PCB canvas.
- Custom DRC-rule evaluation and courtyard filtering are incomplete. Run KiCad DRC
  after placement. Preview limits bound large candidate grids; refill can occupy
  KiCad's GUI thread briefly.
- Signal measurements aggregate net copper and estimated delays; they do not exactly
  reproduce KiCad's point-to-point tuner.
- This release does not implement parallel bus routing, microvias or perimeter fences.

## Validation

Local unit/lint checks and synthetic-board integration checks passed before packaging.
Live editor checks covered placement, native selection, regeneration, removal,
Undo/Redo and save/reopen recovery. No user boards or generated project data are
included. Public CI validates lint, Python compilation and release packaging.
