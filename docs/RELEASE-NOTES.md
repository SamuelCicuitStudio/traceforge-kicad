# TraceForge 0.12.1 — Stable KiCad 10 Windows release

TraceForge 0.12.1 publishes the 0.12 feature set as **stable** for Windows and
KiCad 10. There are no routing or user-interface behavior changes from 0.12.0.
The existing 0.12.0 testing archive remains available. Use the 0.12.1 PCM ZIP
for KiCad's Plugin and Content Manager.

The release includes rounded track corners with persistent restore, native
teardrop controls, Via Tools, Trace Tools, visualization, and BGA fanout.
Download `TraceForge-0.12.1-KiCad10-PCM.zip` and select **Plugin and Content
Manager > Install from file**. Close all KiCad windows and reopen PCB Editor
after installation. `SHA256SUMS.txt` covers the PCM and standalone ZIPs.

Automated tests, lint, compilation, and package validation passed. The 0.12.0
development checks below document the feature behavior and limitations. After
editing copper, refill zones as needed, run DRC, and recheck length and skew.

---

# TraceForge 0.12.0 — Rounded corners, teardrops, and unified PCB tools

Released 2026-10-28 for **Windows and KiCad 10**. This release consolidates the
0.11.7–0.11.26 development work following the published 0.11.6 release.

## What's new

- **Via Tools:** switch between via stitching, RF fencing, and existing-via
  arrays in one tab, retaining each tool's settings and manual F5 refresh.
- **Trace Tools:** switch between cleanup, teardrops, and rounded corners.
  Cleanup gains Select all / Unselect all for the active layer filter.
- **Rounded trace corners:** preview whole-board or selected-track bends,
  choose a maximum radius, optionally fit smaller bends down to 0.05 mm,
  filter by an exact net name, and inspect skip reasons. Clearance checks use
  the proposed arc and actual item/netclass clearances.
- **Persistent restore:** restore selected or all TraceForge-managed rounded
  corners, including after saving and reopening the board. Keep
  `<board>.traceforge-fillets.json` beside the PCB to retain restore records.
- **Native teardrops:** illustrated controls for Add/Remove, board or selected
  scope, pad/via targets, shape, and dimensions, plus KiCad's advanced dialog.
- **Via arrays and BGA:** improved layer-connectivity checks for moving existing
  vias and support for mixed-pitch BGA arrays. Via Array leaves zone refill
  under the user's control.
- **Visualization and lifecycle:** net-group colors, ratsnest filtering, and
  automatic panel closure with the launching PCB Editor instance.

## Installation and upgrade

1. Download `TraceForge-0.12.0-KiCad10-PCM.zip` below.
2. In KiCad Manager, choose **Plugin and Content Manager > Install from file**.
3. Close all KiCad windows and reopen PCB Editor to load the new version.

For a standalone installation, use `TraceForge-0.12.0-KiCad10-Windows.zip`
and follow the included README. `SHA256SUMS.txt` contains both archive hashes.
No pip runtime dependencies or IPC API token are required.

## Validation and limits

- Automated suite: 138 passed, 1 skipped. Release lint, Python compilation,
  version consistency, ZIP CRC, and package allowlist checks also pass.
- Prior local KiCad checks recorded below include real-editor teardrop
  Add/Remove and disposable-board rounded-corner save/reopen/restore cycles.
  These are development checks, not a guarantee for every board or rule set.
- Windows and KiCad 10 only; the plugin remains experimental (PCM: testing).
  Live parallel multirouting is planned and is not included.
- After copper edits, refill zones as needed, run KiCad DRC, and recheck
  lengths and differential-pair skew. Custom rules and pair spacing still
  require review. Track-to-track teardrops use Board Setup defaults and must
  be applied separately; selected-only scope does not support them.

---

# TraceForge 0.11.26 — Fit more eligible track corners (local test build)

The previous preview applied the board's **largest** configured clearance to
every net. It now uses the actual clearance of the trace and nearby copper.
The requested radius is a maximum by default: when the full radius cannot fit,
TraceForge tries a smaller radius down to 0.05 mm. Uncheck **Fit smaller bends**
to require the exact radius. The preview lists skipped reasons with positions;
an optional exact-net filter helps inspect one signal.

At 0.5 mm on the SIM node, the read-only preview accepted 1,884 corners, 472
at a smaller radius, and skipped 1,207. A disposable board copy completed a
1,884-corner add/save/reopen/restore-all round trip with exact original track
geometry recovered. Differential-pair spacing and custom rules still require
KiCad DRC and a length/skew recheck after applying.

# TraceForge 0.11.25 — Correct arc clearance and Restore all (local test build)

The Round Corners preview now tests the actual proposed copper arc against
nearby pads, vias and tracks. The earlier rectangular approximation falsely
rejected valid bends. On the SIM node PCB, both `SEC09_RST_N` corners at
198.3125/151.6175 mm and 200.56/149.37 mm are now eligible at 0.5 mm.

**Restore all rounded corners** restores every TraceForge-managed fillet on the
open board, including differential-pair nets. **Restore selected** remains
available. A disposable copy of the SIM node was rounded at 208 corners,
saved/reopened, and restored; every original straight-track shape matched.
Run DRC and recheck length/skew after rounding.

# TraceForge 0.11.24 — Whole-board rounded trace corners (local test build)

Trace Tools now includes **Round Corners**. Set a radius, preview all copper
layers or selected tracks, and round only simple two-segment corners that fit.
The preview reports skipped junctions. Select a generated arc or adjacent track
to restore its original straight corner later, including after reopening the
saved PCB. Keep `<board>.traceforge-fillets.json` beside the PCB for selective
restore. The edit participates in KiCad Undo. Recheck timing and run DRC after
rounding because changed paths and nearby zones/custom rules need review.

Verified add/restore on a disposable KiCad 10 board using the pcbnew bindings;
the backplane was scanned read-only at 0.5 mm, finding 91 eligible corners and
6,710 skipped junctions. The live PCB Editor UI still needs a user test.

# TraceForge 0.11.23 — Working KiCad teardrop Apply (local test build)

The previous Apply and advanced dialog buttons reported success even though
KiCad did not open the dialog. KiCad's C++ menu command did not run when
TraceForge posted a synthetic wx menu event. TraceForge now sends the native
window menu command to PCB Editor.

Verified in KiCad 10 PCB Editor on a disposable pad-and-track board: Add
increased generated teardrop areas from 0 to 1, Remove returned them from
1 to 0, and the advanced button opened **Set Teardrops**. The installed
0.11.22 files used for this test were restored afterwards; install the
0.11.23 PCM package and restart PCB Editor to load the fix.

# TraceForge 0.11.22 — Illustrated teardrop controls (local test build)

The Teardrops view now shows diagrams alongside via, through-hole pad,
surface-mount pad, and track-junction targets. A legend labels pad/via size
(`d`), teardrop length (`L`), and width (`W`). Curved and straight choices
update the diagrams. The pad/via size fields are grouped as a shared KiCad 10
rule, while track-junction teardrops remain tied to Board Setup defaults.

# TraceForge 0.11.21 — Direct teardrop controls (local test build)

The Trace Tools > Teardrops view now has Add/Remove, whole-board or selected
items, curved or straight edges, via/PTH/SMD targets, and size controls.
**Apply to PCB** drives KiCad 10's native teardrop generator, retaining KiCad's
Undo transaction. The advanced KiCad dialog remains available. Track-to-track
teardrops use Board Setup defaults and must be applied separately; selected-only
scope does not support them. KiCad 10 does not expose separate size rules for
round and rectangular pads through this dialog. Run DRC after applying.

The form was exercised in a KiCad 10 wx window and the native dialog command,
control mapping, and Apply event were exercised in a synthetic PCB Editor
window. A real PCB Editor end-to-end application still needs user verification.

# TraceForge 0.11.20 — Trace Tools tab (local test build)

Trace Cleanup and Teardrops now share one **Trace Tools** tab. Use its selector
at the top right to switch between them. Teardrops has a direct button to open
KiCad's native Edit Teardrops dialog; the old shortcut has been removed from
Visualization. Cleanup still loads a lightweight board overview and scans only
from Scan / Preview. The selector, F5 routing, and native command dispatch were
exercised in a KiCad 10 wx window without changing a project board.

# TraceForge 0.11.19 — Trace Cleanup bulk selection (local test build)

Trace Cleanup now has **Select all** and **Unselect all** above the findings
table. The buttons affect the rows shown by the current layer filter; changing
the filter preserves reviewed checkbox choices. Select all can include
dangling tracks, so Apply still requests confirmation before removing them.

# TraceForge 0.11.18 — Unified Via Tools tab (local test build)

Via Stitching, Via Fencing, and Via Array now share one **Via Tools** tab. Use
the selector at the top right to switch between them. Each tool keeps its own
settings, preview, and manual F5 refresh. Via Array still reads the PCB
selection only when requested. The three modes and F5 dispatch were exercised
in the KiCad 10 wx window without opening a project board.

# TraceForge 0.11.17 — Close with PCB Editor (local test build)

TraceForge now tracks the PCB Editor process that launched it. Closing that
editor, or closing KiCad, closes the TraceForge window automatically. The
lightweight window check runs on the panel's existing timer. A temporary
Windows wx frame was used to verify detection while visible and after close.

# TraceForge 0.11.16 — Manual zone refill for Via Array (local test build)

Via Array Apply now moves the vias and checks their connections without
refilling zones or changing their refill flags. Refill remains entirely under
the user's control through **B** in PCB Editor.

# TraceForge 0.11.15 — Faster Via Array Apply (local test build)

Via Array now moves the selected vias immediately, checks their existing copper
connections, and marks zones for refill. It no longer refills the whole board
during Apply. On the backplane's 15-via selection, the measured full zone refill
alone took about 7.9 seconds; positioning the vias took less than 1 ms. The
in-memory no-refill path kept all previously connected layers connected.

**Press B in PCB Editor to refill zones before DRC, saving a manufacturing
output, or continuing with another Via Array preview.** Undo still restores
the via positions. The original backplane board was not modified by testing.

# TraceForge 0.11.14 — Same-net copper-aware Via Array (local test build)

Via Array now checks physical same-net copper contact on each affected layer
at the proposed via position. A via may move within a copper area or from one
same-net contact to another without needing to keep the exact old contact.
Same-net via copper spacing is allowed; the drill-to-drill minimum remains
checked for selected and nearby existing vias. Other-net clearance and board
edge checks remain in place.

The 15-via BUS_12V_PROTECTED selection on the backplane is auto detected as
3 rows by 5 columns and now previews with zero blockers. Moving them on an
in-memory board copy, refilling zones, and checking previous layer connections
passed. The original project board was not changed.

# TraceForge 0.11.13 — Via Array connection checks (local test build)

The 15 selected vias in the backplane example are auto detected as **3 rows
by 5 columns**. Their proposed centers have 0.780 mm row spacing. The previous
preview incorrectly applied another-net copper clearance between these vias,
producing false via-to-via warnings. Same-net selected vias now use KiCad's
drill-to-drill minimum. The preview still identifies four vias whose proposed
positions would lose existing track, pad, or copper contact. These require
routing changes before the exact even grid can be applied safely.

The preview displays blocked vias in red and states the detected grid and
number of blocked vias. The original backplane PCB was inspected read-only.

# TraceForge 0.11.12 — Via Array auto layout and visual preview (local test build)

Select existing vias in PCB Editor and click **Read & preview selection**.
TraceForge infers the existing row and column arrangement from the via centers,
then shows side-by-side diagrams of the current positions and proposed even
grid. It calculates X and Y center spacing within the selected vias' current
bounds. The backplane example with 12 vias is recognized as 3 rows by 4
columns. Rows and Columns remain available as manual overrides. Apply stays
disabled when moving a via would lose a connection or violate clearance.

The real backplane selection was previewed read-only: auto detect returned
3 rows by 4 columns with no placement issues. The visual preview was rendered
offscreen to confirm the same layout. KiCad DRC and Undo on a disposable copy
remain the validation for applying vias; the original project was not edited.

# TraceForge 0.11.11 — Via Array (local test build)

**Via Array** rearranges 1–64 selected existing vias on the open PCB. Choose a
fixed row or column count; TraceForge fits the remaining dimension and equal
center spacing inside the selected via centers' bounding rectangle. Preview
shows old and new locations. Apply uses KiCad's undoable native board edit and
refills zones. The preview blocks lost track or pad attachments, insufficient
same-net copper contact, keepouts, board-edge violations, and copper or via
clearance conflicts. The tool does not create vias.

The **Visualization** tab supports live net-group and individual net colors,
additive component ratsnest focus, reset to default colors, and access to
KiCad's native teardrop editor.

The 12-via BUS_12V_PROTECTED cluster on the backplane was moved to a 3 × 4
array on a disposable PCB. KiCad DRC after zone refill reported the same 78
findings and zero unconnected items as the original. The original board was
unchanged. The PCM archive is a local test build for KiCad 10 on Windows;
install it with **Plugin and Content Manager > Install from file** after
closing all KiCad windows. Open the Via Array tab, select vias in PCB Editor,
and preview before applying. Run KiCad DRC after application.

# TraceForge 0.11.7 — Variable-pitch BGA preview (testing)

The BGA Fanout tab now recognizes rectangular pad arrays whose X/Y spacing
changes across rows and columns, including mixed-pitch outer rings and inner
arrays. Zero X/Y dogbone offset uses each pad's adjacent gap; the preview and
Auto escape use the actual pad-field bounds. Staggered/perimeter patterns still
need a separate strategy. Via, track and clearance rules remain unchanged.

KiCad's TFBGA257 0.5/0.65 mm footprint was analyzed on a disposable board.
A too-large through-via was correctly blocked by native copper clearance, while
a second disposable uneven-pitch array produced an accepted read-only dogbone
and Auto escape preview. The RK3566 CPU U6 in DroneLink was analyzed read-only: its mixed
0.40/0.65 mm pads were detected, while sample dogbones were blocked by the
board's 0.5/0.3 mm minimum through-via and nearby copper. The project board
was not edited. The Python suite and lint checks pass. Live PCB Editor review remains
the next step before changing this build's PCM status from testing.

Install the local `TraceForge-0.11.7-KiCad10-PCM.zip` through **Plugin and
Content Manager > Install from file**, close all KiCad windows, and reopen PCB
Editor. The TraceForge title and About tab should show 0.11.7.

# TraceForge 0.11.6 — BGA selection repair

This update restores the board-boundary helper required by the native BGA
fanout module. In 0.11.5, **Analyze PCB selection** failed before reading the
selected footprint with `cannot import name 'fits' from stitching_native`.
Version 0.11.6 restores that helper and checks whether proposed vias and
tracks remain inside the board outline and clear of its edges and cutouts.
The BGA selection flow was also verified in PCB Editor after the fix.

Install `TraceForge-0.11.6-KiCad10-PCM.zip` with KiCad's Plugin and Content
Manager **Install from file**. Close all KiCad windows before reopening PCB
Editor. The TraceForge title and About tab should show 0.11.6.

# TraceForge 0.11.5 — Dense via stitching and clearer plugin information

TraceForge 0.11.5 updates the KiCad 10 Windows plugin with practical whole-board
via stitching at fine center-to-center spacing and clearer installation diagnostics.

## Changes since 0.11.0

- Via Stitching previews large grids without the previous 5,000-location limit.
  The basic form shows the net, via source, and X/Y center-to-center pitch;
  placement pattern, offsets, and setbacks remain under Advanced options.
- Rectangle regions work when dragged in any direction. The overview captures
  the mouse during the drag, including when it leaves the overview boundary.
- The window title and About tab show the running version. The redesigned About
  page describes the tools, compatibility, license, and project links. Optional
  diagnostics show the panel and PCB Editor helper paths and versions.
- A stale panel or PCB Editor helper now produces a version mismatch message
  instead of repeating the old grid-limit error. Restart all KiCad windows
  after updating the plugin.

## Install

For KiCad Plugin and Content Manager, download
`TraceForge-0.11.5-KiCad10-PCM.zip` and choose **Install from file**. Close all
KiCad windows, including Manager and PCB Editor, then reopen the board. The
TraceForge window title and About tab should both report version 0.11.5.

The `TraceForge-0.11.5-KiCad10-Windows.zip` asset is for standalone manual
installation; follow the README's standalone instructions. `SHA256SUMS.txt`
contains hashes for both archives.

## Verification and limits

On the saved 02-BACKPLANE-BOARD, a 0.45/0.2 mm via at 0.6 × 0.6 mm
center-to-center pitch previewed 14,362 accepted locations and 54,938 skipped
locations in 47 seconds. This was a read-only preview of the saved board, not
a live placement test. Four rectangle drag directions, KiCad native stitching
integration, the Python tests, and lint checks passed.

TraceForge keeps the requested grid pitch and skips sites blocked by copper,
keepouts, board edges, or other geometry. It does not enlarge the pitch to fit
a candidate limit. Run KiCad DRC after applying vias, especially where project
specific fabrication rules apply.
