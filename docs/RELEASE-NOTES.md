# TraceForge 0.10.1

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
