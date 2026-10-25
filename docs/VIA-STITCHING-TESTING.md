# Via Stitching 0.7 testing

Restart PCB Editor once to load the updated native helper and its internal undoable
stitching action. Open TraceForge, choose **Via Stitching**, and click **Refresh board**.
The first tab retains all existing Signals / xSignals functionality.

1. Choose a net with filled copper on two or more layers. GND is usually suitable.
2. Check that Active board preset and Netclass show the intended diameter/drill.
   Try a listed preset and Custom; all dimensions and center-to-center spacing are mm.
3. Compare Symmetric and Staggered previews. Alternate staggered rows shift by half
   the horizontal pitch, with row parity anchored to the board coordinate grid.
4. Draw a rectangle on the tab's board overview by dragging. For a polygon, click
   vertices and press Enter/right-click to finish. Esc cancels. This version draws
   in the overview, not directly on the PCB canvas. Whole board and Use PCB selection
   (one copper zone or non-copper rectangle/polygon) are also available.
5. Preview without applying. Check green accepted locations, amber skipped locations,
   counts and rejection reasons. PCB vias must remain unchanged during preview.
6. Apply a small region first. Check the live PCB and KiCad DRC after zone refill.
   The planner performs conservative geometry checks; custom DRC rules and optional
   courtyard exclusion are not completely implemented.
7. Choose the set and click Select set. Verify the actual native selection includes
   only that set's vias. Select all stitching addresses all recorded live sets.
8. Edit/regenerate with different spacing or pattern. Check for duplicates and verify
   one Undo and Redo restores the exact previous/new set. Remove a set, Undo it, and
   confirm ordinary routing vias remain intact.
9. Save/reopen the PCB and Refresh board. Keep the adjacent
   `<board>.traceforge-stitching.json` file: it stores UUID ownership and recipes.
   Missing metadata prevents managing those vias as sets. Moved/resized/renetted/locked
   managed vias are preserved by automatic removal/regeneration.
10. Switch tabs repeatedly. Neither switching nor idle time should request board data;
    F5 updates only the active tab. Signals scrolling, expansion and snapshot remain.

Native preview/apply can briefly occupy KiCad's GUI thread. The initial version limits
grids to 5,000 candidates and bounds preview computation time. Use a smaller region or
larger spacing when a limit is reported. Finish routing/tuning and close modal editor
dialogs before starting stitching operations. Failed mutations are not automatically
replayed; refresh and inspect the live state before another attempt.

Validation performed on disposable synthetic boards: apply Undo/Redo; regeneration
Undo/Redo with exact UUID membership; removal Undo; ordinary-via preservation; real
multi-via selection; save/reload ownership; symmetric/staggered grids; cutouts/keepouts;
read-only previews; stale preview rejection and single-use tokens. The real management
board was used only for read-only preview and existing signal-chain checks. A DRC
comparison across synthetic patterns found the same two isolated-copper warnings,
zero unconnected items and no clearance violations. This is not a complete DRC proof.

Development checks: 71 unit tests and Ruff pass. With KiCad's bundled Python, run
`tools/check_stitching.py` for geometry/serialization checks and
`tools/check_native_bridge.py BOARD.kicad_pcb` for existing signal checks. The former
creates temporary synthetic boards; the latter never saves the source PCB.

Logs: `%APPDATA%/TraceForge/traceforge.log`. Include the failed action and whether the
failure happened during Preview, Apply, zone refill, Select or Remove.
