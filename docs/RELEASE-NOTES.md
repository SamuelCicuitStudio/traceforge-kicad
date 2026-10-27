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
