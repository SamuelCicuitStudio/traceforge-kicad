# Changelog

Historical release notes. Current release: [0.9.7](docs/RELEASE-NOTES.md).

## TraceForge 0.9.6

Fixed highlighted paths disappearing as soon as a PCB mouse button was pressed.
Hold-and-drag navigation, wheel zoom, middle/right presses and navigation keys
retain the highlight. A deferred check after click/key completion clears it when
the native selection actually changes or Esc is pressed. Cleanup preserves the
new native selection instead of restoring the original one over it.

Checks are event driven, without periodic selection polling. Delayed cleanup from
an earlier highlight cannot clear a newly highlighted path. Restart PCB Editor and
reopen TraceForge to load the updated native event filter.

## TraceForge 0.9.5

Tabs load automatically on first opening. Returning to TraceForge after editing in
PCB Editor, or revisiting a tab, makes one change check. Unchanged tabs skip the
full refresh. Changed tabs refresh through the shared worker; Signals retains its
existing rows, scroll position and expanded groups. Managed via lists retain set
selection across refreshes. BGA analysis also responds to selection changes.

The check uses KiCad's revision plus a read-only geometry/settings signature to
catch direct pcbnew edits that do not advance the revision. No periodic board
polling, selection polling or retry loop is introduced. Region drawing is left
undisturbed. Busy tab checks coalesce until the current operation completes.
Automatic failures retain prior data; F5 remains the explicit refresh fallback.

Automatic updates happen on tab/focus transitions, not continuously while routing.
Restart PCB Editor and reopen TraceForge to load the revision helper update.

## TraceForge 0.9.4

Endpoint path detection now follows all two-pad series resistors by default rather
than silently stopping at the old 100-ohm threshold. This supports indicator and
other signal paths crossing higher-value series resistors and multiple net names.
The new **Follow all series resistors** checkbox can be disabled to restore the
explicit resistor limit. Series capacitor traversal remains configurable.

This is a connectivity path view, not a claim that arbitrary resistors preserve
high-speed signal integrity. Power/ground rails and component internals remain
excluded. Geometry and routing must still connect the selected endpoints.

Restart PCB Editor and reopen TraceForge to load the updated native detector.

## TraceForge 0.9.3

- Via Fencing accepts typed fence-net names and a one-click **Pick fence net in PCB**.
- Type or pick the source signal net to load its routed, connected single-layer path.
  Use selected trace for branched, disconnected or multilayer nets.
- Guided path detection prompts for first and second PCB endpoints sequentially,
  then detects and highlights the path. Available in both chain dialogs.
- Native picking completes a single pending request from a canvas event, without
  selection polling. Esc cancels, and a pending pick expires after 90 seconds.

Restart PCB Editor and reopen TraceForge to load the new native picker.

## TraceForge 0.9.2

Endpoint detection accepts two pads, vias, tracks/arcs or footprints, including mixed
types. Selecting components with several possible signals opens a pad-pair choice
before routed-copper tracing. Candidates use the configured passive traversal rules;
the chosen path must still be physically routed. Up to 128 choices are shown.

Both Chain Editor selection buttons use this workflow for any two selected PCB items.
AC-coupling capacitor traversal is enabled by default. The resistor limit remains
visible and adjustable; errors explain restrictions rather than saying a path is
not allowed. Power/ground rails and component internals remain excluded.

Restart PCB Editor once and reopen TraceForge to load the updated native detector.

## TraceForge 0.9.1

Fixed the Signal Chain Editor's **Use KiCad selection** buttons silently ignoring
selected pads and vias. Both buttons now detect the routed endpoint path, highlight
and fit it, preview crossed parts, include a resolvable differential partner and
report existing-chain matches. New definitions are staged until **Apply & save**.

Added an explicit **Detect path from 2 selected pads / vias** button in the editor.
Footprint selection continues to fill component references. Invalid selections
display a useful error; endpoint searches run in a worker without polling.

Close and reopen the TraceForge window to load this panel update. No new helper
operation is required when the native helper from 0.9.0 is already running.

## TraceForge 0.9.0

- Signals: select two vias/pads to detect, highlight and fit a routed endpoint path.
- Configurable resistor/capacitor traversal and reviewed differential partner detection.
- Report existing chain coverage; append new definitions without overwriting groups.
- Via Fencing: RF spacing helper with frequency, saved dielectric data and editable
  permittivity; choose wavelength/10 or wavelength/20 independently of copper gap.
- Validated the actual Both sides tab controls and native placement on a synthetic
  RF route containing a straight section, an arc and 45-degree bends.

Restart PCB Editor and reopen TraceForge after updating the native helper. Detection
is manual and does not change copper. Saved chains continue to cover whole nets;
the selected-endpoint preview is a separate routed-path view. RF suggestions are
estimates, not an impedance or antenna solver.

## TraceForge 0.8.1

Adds a dedicated **Via Fencing** tab for ground vias along selected RF/antenna-feed
traces, distinct from the perimeter pattern in Via Stitching.

- Follow selected connected straight tracks and arcs on one net/layer.
- Choose left, right or both sides, spacing, lateral copper gap and via sizes.
- Preview source identity, accepted/rejected locations and largest fence gap.
- Native clearance/connectivity checks and undoable managed set operations.
- Separate trace-fence lists from ordinary stitching sets.
- Reject branches, disconnections, loops, signal-net fences and stale source paths.

See [Via Fencing](docs/VIA-FENCING.md) for the workflow and limitations.
This uses through vias; it does not add HDI or automatic RF design.

## TraceForge 0.8.0

Adds **BGA Fanout**, a third tab for selected-footprint pad-to-via breakout.

- Detect rectangular-grid X/Y pitch and footprint orientation/side.
- Preview dogbone stubs with automatic half-pitch or custom X/Y offsets.
- Explicit via-in-pad mode with fabrication-support confirmation.
- Active/named board presets, per-net netclass or custom via dimensions.
- Net/pad wildcard filters, clearance and width controls, per-pad rejection reasons.
- Native, undoable placement with live revalidation, single-use tokens, refill and
  pad-to-via connectivity checking. Existing routed pads are skipped.
- Geometry-checked through-via suggestions and UUID-based removal of generated fanout,
  preserving manual routing and edited/locked items. Ownership recipes are stored
  alongside the board in `.traceforge-fanout.json`.
- Perimeter via fencing in the Via Stitching tab, with inset contours/cutouts,
  managed placement/removal and largest-gap reporting when sites are rejected.

This is an initial breakout implementation, not full BGA escape routing or live
multirouting. Vias are through-hole only; no pair coupling or length matching.
See [BGA Fanout](docs/BGA-FANOUT.md) for limitations and the test workflow.

Signals / xSignals and Via Stitching remain available in the first two tabs.
Install the same way as 0.7 and restart PCB Editor once after upgrading.

## TraceForge 0.7.0

Initial review release for KiCad 10 on Windows.

### Included

- Native pcbnew board access without the official IPC API dependency.
- Signals / xSignals tab with manual timing snapshots, chain lengths, differential
  pair highlighting, stable automatic zoom, chain editing and CSV export.
- Via Stitching tab with symmetric and staggered grids, via presets/netclass/custom
  sizes, spacing/offsets, setbacks, selected-zone/drawing and whole-board regions.
- Rectangle/polygon drawing and colored preview in the board overview.
- UUID-based stitching sets with selection, removal, regeneration and Undo/Redo.
- Light/dark themes and colored status indicators.

### Install

Download `TraceForge-0.7.0-KiCad10-Windows.zip`, verify its SHA256 against
`SHA256SUMS.txt`, and extract it to a permanent folder. Run
`tools/install_native_bridge.ps1` in PowerShell, then restart PCB Editor. Open a saved
board and launch TraceForge from its toolbar button or Tools > External Plugins.
No administrator access or pip runtime dependencies are required.

Keep `<board>.traceforge-stitching.json` alongside the saved PCB to retain stitching
set ownership and settings. Keep signal-chain configuration alongside the board too.

### Known limits

- KiCad 10/Windows only; legacy bindings are planned for removal in KiCad 11.
- Region drawing is in the tab overview, not directly in the PCB canvas.
- Custom DRC-rule evaluation and courtyard filtering are incomplete. Run KiCad DRC
  after placement. Preview limits bound large candidate grids; refill can occupy
  KiCad's GUI thread briefly.
- Signal measurements aggregate net copper and estimated delays; they do not exactly
  reproduce KiCad's point-to-point tuner.
- This release does not implement parallel bus routing, microvias or perimeter fences.

### Validation

Local unit/lint checks and synthetic-board integration checks passed before packaging.
Live editor checks covered placement, native selection, regeneration, removal,
Undo/Redo and save/reopen recovery. No user boards or generated project data are
included. Public CI validates lint, Python compilation and release packaging.
