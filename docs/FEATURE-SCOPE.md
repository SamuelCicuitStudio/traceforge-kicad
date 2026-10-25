# Feature scope

This document defines the intended behavior of the KiCad PCB Automation Toolkit. It
prevents similarly named PCB features from being implemented with the wrong model.

## TraceForge feature tabs

The agreed layout is one window with **Signals / xSignals** as the first tab and
**Via Stitching** as the second. Keep net/chain analysis, timing, highlighting,
chain editing, DRC targets and exports together in Signals. The stitching tab owns
regions, via settings, preview and management of generated stitching sets. Tab changes
preserve state and do not trigger board refreshes. See the implementation sequence,
native capability proof points and acceptance checks in
[VIA-STITCHING-PLAN.md](VIA-STITCHING-PLAN.md). Version 0.7 implements both tabs and
initial stitching; that document identifies differences from the full intended scope.

## Signal Path Analyzer

The analyzer treats a signal as an electrical path, not merely a KiCad net name. It
will combine tracks, arcs, electrical via height, per-layer propagation delay,
pad-to-die delay, and explicitly approved bridges through series passives.

Initial output is read-only CSV reporting. Later releases will provide path selection,
group skew comparisons, PCB highlighting, and reviewed custom-rule generation.

## Zone Via Stitching

This feature is not a generic via-array command.

### User workflow

1. Select a filled copper zone, draw a rectangle/closed polygon, or choose whole-board mode.
2. In zone mode, inherit the zone net by default. Allow an explicit net only when it
   is electrically compatible with the selected copper.
3. Inherit via diameter/drill from the active board preset or chosen net's netclass,
   or use custom values. Set horizontal/vertical pitch, grid offsets, zone-boundary
   setback and board-edge setback.
4. Choose whether a candidate must touch same-net copper on at least two traversed
   layers or on every traversed copper layer.
5. Preview accepted and rejected candidates, with a rejection count by reason.
6. Confirm all vias as one undoable KiCad commit, then refill affected zones.
7. Keep generated vias in identifiable, persistent stitching sets. Select, remove
   or regenerate one set or all managed sets while preserving ordinary routing vias.
8. Choose symmetric aligned rows or staggered alternate rows; preserve grid origin
   and row parity when regenerating a region.

### Placement rules

- Clip candidates to the selected zone's actual filled copper, not only its outline.
- Reject holes or annular rings that violate board rules or explicit setback values.
- Reject collisions with pads, tracks, vias, keepouts, holes, courtyards when enabled,
  and copper belonging to a different net.
- Do not place a via connected on only one layer.
- Preserve a stable grid when regenerating the same stitching region.
- Support rectangular filling first; perimeter/fence placement can follow.

This matches EasyEDA Pro's useful workflow: choose the net and via geometry, set row
and column spacing, draw a rectangle or select a copper region, and automatically
avoid placements that would cause DRC errors.

## Interactive Parallel Multi-Routing

This feature is interactive bus routing, not automatic routing and not differential-
pair routing.

### User workflow

1. Select an ordered set of starting pads, vias, ratsnest connections, or existing
   track ends.
2. Confirm or reverse the lane order.
3. Set track width, edge-to-edge spacing or pitch, active layer, corner style, and
   routing conflict mode.
4. Move the cursor to preview the complete bundle as parallel tracks.
5. Click to add a shared inflection point. Each lane receives geometry offset from a
   common guide while maintaining ordering and spacing.
6. Finish at the corresponding ordered destination pads or track ends.
7. Commit the bundle as one undoable operation.

### Routing rules

- Preserve lane order unless the user explicitly performs a controlled swap.
- Support at least 45-degree routing first; arcs and other modes can follow.
- Maintain per-net width and clearance constraints, using the most restrictive legal
  bundle spacing when rules differ.
- Detect neck-down and fan-out regions rather than silently collapsing spacing.
- Provide block mode first. Push and walk-around behavior require an interactive
  collision solver and will be introduced only after deterministic block routing.
- Layer changes must create one correctly netted via per lane and maintain sufficient
  via-to-via and via-to-copper clearance.
- Never treat a bus as a differential pair or automatically length-match it unless a
  separate timing rule requests matching.

EasyEDA Pro describes this behavior as multi-way or bus routing: more than 20 wires
can be laid simultaneously, with push and arc routing available in that mode. The
toolkit will reproduce the interaction model while obeying KiCad's native rules and
undo system.

## References

- [EasyEDA Pro: Multiple Routing](https://prodocs.easyeda.com/en/release-note/v2.2.x/)
- [EasyEDA Pro: Suture Via](https://prodocs.easyeda.com/en/pcb/place-suture-vias/index.html)
- [EasyEDA Pro: Copper Region](https://prodocs.easyeda.com/en/pcb/place-copper-region/index.html)
- [KiCad IPC API for add-on developers](https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/)
