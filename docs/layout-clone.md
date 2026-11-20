# Layout Clone

Reuse repeated circuit layout from selected parts or repeated hierarchical sheet instances. Open **Layout Clone** in TraceForge.

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
existing tracks and each other. Zones are copied unfilled. Press B in KiCad when ready to refill.
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

## Repeated hierarchical sheet instances

Choose **Scope: Repeated sheet instance** before recording. Select one footprint
in the source instance and click Record; TraceForge expands it to every footprint
in that sheet and its subsheets. Select one footprint in the destination instance,
then Preview or Apply. **Parent sheet levels** (0 = containing sheet, 1 = its parent)
lets you select a footprint inside a nested sheet and clone the larger repeated block.
Use the same nesting level for source and target; the recorded scope is used for both.
Root-project expansion is refused. Expansion is limited to 500 footprints.

Matching uses symbol UUID paths relative to each instance root, including nested
sheet UUIDs. Table matches show **Hierarchy**. This disambiguates identical passives
without guessing from reference numbers or position. Different symbol sets, pad
geometry, internal connectivity, stale sheet membership and conflicting manual
assignments are blocked. Selected-items mode remains available for circuits without
hierarchy and also uses matching UUID paths when available.

All existing clone modes work: placement, routing, or both, with anchor rotation,
preview, net remapping and native undo. For repeated-sheet recording, routing modes
automatically capture tracks/arcs/vias on nets whose footprint pads all belong to
that instance. **Shared power and interface nets require explicit routing selection**;
TraceForge does not capture routing from other circuits sharing those nets. Graphics
and keepouts still require explicit selection and the graphics checkbox. Select them
alongside the source footprint before Record. A hierarchy change never bypasses the
existing target-copper, clearance, locked-component or routing-alignment checks.

## FPGA and connectors across different sheets

Use **Selected items** for an FPGA and its connected headers when they span
separate schematic branches. Select the same component roles in the target group.
Functional connector labels such as SIM05 / IDC1 and SIM01 / IDC1 match as the same
role; IDC1 and IDC2 remain distinct. Component values and labels are never rewritten.
Placement-only cloning can retain differing target pin connectivity and shows a
warning. Routing cloning still requires matching connectivity and safe net remapping.
Matching caches physical geometry while evaluating network roles for large BGAs.

## Clearance override and copper artwork

**Check copper clearance** is enabled by default. Uncheck it to bypass the clone's
native copper-clearance preflight for Apply. This does not disable KiCad DRC or
change project rules; it lets you copy a layout and resolve its violations afterward.
Net mapping, matching, stale snapshots, target routing/movement guards, locked parts,
duplicate detection and board-layer validation still apply. The preview status shows
when the clearance check is disabled.

With **Also copy selected graphics / keepouts**, selected top-level F.Cu/B.Cu artwork
copies with its shape/layer and transform. Unnetted copper artwork remains unnetted;
TraceForge does not guess a power or ground net for it. Tracks, vias and netted zones
still remap through matched component pads. Footprint-owned graphics remain part of
the matched footprint rather than separate board graphics.

Validated on the supplied FPGA PSU selection: 30 footprints, 135 tracks, 43 vias and
33 copper graphics copied on a disposable board. The default clearance call was
confirmed blocking; the unchecked option bypassed that call. No user PCB was written.

## Routing clone activity

Record, target selection reads and Apply native requests run off the TraceForge wx thread. The activity indicator, phase label and elapsed time stay visible while KiCad processes the request. KiCad board edits run on its editor thread to support Undo. Refill zones manually in KiCad when ready.

## Clone all replicas to grid

Record a complete repeated sheet using Repeated sheet instance scope. Set Columns,
X pitch mm and Y pitch mm, then click **Clone all replicas to grid (Undoable)**.
The source stays at cell zero; other complete instances with the same relative symbol
UUID paths and sheet files are ordered by reference and placed row by row. Pitch is
anchor-to-anchor, not clearance; allow enough room for the source circuit's full size.
The action supports placement, routing and both, plus the graphics/clearance options.
Routing modes realign the target placement before copying copper. All replicas are
applied in one undoable batch edit. Up to 64 total
instances are supported.

Recloning automatically replaces unlocked tracks/vias on nets whose footprint pads all belong to the matched target group. Placement-only removes that local routing and moves components; routing modes also align source placement and copy the source copper. Shared/interface-net copper is preserved. Locked routing blocks the operation. Removal, placement and replacement share one native undo transaction. TraceForge never saves the live PCB under a temporary name or changes its schematic association during this operation.

Clone all occurrences uses the recorded source, not target selection. Keep the source components/routing/artwork/zones selected after Record and press Clone all occurrences. Matching recorded subsets of repeated sheets is supported; other components remain untouched. Existing target local internal-net routing is replaced automatically. The source snapshot is checked for stale edits before any replicas change.
