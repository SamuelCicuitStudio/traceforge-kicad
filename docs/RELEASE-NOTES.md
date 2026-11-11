# TraceForge 0.13.3 - Windows PCM release

The 0.13.3 GitHub release contains the Windows KiCad 10 PCM ZIP and checksum.
No macOS 0.13.3 asset is published.

Routed chains with missing timing profiles now display "timing profile missing"
instead of 0.0 ps / matched. They are excluded from skew targets and generated
timing DRC rules until every chain net has a usable layer delay.

Automatic chain discovery no longer creates a 15 ps source-net length limit.
The old value measured all copper on the first net, including branches, and
could incorrectly appear as a routing requirement or create KiCad DRC errors.
The source-net delay remains visible for review. A project can still set an
explicit limit in the Signal Chain Editor when justified by its design rules.

The inspector now reports vias whose drilled hole or copper annulus touches an
SMT pad, even when the via center lies outside the pad. It scans all nets and
groups expanded results by full via-in-pad (green), partial hole overlap (red),
and annulus-only partial overlap (amber). Standalone via cleanup opens a
full-height view inside the Via Stitching tab, with a button back to placement
setup. A placement checkbox keeps vias away from SMT pads by default;
intentional same-net pad placement can be enabled explicitly.

Trace Cleanup now detects a narrow straight track fully contained within a
wider same-net, same-layer track, including offset and angled centerlines and
the 0.25 mm segment under a 0.6 mm segment reported by the user. The narrow
track is offered for removal; the wider track remains unchanged. When KiCad's
Selection Filter excludes the requested item type, selection-based tools now
explain which filter to enable; board-wide scans remain independent of selection.

---

# TraceForge 0.13.1 - via inspection and faster cleanup

The Via-in-Pad Inspector scans the live board for vias whose centers are inside
exposed SMT pads. Results are grouped by component, with each pad via shown under
its component. Click a via to select and zoom to it in PCB Editor, or click the
component to focus all its listed vias. The scan is read-only; the user
can inspect and edit each via with KiCad's normal tools. The Windows PCM is released
separately from the macOS standalone preview. The Mac build requires Python 3 with
wxPython for the separate panel and has not been exercised in a live KiCad session.

Inspector row focus skips renderer dimming and its extra full-board refreshes.
The inspector shows a local loading animation during scan and select/zoom work.
The shared loading animation now also covers signal selection and other background
KiCad actions. Via Stitching opens a new Stitching Cleanup view for standalone
through vias; it can select all listed unlocked vias for manual deletion. The view
reports actual connected-layer count so valid zone-only stitching can be distinguished
from vias connected on fewer than two layers. It never deletes vias automatically.
Deleting stitching vias, generated fanout items or Via Size Manager vias now defers
zone fill; press B in KiCad when ready, before DRC/export. Placement actions still refill
zones when their connectivity check requires filled copper.

---

# TraceForge 0.13.0 - independent manual installers

This prerelease provides separate KiCad 10 standalone ZIPs for Windows and macOS. The Windows ZIP retains the PowerShell junction installer. The macOS ZIP adds a shell installer that links the extracted plugin into KiCad's user scripting-plugin directory and records a Python 3 interpreter able to import wxPython for the separate TraceForge panel. Both ZIPs contain the same plugin source and can be downloaded independently. The existing Windows-only PCM ZIP is also attached as an alternative installation method.

**Windows:** Download `TraceForge-0.13.0-KiCad10-Windows.zip`, extract it to a permanent folder, close KiCad, then run `tools/install_native_bridge.ps1` in PowerShell as described in the README.

**macOS preview:** Download `TraceForge-0.13.0-KiCad10-macOS.zip`, extract it to a permanent folder, close KiCad, then run `bash tools/install_native_bridge_macos.sh --python /absolute/path/to/python3`. The selected Python must import `wx`. The installer accepts `--plugins-dir` if KiCad's actual plugin search path differs from the default. Restart PCB Editor after installation.

Archive contents, checksums, Python compilation and the macOS installer mechanics are verified automatically. **The plugin's live board editing, toolbar, Undo, and manufacturing workflows have not yet been exercised in KiCad 10 on macOS.** The macOS asset is a preview and should be tested on a noncritical board first. Windows-only native teardrop menu dispatch and automatic net-focus shortcut assignment are not enabled on macOS. No KiCad 11 support is claimed.

---

# TraceForge 0.12.10 - Multi-group highlighting

Select multiple groups in the Signals / xSignals tab and highlight their routes together in KiCad. This helps inspect related interfaces and capture routing views for fabrication review.

- Ctrl+click selects separate rows; Shift+click selects a range.
- Highlight groups merges all selected groups, including groups selected through child rows, and updates the board highlight once.
- Shared nets and series components are deduplicated.
- Ctrl/Shift selection does not trigger an individual-chain highlight or collapse the selected rows.
- Selected rows are preserved when the timing tree is rebuilt, where those rows still exist.
- Single-chain highlighting and the existing KiCad-selection fallback remain available.

## Installation

Windows and KiCad 10 only. Install `TraceForge-0.12.10-KiCad10-PCM.zip` using KiCad Plugin and Content Manager, or use the standalone Windows package. Close TraceForge and all KiCad windows after updating so the new panel and native helper load together. A build-identity check rejects stale helpers.

## Validation

Local unit tests and lint pass. Multi-selection was exercised with KiCad's bundled wxPython tree control, including a single combined native highlight request, duplicate removal, modifier-click selection preservation, single-group behavior and empty-selection fallback. Both release archives are checked for integrity and the public PCM download must match its submitted metadata checksum.

This release retains the 0.12.9 via-management, cancellation and focus-lifecycle fixes. No PCB manufacturing dimensions or board artwork are changed by this update. KiCad catalog availability depends on acceptance of the metadata merge request.

---

# TraceForge 0.12.9 - Stable KiCad 10 Windows Release

Focus lifecycle correction: via focus now owns and releases its renderer state
independently of a preceding wire highlight, including partially failed dimming
attempts. Click-away and Escape release temporary visuals without restoring an
old selection over a new PCB pick. Cleanup never steals input focus, and bounded
post-click checks allow native selection to settle without continuous polling.
Wire-to-via-to-blank-space transitions were exercised with a real PCB canvas click.


Highlight regression correction: restores the shared 0.12.8 native dispatch path
for existing signal/endpoint highlighting and zoom. Via-only dimming uses a
separate dispatcher; an optional dimming failure no longer blocks verified native
via selection, zoom or property editing. A build-identity handshake rejects stale
0.12.9 helpers after installing a corrected testing package.


Adds a global **Cancel operation** control for Via Size Manager analysis,
stitching/RF-fencing previews, BGA previews and cleanup scans. Cancellation is
cooperative across processes, discards unfinished previews, and terminates only
the owned temporary-board DRC child. Atomic undoable board edits cannot be
cancelled halfway through.


Preset detection now reads live Board Setup via dimensions and netclass defaults,
including sizes with zero placed vias. Target choices include these project sizes.
A helper capability check rejects an older 0.12.9 process instead of silently
showing the old inventory; close every KiCad window after updating.

Same-diameter/drill-only growth uses local hole checks without a full routing scan
or unnecessary zone refill. It checks annular rings, custom hole bounds and nearby
hole/copper/edge clearances; unsupported custom rules fall back to full DRC.


Via filter selection now **replaces KiCad's actual selection** and verifies exact
via UUIDs after synchronization. It does not select other vias, pads or tracks
merely because they share GND. Right-click editing uses that native selection.
Neutral renderer dimming avoids highlighting the entire filtered net; unconnected
net-0 copper can remain undimmed. When neutral dimming is unavailable, the tool
reports that explicitly instead of expanding the selection to a whole net.


Also fixes stitching/fencing near fiducials and critical footprints: optical mask
openings, both-side courtyards, missing-courtyard bounds and configurable reference
patterns now create previewed exclusion regions. Existing sets must be regenerated
to use the new protections; manually placed or locked vias are not silently removed.

Adds **Via Tools > Via Size Manager** for existing-via diameter/drill inventory,
net and selection filters, PCB selection, and undoable bulk deletion with an
explicit count confirmation and locked-via protection.

Enlargement previews use the live PCB and saved project/custom rules on temporary
copies. KiCad DRC refills zones and compares all findings against a baseline;
conflicting candidates are removed and the final batch is tested together.
The map and per-via reasons show what can grow and how many small drills remain,
including whole-board counts. Apply validates that the board and rules have not
changed, then resizes/refills in a single undoable native action.

This is a **stable release for Windows and KiCad 10**. Automatic growth
supports uniform ordinary through vias only. It is conservative and does not
maximize every possible combination, validate electrical performance or predict
price. Existing DRC findings remain release blockers. Save project settings before
scanning, inspect results, and run final project DRC after applying changes.

Install `TraceForge-0.12.9-KiCad10-PCM.zip` through KiCad's Plugin and Content
Manager > Install from file. Close all KiCad windows and reopen PCB Editor.

---

# TraceForge 0.12.8 - Stable KiCad 10 Windows Release

Use this release instead of 0.12.7. It includes the 0.12.7 differential-matching and signal-type improvements, and corrects a packaging checksum issue found during public download verification.

## Packaging correction
- ZIP source files are normalized to LF line endings on Windows and Linux.
- Bundled manufacturing exporter hashes are calculated against those exact bytes.
- The PCM builder rejects a package whose exporter manifest does not match its contents.
- Local and published packages are verified byte-for-byte before catalog submission.

## Signal tools included
- `[DIFF]` rows identify each differential member and its partner; `[SE]` identifies single-ended signals, including mixed RAM byte lanes.
- Selecting a row explains pair-length, P/N-skew or single-track tuning and its limits.
- Independent intra-pair and inter-pair checks, correct whole-chain series offsets, package-delay handling and pending-partner checks.
- Source PCB limits exclude package delay; additional pad contacts are not described as dangling stubs.

## Other included improvements since 0.12.1
Manufacturing project review and PCBWay/PCBPower exporters; feature-tab shortcuts; component rotation and the existing trace, via and BGA tools.

## Install
In KiCad Manager choose **Plugin and Content Manager > Install from file** and select `TraceForge-0.12.8-KiCad10-PCM.zip`. Close all KiCad windows and reopen PCB Editor. The Windows ZIP is the alternative standalone installation; use only one installation method.

## Validation and supported scope
Release lint, unit tests, native wxPython row checks, extracted-PCM differential-matching regressions, and bundled exporter manifest verification. The release publishes checksums for both archives.

This is a **stable release for Windows and KiCad 10**. Manufacturing export needs kicad-cli and a separate Python with openpyxl. Hardware timing budgets, manufacturing choices and final signoff require project review. Recompute DRC tuning windows after routing changes. A split series-net path may require nonzero local skew to achieve whole-chain matching.

The GitLab catalog update is submitted separately for KiCad maintainer review. Previous stable releases remain available.


# TraceForge 0.12.7 ? explicit signal types

Signals rows show `[DIFF] DQS_P (mate: DQS_N)` for differential members and
`[SE] DQ0` for single-ended signals. This applies to all configured interfaces,
including mixed RAM byte-lane groups. Selecting a row explains which native
KiCad tuning tool to use and shows the configured P/N and group/bus limits.
Default tools: 8 = differential pair length, 9 = differential pair skew,
7 = single-track length. Shortcut assignments may be customized in KiCad.
Series-net paths warn that local zero skew is not necessarily whole-chain zero.
Display decoration never becomes the internal key used for highlighting or
chain operations. Install using PCM and restart KiCad.

# TraceForge 0.12.6 ? differential matching correction

Intra-pair P/N skew and inter-pair delay spread are evaluated separately.
Pair timing is the average of its P and N whole-chain delays. Group spread
compares those centers; each P/N difference is checked against the pair limit.
With a 30 ps group limit and 0.7 ps pair limit, two internally matched pairs
20 ps apart now pass without tuning all eight signals into one 0.7 ps window.

Generated rules use per-chain lower/upper bounds, with the already routed
series-net delay subtracted from the tunable net target. Rule windows are a
snapshot: regenerate them after changing either member or its fixed segment.
The live monitor always re-evaluates actual pair/group skew.

Source PCB limits exclude package delay; whole-chain matching retains it.
A series resistor pad or additional-contact notice does not imply a dangling
stub. Pending differential partners are not certified matched.

Install the PCM ZIP through KiCad Plugin and Content Manager > Install from
file. Close all KiCad windows before reopening the updated plugin. Project
limits are retained; this release does not establish hardware timing budgets.

## Previous manufacturing testing build

# TraceForge 0.12.5 — Manufacturing workflow testing build

The Manufacturing tab opens on one saved board project by default. A sibling-board
bundle is available only when selected explicitly.
It uses labeled forms for PCBWay and PCBPower choices and shows an engineering
review of layers, schematic sheets, linked CAM and mechanical documents, ERC/DRC
findings, BOM/centroid parity, package contents, and release holds. Internal
configuration files remain hidden from the normal workflow.

The three-board Modular 256 SIM project has PCBPower profiles based on its
existing Rev B export settings and linked mechanical files. PCBWay order and
stackup choices remain unselected until confirmed. Generated packages are kept
separate from the existing Rev B review snapshot.

This is a **local testing build**. Manufacturing export needs `kicad-cli` and a
Python installation with `openpyxl`; the other TraceForge tabs continue to use
KiCad's bundled Python. A generated package may still be on HOLD for DRC findings
or missing quote decisions. No manufacturer order approval is implied.

Install `TraceForge-0.12.5-KiCad10-PCM.zip` with **Plugin and Content Manager >
Install from File**, then restart PCB Editor.

---

# TraceForge 0.12.4 — PCB Editor shortcuts

This local KiCad 10 testing build adds a **TraceForge: PCB Rotation** toolbar
button and direct entries under **Tools > External Plugins** for PCB Rotation,
Via Tools, BGA Fanout, Trace Tools, and Visualization. These actions open the
corresponding tab in the existing TraceForge window when one is running.

Live KiCad testing confirmed that the rotation menu action registers, and that
component rotation through 45 degrees is restored by KiCad Undo. Testing also
showed that the previous graphical polygon rotation could change the drawing
without KiCad Undo restoring it. This build limits TraceForge rotation to
components. To rotate a shape or zone 45 degrees, set **Preferences > PCB
Editor > Editing Options > Step for rotate commands** to 45 degrees, select
the object, and press **R**. KiCad's ActionPlugin API exposes toolbar and Tools
menu actions; it does not expose a supported PCB canvas context-menu hook.

Install `TraceForge-0.12.4-KiCad10-PCM.zip` through **Plugin and Content Manager >
Install from File**, then restart PCB Editor to load the new menu actions.

---

# TraceForge 0.12.3 — PCB Rotation fix

This testing build fixes the PCB Rotation error **"The open board changed before
rotation."** KiCad passes a fresh Python wrapper for the same board into its
undoable edit action; TraceForge now relies on the existing board-file check
instead of Python object identity. Use the 0.12.3 package when updating from
0.12.2. The rotation tab and controls are unchanged.

The fix was exercised in a disposable live KiCad PCB Editor: a selected
component rotated from 0 to 45 degrees, then KiCad Undo restored 0 degrees.
Graphical polygon and zone rotation also passed in-memory KiCad 10 checks.
Those checks did not verify KiCad Undo for drawings. Live testing for 0.12.4
found that the drawing edit was not restored by Undo.

Install `TraceForge-0.12.3-KiCad10-PCM.zip` with **Plugin and Content Manager >
Install from File**, then close every KiCad window and reopen PCB Editor.

---

# TraceForge 0.12.2 — PCB Rotation testing build

This Windows/KiCad 10 build adds a top-level **PCB Rotation** tab. Select one or
more components, graphical polygons, or copper zones in PCB Editor, enter `45`
or another signed angle, and click **Rotate selected items**. Positive angles
rotate counterclockwise; negative angles rotate clockwise. Each component
rotates around its anchor; polygons and zones rotate around their own centers.
The edit is one KiCad Undo step. Zone fills are updated after rotation.

Install `TraceForge-0.12.2-KiCad10-PCM.zip` with **Plugin and Content Manager >
Install from File**, then close every KiCad window and reopen PCB Editor.
Open TraceForge and select the **PCB Rotation** tab. The TraceForge title and About tab should say
`0.12.2`. Inspect connected traces and run DRC after rotating components.

This is a local testing package; the official 0.12.1 release remains available.

---

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
