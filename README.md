# TraceForge

Signal-chain analysis and managed via stitching for **KiCad 10 on Windows**.

| Feature | Status | What it does |
| --- | --- | --- |
| Signals / xSignals | Available | Analyze timing and chain lengths, highlight pairs, edit chains and export results |
| Via Stitching | Available | Preview and manage symmetric or staggered via grids inside chosen regions |
| Parallel multirouting | Planned | Route an ordered bundle of nets along a shared guide |

TraceForge 0.7 uses KiCad 10's embedded `pcbnew` interface for all board access.
The colored wxPython panel runs separately and talks to an authenticated native helper
inside PCB Editor. KiCad's official IPC API and the kicad-python SDK are not required.

## Install on Windows

1. Download and extract the release ZIP, or clone this repository, into a permanent directory.
2. Open PowerShell in that directory and run:

   ```powershell
   .\tools\install_native_bridge.ps1
   ```

3. Save your work and restart PCB Editor once.
4. Open your board and click the native **TraceForge** toolbar button, or use
   **Tools > External Plugins > TraceForge**.
5. Click **Refresh** or press **F5** while the panel has focus.

The installer creates a junction under
`%APPDATA%/kicad/10.0/scripting/plugins/traceforge_native_bridge`.
KiCad's bundled Python and wxPython run the panel; no pip runtime dependencies are needed.
The native toolbar supports light and dark TraceForge icons.

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
The window has **Signals / xSignals** and **Via Stitching** tabs. Switching tabs retains
their state without reading the board. F5 refreshes only the active tab.

## Via stitching

Restart PCB Editor after updating the helper, open TraceForge and select **Via Stitching**.

1. Click **Refresh board** (or F5 in this tab), then choose the net.
2. Choose **Symmetric** (aligned rows) or **Staggered** (alternate rows offset by half
   the X spacing). Set center-to-center X/Y spacing, offsets and setbacks in mm.
3. Use the active board via preset, the chosen net's netclass, a listed board preset,
   or custom diameter/drill. Resolved sizes are shown before placement.
4. Choose **Whole board**, **Use PCB selection** for a copper zone/non-copper drawing,
   or draw a rectangle/polygon on the tab's **board overview**. Drag a rectangle;
   click polygon vertices and press Enter/right-click to finish; Esc cancels.
5. Click **Preview**. Green locations are accepted, amber locations are skipped and
   blue locations belong to existing sets. Review rejection reasons, then **Apply stitching**.
6. Use the set list to select stitching vias, regenerate a set or remove managed vias.
   Placement, regeneration and removal support KiCad Undo/Redo. Save the PCB normally.

The helper checks board cutouts, via keepouts, filled copper on at least two layers
(or every copper layer), board minimums and conservative geometry clearance. Refilling
zones and a native connectivity check follow placement. Refill zones in KiCad before
previewing if fills are missing/stale. Preview is read-only; Apply revalidates it.
Large grids are limited to 5,000 candidates and previews have a time budget.

Set ownership and recipes are stored in `<board>.traceforge-stitching.json` using exact
via UUIDs. Keep this file alongside the PCB, including when copying/renaming a project.
Undo history records are retained so sets recover after Undo/Redo and save/reopen.
Ordinary vias are preserved; removal/regeneration also preserve managed vias that were
manually moved, resized, renetted or locked. Missing metadata prevents managed removal.

Drawing is currently in the overview, not directly on KiCad's canvas. Full custom DRC
rule evaluation, courtyard exclusion, and copper/text bounding-box optimizations remain
follow-up work; run KiCad DRC after placement. Board operations/refill can briefly occupy
the editor's GUI thread. See [native board access](docs/NATIVE-BOARD-ACCESS.md).

## Parallel multirouting: planned

Parallel multirouting is a feasible extension, but **it is not included in 0.7**.
The proposed third tab, **Multirouting**, would guide an ordered bundle of separate
nets together. Each lane retains its own net identity and follows an offset from a
shared route. Width and spacing do not imply equal electrical lengths.

The first implementation should support:

1. Pick source pads or existing track ends and explicitly map them to destinations.
2. Review, reorder or reverse lanes before routing.
3. Set the copper layer, track width and edge-to-edge spacing, respecting per-net limits.
4. Draw a shared guide with straight and 45-degree segments and preview every lane.
5. Reject colliding or invalid bundles before placing tracks.
6. Apply the reviewed bundle as one undoable operation and validate it with KiCad DRC.

Start with **single-layer block routing**: stop at obstacles instead of moving existing
copper. Fan-out geometry, inside-corner spacing and destination approach need explicit
validation; simply copying a trace sideways is insufficient. Source/destination mapping
must be checked again against the live board before applying a preview.

The current native helper can create tracks and capture changes through its undoable
action path. The installed pcbnew bindings do not provide the full interactive router
as a callable Python interface. Live PCB-canvas drawing, push-and-shove, walk-around
and coordinated layer transitions therefore need separate prototypes and may require
a compiled KiCad extension or source changes. An overview-based guide editor is a
practical first interaction, as with the current stitching region editor.

Differential-pair constraints, length matching, automatic lane swaps and via transitions
are later work. They should not be implied by a basic parallel routing preview.
See the [routing scope](docs/FEATURE-SCOPE.md#interactive-parallel-multi-routing) for
the intended behavior. The Multirouting tab will be added when there is a working
prototype; the current release continues to show its two implemented tabs.

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

The native plugin exposes four user-facing actions:

- TraceForge: open or activate the colored panel.
- TraceForge: Highlight Signal Chain: highlight the current PCB selection's chain.
- TraceForge: Export Signal Paths: write `<board>.signal-paths.csv`.
- TraceForge: Signal Timing Monitor: open the optional older timing dashboard.

An additional internal **Apply Stitching Changes** action provides native undo handling;
use the Via Stitching tab rather than invoking this action directly.

Each launcher passes its own editor endpoint and board filename to the external process.
With multiple PCB Editors open, launch from the intended board's native button. Standalone
launch without a specified board rejects ambiguous editor connections.

The panel shortcuts are Ctrl+Alt+H (chain), Ctrl+Alt+G (group), Ctrl+Alt+C (clear),
Ctrl+Alt+W (DRC targets), Ctrl+Alt+E (export), and Ctrl+Alt+T (show/hide).
Change them through **Shortcuts**. Settings are stored in `%APPDATA%/TraceForge/settings.json`;
logs are in `%APPDATA%/TraceForge/traceforge.log`.

## Development and checks

Install development dependencies with `python -m pip install -e ".[dev]"`.
Run `python -m ruff check .` and `python -m compileall -q signal_path_analyzer native_bridge`.
Local unit/integration tests and generated board fixtures are intentionally ignored.
Public CI validates source checks and builds the same allowlisted release ZIP.

Build a release ZIP with `python tools/build_release.py`; output is written to `dist/`.
It includes the runnable toolkit, native helper, installer, icons, license and public docs.
It excludes Git history, tests, caches, credentials and user project data.

See [native board access](docs/NATIVE-BOARD-ACCESS.md) and
[stitching testing](docs/VIA-STITCHING-TESTING.md) for operational details.

## Compatibility

This version targets **KiCad 10 on Windows**. It uses legacy pcbnew bindings that KiCad plans
to remove in version 11. There is no official IPC fallback. Keeping the panel and calculations
separate from the native helper gives a clear boundary for future backend migrations.
