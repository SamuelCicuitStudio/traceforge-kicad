# Trace cleanup

Whole-net length totals can include duplicate track objects, overlapping copper
and dangling branches. Endpoint-route lengths can differ because they follow a
single path. Removing redundant copper objects addresses duplicates without
pruning potentially intentional branches.

## Workflow

1. Open **Trace Cleanup** and click **Scan / Preview**. Optionally enter an exact
   net name; blank scans the board. Opening this tab also scans changed geometry.
   Use **Show layer** to inspect F.Cu, inner layers or B.Cu independently. The
   summary gives finding counts on every detected copper layer.
2. Review duplicate, fuse and dangling findings and the excess counted length. Select a row to
   highlight and zoom to that object in PCB Editor. Uncheck objects to keep.
3. Redundant tracks and compatible fusions start checked. Dangling tracks start unchecked: review them
   before opting to remove them. Click **Apply checked cleanup**. Choosing any
   dangling tracks asks for confirmation because they can be intentional stubs
   or unfinished routing. Changes use KiCad's native undoable action; the board
   is not saved. Only checked rows visible in the selected layer are applied.
4. Refresh Signals and run KiCad DRC. Use KiCad **Undo** to restore the removal.

## Removal criteria

- Exact duplicate straight tracks, including reversed endpoints.
- Straight tracks entirely covered by retained collinear tracks.
- Partially overlapping straight tracks can be fused into one continuous segment
  covering the same span, with the same net, layer, width and mask settings.
  Each layer has a separate fuse group. Original objects are replaced through
  KiCad Undo; pad-to-pad continuity was checked on a synthetic route.
- Exact duplicate arcs with identical endpoints and midpoint.
- Identical net, copper layer, width and solder-mask properties are required.
- Integer geometry is compared exactly, without a snapping tolerance.
- Locked, grouped, fanout-managed and unassigned copper is never removed.
  Vias are excluded.

At least one retained set of copper covers every removed track. A removed object
is never used as the only justification for deleting another object. The copper
shape is preserved; this is not a reroute or an endpoint-matching operation.

Partial overlaps involving protected tracks are counted for review and retained.
Different-width copper,
near-parallel tracks and crossing routes are not automatically fused or removed.
Dangling-end detection uses KiCad's native connectivity test, rather than a
geometric guess about whether a trace touches a pad, via or zone. Removing the
end of a multi-segment dangling branch can expose another dangling segment;
scan again to review the next one. It does not recursively prune entire branches
or remove dangling vias. It does not alter the Signals length calculation.

Previews hold UUIDs and geometry fingerprints, not native object pointers.
Changing track geometry/properties after a preview requires rescanning before
removal or fusion. Dangling connectivity is checked again before removal, so tracks newly
connected to a pad/via/zone are not removed from a stale preview. Existing preview
IDs cannot be replaced with arbitrary board IDs.
Scans run on demand/change triggers, with no continuous board polling. Large
boards can be scanned one net at a time.
