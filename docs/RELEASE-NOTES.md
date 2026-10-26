# TraceForge 0.11.6 — BGA selection repair

This update restores the board-boundary helper required by the native BGA
fanout module. In 0.11.5, **Analyze PCB selection** failed before reading the
selected footprint with `cannot import name 'fits' from stitching_native`.
Version 0.11.6 restores that helper and checks whether proposed vias and
tracks remain inside the board outline and clear of its edges and cutouts.

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
