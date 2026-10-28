# Changelog

Release details: [0.12.1](docs/RELEASE-NOTES.md).

## TraceForge 0.12.1 (2026-10-28)

- Publish the 0.12 feature set as a stable KiCad 10 Windows PCM package.
- Keep the 0.12.0 testing package available for existing downloads.
- No routing or UI behavior changes from 0.12.0.

## TraceForge 0.12.0 (2026-10-28)

- Consolidate the 0.11.8–0.11.26 local builds into a published release.
- Group stitching, RF fencing, and existing-via arrays in Via Tools.
- Group cleanup, illustrated native teardrop controls, and rounded trace corners
  in Trace Tools; add bulk selection to cleanup findings.
- Preview and round eligible corners using actual item clearances, optional
  smaller radii, exact-net filtering, and detailed skip reasons.
- Restore selected or all managed rounded corners after saving and reopening
  when the board's `.traceforge-fillets.json` sidecar is retained.
- Improve via-array connectivity handling, visualization, and panel lifecycle.
- Target Windows and KiCad 10. Run DRC and recheck timing/skew after copper edits.

## TraceForge 0.11.26 (local test build)

- Use each copper item's actual netclass/local clearance instead of the board's
  maximum clearance when checking proposed fillet arcs.
- Allow smaller radii up to the chosen maximum when a short segment or nearby
  copper makes the full radius impossible. A checkbox keeps exact-radius mode.
- Show skip counts by reason and allow previewing one exact net name.
- On the SIM-node board at a 0.5 mm maximum, preview 1,884 eligible corners,
  including 472 adjusted smaller bends; add/save/reopen/restore-all recovered
  every original straight-track shape on a disposable copy.

## TraceForge 0.11.25 (local test build)

- Check the real proposed arc against nearby copper geometry, avoiding false
  rejections from the old broad bounding-box test.
- Add **Restore all rounded corners** alongside selective restore. This includes
  all nets and differential-pair traces previously rounded by TraceForge.
- Verify a 208-corner add/save/reopen/restore-all cycle on a disposable copy of
  the SIM node board, recovering every original straight track shape.

## TraceForge 0.11.24 (local test build)

- Add board-wide and selected-track corner rounding with a chosen radius.
- Preview eligible corners across all copper layers and explain skipped corners.
- Restore individual TraceForge-generated arcs to their original straight shape
  using a persistent board sidecar, including after reopening the PCB.
- Keep the edit undoable through KiCad's native ActionPlugin transaction.

## TraceForge 0.11.23 (local test build)

- Fix Apply and the advanced teardrop shortcut not opening KiCad's dialog.
  Deliver KiCad's menu command to its native PCB Editor window. Verified Add
  and Remove on a disposable board in the real KiCad 10 PCB Editor.

## TraceForge 0.11.22 (local test build)

- Show labeled teardrop diagrams for vias, through-hole pads, surface pads, and
  track junctions beside their target controls. Illustrate the shared length,
  width, and pad/via size measurements without implying KiCad supports separate
  size settings for each target.

## TraceForge 0.11.21 (local test build)

- Add in-Forge teardrop controls for Add/Remove, whole-board/selected scope,
  pad and via targets, shape, and dimensions. Apply uses KiCad's native editor
  generator and Undo transaction. Track-to-track teardrops use board defaults.
- Keep the advanced KiCad dialog available for its other filters and settings.

## TraceForge 0.11.20 (local test build)

- Combine Trace Cleanup and Teardrops in one Trace Tools tab with a top-right
  selector. The Teardrops view opens KiCad's native Edit Teardrops dialog.
- Move the teardrop shortcut out of Visualization so the trace controls share
  one place. Cleanup scan behavior and bulk selection remain available.

## TraceForge 0.11.19 (local test build)

- Add Select all and Unselect all to Trace Cleanup. They affect findings shown
  by the active copper-layer filter and preserve checkbox choices across
  filter changes. The existing dangling-track confirmation remains in place.

## TraceForge 0.11.18 (local test build)

- Combine Via Stitching, Via Fencing, and Via Array into one Via Tools tab with
  a selector at the top right. Preserve each workflow's controls and F5 refresh.

## TraceForge 0.11.17 (local test build)

- Close the TraceForge panel automatically when the PCB Editor instance that
  launched it closes, including when KiCad is closed. Keep the existing manual
  close behavior and single-instance cleanup.

## TraceForge 0.11.16 (local test build)

- Via Array Apply no longer refills zones or marks them for refill. The user
  controls zone updates with KiCad's B shortcut.

## TraceForge 0.11.15 (local test build)

- Make Via Array Apply responsive by moving the selected vias and checking
  connectivity without immediately refilling every copper zone on the board.
- Mark zones for refill and show the KiCad B shortcut required before DRC or
  fabrication. Undo continues to restore the via positions.

## TraceForge 0.11.14 (local test build)

- Judge an array move by whether each previously connected copper layer still
  has same-net copper at the proposed position, including pads, tracks,
  drawings and filled zones. The original item need not remain in contact.
- Allow same-net via copper to sit close together; retain drill-to-drill
  spacing checks for selected and nearby existing vias.
- Validate the 15-via backplane selection as a 3 x 5 array, including a
  successful zone refill and unchanged layer connectivity on an in-memory copy.

## TraceForge 0.11.13 (local test build)

- Correct Via Array clearance checks for vias on the same net. Their copper
  clearance does not apply between selected vias; the board's drill spacing
  still does.
- Make an auto-detected array's blocked vias explicit in the preview and
  explain when connected copper prevents a safe move.

## TraceForge 0.11.12 (local test build)

- Auto detect the selected via array's rows and columns using the layout with
  the least total via movement. The 12-via backplane selection resolves to
  3 rows and 4 columns without entering a count.
- Show current via positions and the proposed grid side by side before Apply.
  Keep manual row or column counts available as an override.

## TraceForge 0.11.11 (local test build)

- Add Via Array to fit selected existing vias inside their current bounding
  rectangle using a fixed number of rows or columns. Preview attachment and
  clearance checks before an undoable move.
- Add live net group colors, additive component ratsnest focus, and quick access
  to KiCad's native teardrop editor in Visualization.

## TraceForge 0.11.5

- Redesign About as a product overview with the plugin icon, supported KiCad
  version, tool summaries, author, license, and links to documentation and issues.
- Keep installation paths, helper version, and log location behind an optional
  diagnostic section that can be copied when support is needed.

## TraceForge 0.11.4

- Check that the external panel and the in-process PCB Editor helper run the same
  version. A stale helper now produces a clear restart message before a board
  operation, instead of the old 5,000-grid-location error.
- Show the helper version and loaded path on the About tab.

## TraceForge 0.11.3 (local PCM test build)

- Add an About tab and put the running version in the window title. The tab shows
  the loaded code path and log path so an older installed copy can be identified.
- The About tab does not trigger a board scan or an automatic revision check.

## TraceForge 0.11.2 (local PCM test build)

- Normalize rectangle corners for drags in either direction, both in the Via
  Stitching overview and for rectangles selected in PCB Editor.
- Keep the overview's mouse drag active if the pointer leaves its edge before
  release.

## TraceForge 0.11.1 (local PCM test build)

- Via Stitching now streams a whole-board grid instead of rejecting regions at
  5,000 candidate locations. The preview still checks board edges, copper fills,
  keepouts, tracks, pads and vias before offering any locations to apply.
- Precomputed inset copper makes dense previews practical on large boards.
- The normal Via Stitching form shows the net, via source and center-to-center
  X/Y spacing; the other placement controls are under Advanced options.
- Dense stitching has longer preview/apply deadlines and the board overview
  samples display markers so it remains responsive.

## TraceForge 0.11.0

- Add BGA fit guidance and a bounded Auto escape to BGA edge mode for selected
  single-ended pads, with per-pad accepted and blocked results.
- Apply accepted routes in one KiCad undoable operation. Live PCB Editor testing
  confirmed Apply, Undo, Redo and managed removal on a disposable 4 by 4 BGA.
- Add a KiCad 10 Windows Plugin and Content Manager package and official-repository
  submission metadata alongside the standalone Windows ZIP.
- Replace demonstration screenshots in the README with current PCB Editor captures
  on the management board and the BGA test board.

## TraceForge 0.10.1

- Trace Cleanup now shows findings and counts for every copper layer, with an
  explicit layer filter. A filtered view applies only its checked rows.
- Partially overlapping, collinear tracks with the same net, layer, width and mask
  settings can be fused into one continuous segment. The complete copper span and
  connector-to-connector route are preserved. Fusion uses KiCad's undoable action.
- Duplicates and dangling endpoints continue to be previewed separately. Dangling
  removals start unchecked and require review.
- TraceForge's stale pad-selection fix and Recheck length matching remain available.

Validated on two-layer synthetic boards: F.Cu and B.Cu produced independent fuse
rows; 40 mm of duplicate-counted copper became 30 mm of continuous copper and
KiCad Undo restored 40 mm. Endpoint detection still connected the same two pads
through the fused F.Cu route.

Close all KiCad windows, including KiCad Manager, then update/reinstall TraceForge
and reopen PCB Editor. Supports KiCad 10 on Windows. Run DRC after reviewed edits.

## TraceForge 0.10.0

- New **Trace Cleanup** tab: scan the whole board or an exact net for duplicate
  tracks, fully covered straight tracks and dangling endpoints.
- Preview and highlight findings before removing checked tracks with native
  KiCad Undo. Redundant tracks start checked; dangling tracks start unchecked
  and require review because they may be intentional or unfinished routing.
- **Recheck length matching** returns to Signals and refreshes the measurements.
- Preserve partial overlaps, vias, locked/grouped items and unassigned copper.
  Geometry changes invalidate removal previews; dangling connectivity is checked
  again before deletion. No periodic polling or automatic board saving.
- Fix stale pad-selection flags after switching paths or making another PCB
  selection. Newly selected native items are preserved; pan/zoom retains focus.

Close all KiCad windows, including KiCad Manager, run
`tools/install_native_bridge.ps1`, then reopen PCB Editor and TraceForge.
Supports KiCad 10 on Windows. Run DRC after reviewing cleanup changes.

## TraceForge 0.9.9

Native net focus now applies automatically whenever TraceForge highlights a signal
path or differential pair. Unrelated copper dims without enabling an option.
The Signals checkbox has been removed. Clear, Esc or a changed native selection
releases focus; panning and zooming retain it. All branches on highlighted nets
remain bright.

Close all KiCad windows, including KiCad Manager, run
`tools/install_native_bridge.ps1`, then restart PCB Editor.
The installer configures the required native highlight shortcut while preserving
existing custom bindings. This step is required when updating from older versions.

Supports KiCad 10 on Windows.

## TraceForge 0.9.8

Adds **Dim unrelated nets** in the Signals tab. Enable it to keep the selected
chain or differential pair bright while KiCad dims unrelated copper. Works with
chains crossing series resistors/capacitors and endpoint path detection. Native
net focus includes all branches of each highlighted net. Clear, Esc or a changed
native selection releases focus; panning and zooming retain it.

Rerun the installer with PCB Editor closed, then restart PCB Editor and reopen
TraceForge. The installer configures an unused Ctrl+Alt+Shift+F12 shortcut for
KiCad's Highlight Net (selected nets) action when it has no binding. It preserves
custom bindings and backs up a changed user.hotkeys file. Shortcut conflicts are
reported instead of overwritten. Clear Net Highlighting must also have a shortcut.
The installer now respects KICAD_CONFIG_HOME when set.

Verified on a disposable PCB Editor with repeated visual on/off cycles, switching
nets and Clear. Native geometry/ownership checks cover multi-net differential
chains. No global keyboard input or continuous board/selection polling is used.

Supports KiCad 10 on Windows. Existing signal timing, via stitching, RF fencing
and through-via BGA fanout features remain available. Preview generated geometry,
keep ownership sidecars with the board, and run KiCad DRC before manufacturing.

## TraceForge 0.9.7 - KiCad 10 preview

TraceForge combines signal-path/timing analysis, managed via stitching, RF trace
fencing and BGA fanout in one native pcbnew-based panel for Windows/KiCad 10.

- Guided first/second endpoint picking and detection through series resistors and
  capacitors across different net names, with differential-pair review.
- Change-aware tab refresh without continuous polling or automatic retry loops.
- Path highlights retained while panning and zooming.
- Symmetric/staggered stitching, trace-following fences on both sides, editable
  net inputs and RF spacing guidance.
- BGA suggestions, preview, apply and managed removal for through-via breakouts.
- Public repository cleanup, illustrated README and install/update instructions.
  Removed obsolete web/Tk dashboards; the Signals tab is the timing interface.
- Installer can safely switch an existing junction with `-ReplaceExisting`.

Extract the Windows ZIP to a permanent folder, close PCB Editor and run
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\install_native_bridge.ps1`.
Restart PCB Editor, open a saved board and launch TraceForge from its toolbar.
Use `-ReplaceExisting` when changing the installation folder.

Keep generated ownership sidecars with the PCB. Preview placements and run KiCad
DRC. Microvias, full BGA escape routing and live parallel multirouting are not
implemented. This is a pre-release for review and testing.

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
