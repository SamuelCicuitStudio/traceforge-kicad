# Trace cleanup

Whole-net length totals can include duplicate track objects, overlapping copper
and dangling branches. Endpoint-route lengths can differ because they follow a
single path. Removing redundant copper objects addresses duplicates without
pruning potentially intentional branches.

## Workflow

1. Open **Trace Cleanup** and click **Scan / Preview**. Optionally enter an exact
   net name; blank scans the board. Opening this tab also scans changed geometry.
2. Review the redundant and dangling track list and extra counted length. Select a row to
   highlight and zoom to that object in PCB Editor. Uncheck objects to keep.
3. Redundant tracks start checked. Dangling tracks start unchecked: review them
   before opting to remove them. Click **Remove checked tracks**. Choosing any
   dangling tracks asks for confirmation because they can be intentional stubs
   or unfinished routing. Changes use KiCad's native undoable action; the board
   is not saved.
4. Refresh Signals and run KiCad DRC. Use KiCad **Undo** to restore the removal.

## Removal criteria

- Exact duplicate straight tracks, including reversed endpoints.
- Straight tracks entirely covered by retained collinear tracks.
- Exact duplicate arcs with identical endpoints and midpoint.
- Identical net, copper layer, width and solder-mask properties are required.
- Integer geometry is compared exactly, without a snapping tolerance.
- Locked, grouped, fanout-managed and unassigned copper is never removed.
  Vias are excluded.

At least one retained set of copper covers every removed track. A removed object
is never used as the only justification for deleting another object. The copper
shape is preserved; this is not a reroute or an endpoint-matching operation.

Partial overlaps are counted for review and retained. Different-width copper,
near-parallel tracks and crossing routes are not automatically fused or removed.
Dangling-end detection uses KiCad's native connectivity test, rather than a
geometric guess about whether a trace touches a pad, via or zone. Removing the
end of a multi-segment dangling branch can expose another dangling segment;
scan again to review the next one. It does not recursively prune entire branches
or remove dangling vias. It does not alter the Signals length calculation.

Previews hold UUIDs and geometry fingerprints, not native object pointers.
Changing track geometry/properties after a preview requires rescanning before
removal. Dangling connectivity is checked again before removal, so tracks newly
connected to a pad/via/zone are not removed from a stale preview. Existing preview
IDs cannot be replaced with arbitrary board IDs.
Scans run on demand/change triggers, with no continuous board polling. Large
boards can be scanned one net at a time.
