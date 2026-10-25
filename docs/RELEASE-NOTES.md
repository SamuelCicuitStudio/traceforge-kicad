# TraceForge 0.10.0

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
