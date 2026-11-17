# Layout Clone

Reuse repeated circuit layout without hierarchical sheets. Open **Layout Clone** in TraceForge.

1. Choose the clone mode and graphics option, then select source footprints in PCB Editor. Include the tracks, arcs, vias, zones and
   board graphics you want to reuse, then click **Record selected layout**.
2. Select corresponding target footprints and click **Apply to selected group**.
   Apply captures the current target selection, matches it automatically and applies.
   No table-row selection is required. **Preview target matches** and match editing
   are optional. Electrically interchangeable duplicate parts match automatically.
   Switching from placement-only to routing later requires recording the source again.

Nested PCB groups are expanded. Capture uses explicit selection: it does not follow shared
power/ground nets across the board or guess a rectangular routing boundary. If a selection
filter excluded tracks or graphics, enable those items and record the source again. The
recorded item counts appear in the status box. Templates can be saved and loaded as JSON.
Older placement-only templates remain usable; record again to include routing.

## Clone modes

| Mode | Components | Copper |
|---|---|---|
| Placement only (default) | Copy source positions/rotations relative to target anchor | No copper copied |
| Routing only | Preserve target positions, rotations and placement locks | Copy selected tracks, arcs, vias and copper zones with target nets |
| Placement + routing | Copy source arrangement relative to target anchor | Copy selected tracks, arcs, vias and copper zones with target nets |

**Also copy selected graphics / keepouts** adds explicitly selected board text, shapes,
text boxes, tables, dimensions, targets and rule-area zones. It also copies native footprint
reference/value field positions, angles, layers, sizes, stroke and justification. Target
reference/value strings and visibility stay intact; individually locked text blocks that
operation. Footprint-owned decorative artwork is retained from each target footprint.

Transforms preserve the target anchor's position and orientation on the same copper side. Source offsets, footprint angles, routing and optional graphics rotate together around that anchor. Routing-only requires the targets to already match this rotated arrangement; it never moves components. Use placement + routing if alignment is needed. Copper-side mirroring and automatic repacking are not provided.

## Component and net mapping

Correspondence uses numbered pad geometry, values, normalized net roles and internal
connectivity. Electrically interchangeable duplicate parts match automatically. Unresolved electrical ambiguity can be corrected with the optional **Assign selected row** control. Choose a different
anchor if the automatic highest-pin-count component is unsuitable.

Different values and partial placement groups require explicit options. Routing requires
complete groups. Every copied copper net must resolve through matched numbered pads to
exactly one target net, and distinct source nets must not merge. An unmapped route, including
a selected route on a net absent from the matched pads, blocks apply. Via drills, diameters,
layer pairs, arc geometry, track widths and zone settings use KiCad-native serialization.
New assets receive new UUIDs. Source copper and component identities remain intact.

Board outlines, margin lines, reference images, unsupported item types and unnetted copper
graphics are rejected rather than copied as circuit assets. Use netted tracks or zones for
copper. Items using disabled target layers are rejected. Source PCB groups are flattened;
this does not create a new target PCB group.

## Preview, apply and remaining checks

Apply rechecks the target board, placement, pads, values, locks and nets against the analyzed
snapshot. With graphics enabled it also rechecks target field styles. Existing track/via
copper touching target pads blocks the operation: the tool never deletes or replaces target
routing. Identical existing asset copies are rejected. The touching-copper guard uses
conservative same-net bounding boxes and can require manual adjustment of a nearby route.

Copied tracks/arcs/vias are checked with native copper shapes against foreign-net pads,
existing tracks and each other. Zones are copied unfilled and refilled after the operation.
The native edit transaction supplies one Undo step and rolls back a failed edit. The board
is not saved automatically. Locked targets block placement changes; routing-only may leave
locked target components stationary.

Run full KiCad DRC afterward for custom rules, zone clearances/fill, board edges, keepouts,
isolation, assembly and other layout constraints. Cloning does not qualify impedance,
length matching or manufacturing clearance.

## Verification

`tests/test_layout_clone.py` covers matching, ambiguity, topology, partial selection,
values, locks, routing modes, placement alignment and net correspondence. Run
`tools/verify_layout_clone_native.py` with KiCad's bundled Python to check native placement,
tracks, arcs, vias, zones and graphics, target net remapping, duplicate rejection, missing
net rejection and routing-only placement preservation. Native checks use in-memory boards;
the headless transaction substitute does not verify live-editor Undo/Redo. Confirm Undo/Redo
on a disposable board when installing a new KiCad build.


The target anchor retains its position and orientation. Source offsets, footprint
angles, routing and optional graphics rotate together around that anchor. Choose
an IC as the anchor when a passive component's 180-degree orientation is ambiguous.
For an unorganized target group, use placement and routing together; routing-only
requires the matching placement first. Clearance checks use prospective pad
positions before changing the live board. A rejected collision reports the item,
net and position and leaves the board unchanged. Full KiCad DRC remains required.


## Result preview (0.16.4)

A drawing beside the correspondence table shows the recorded source, then the
proposed target result when **Preview selected target** is clicked. Apply can
still run directly; previewing does not add a confirmation or row-selection step.
The preview updates with mode, anchor, matching, layer and before/after changes.
Placement-only omits copper; routing-only keeps the actual target footprints;
combined mode transforms both. Copied tracks, arcs, vias and zone outlines use
the same rigid transform as Apply. Optional recorded graphics are also drawn.

Top copper is red, bottom is blue, vias are gold and previous footprint locations
are grey. Use the mouse wheel to zoom, drag to pan, and **Fit** or double-click to
fit the group. The layer choice filters routing; component land patterns stay
visible for context. Footprint body bounds, custom pads, text and zone presentation
are simplified; this is a selected-group preview, not a full-board DRC renderer.
Existing neighboring copper and filled-zone results are not shown. Apply still
runs its copper checks, and the finished board still needs KiCad DRC.

Preview draws from copied metadata and temporary recorded assets. It never moves
or adds anything on the live board, never changes selection, never refills zones
and never saves the PCB. Old templates with native assets can regenerate their
preview without recapturing the source. A blocked mapping is visibly marked;
previewing it does not bypass routing-only alignment or electrical checks.
