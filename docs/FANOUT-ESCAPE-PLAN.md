# TraceForge fanout: focused next step

Status: focused first implementation is in the BGA Fanout tab. Live editor Apply,
Undo/Redo and managed removal passed on a disposable 4 by 4 board with 16 routes.
Fabricator-specific rules and more difficult blocked-pad layouts remain to validate.

## Goal

Make the existing BGA Fanout tab useful for deciding **whether a selected BGA
can be escaped with the current board rules, and which pads actually have a
routable way out**. Keep TraceForge's live PCB preview, native Undo, and managed
removal. This is a targeted extension of the current pad-to-via tool, not a
general autorouter.

## The two additions

### 1. Fit guidance before placement

After Analyze, show whether the selected track, clearance, via and drill
dimensions can fit the BGA's measured pitch and the board's minimum rules.
**Suggest settings** should rank legal board presets and explain why a
candidate fails (track channel too narrow, via does not fit the gap, drill or
annular ring below the allowed minimum, or obstacle on the selected layer).
It must never silently shrink below board or fabrication limits.

### 2. Escape-to-edge preview

Add an **Auto escape** choice beside the current Dogbone and Via-in-pad
breakouts. For selected single-ended signals on a regular SMD BGA, it proposes
a short connected route from each pad to a clear point just outside the BGA pad
field. It may use one legal through via and user-selected copper layers. It
must keep existing copper fixed and use a bounded search so PCB Editor remains
responsive.

Preview labels every pad **escaped**, **breakout only**, **already routed**,
**skipped**, or **blocked**, with the blocking reason. A pad is escaped only
when its same-net copper reaches the recorded edge endpoint; placing a via
alone does not qualify. Apply rechecks the live board and creates reviewed
routes in one undoable operation. Managed removal removes only unchanged
TraceForge-owned copper.

## Why these two

- [KiCadRoutingTools](https://github.com/drandyhaas/KiCadRoutingTools/blob/main/py_router/bga_fanout/README.md)
  shows that width/clearance feasibility and routes to the package boundary
  matter more than a count of vias placed. Its channel, under-pad and
  multilayer router are broader than this proposal.
- [KiCad Fanout Tool](https://github.com/thanhduongvs/kicad-fanout-tool)
  shows the value of understandable placement controls. TraceForge already
  has editable dimensions, preview and native Undo, so copying its full set of
  fan/staggered/linear styles has little immediate benefit.
- [WayriCAD Fanout Generator](https://github.com/wayri/WayriCAD/blob/develop/fanout_generator_plugin/ReadMe.md)
  shows the value of explaining accepted and rejected candidates on the
  actual board. Its guide also distinguishes fanout seeds from finished routes.

We are learning from these designs, not copying their source. Review license
and attribution before any code reuse.

## Implementation boundary

Use `fanout_native.py` to collect a live, read-only board snapshot and to
revalidate/commit. Put the bounded route search in a new pure planner module;
extend `fanout_ui.py` for fit explanations and per-pad preview. Reuse the
existing UUID journal for ownership of the added route segments. Compute
candidate geometry without modifying the board; Apply alone mutates it.

The first implementation supports regular BGA grids, through vias and
single-ended nets. It does not attempt QFN/QFP fanout, dense under-pad routing,
differential-pair coupling, automatic rip-up, component movement, microvia
stacks, destination routing, or length/impedance matching. Those can be
considered later based on actual blocked-pad results, rather than becoming
release requirements now. In particular, HDI microvias require explicit
stackup and fabricator rules before implementation.

## Acceptance test

On front/back, rotated, sparse and dense synthetic BGAs plus a disposable
copy of a real board:

1. Show a feasibility explanation before placement, including infeasible
   dimensions and board-rule floors.
2. Confirm each **escaped** pad has continuous same-net copper to its
   reported edge endpoint; never count a stub-only pad as escaped.
3. Report every blocked pad and preserve all pre-existing copper.
4. Run KiCad DRC before and after Apply; accepted routes add no DRC errors.
5. Verify native Undo and managed removal, including a route manually edited
   after Apply, which removal must preserve.

The dense fixture may have blocked pads. Accurate reporting is a valid result;
claiming a complete escape when balls remain trapped is not.
