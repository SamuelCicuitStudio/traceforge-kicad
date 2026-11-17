# Auto Text

Arrange component references for a first cleanup pass. Open **Auto Text** in TraceForge.

1. Select footprints in PCB Editor, or choose **Entire PCB** in Scope.
2. Choose **Destination layer**: keep current layers, F.SilkS/B.SilkS, F.Fab/B.Fab,
   Dwgs.User, Cmts.User, or User.1–User.9.
3. Click **Preview placement**, review the rows, then **Apply safe placements**.

References are the default. **Include reference text copies** also discovers visible
`${REFERENCE}` graphic text inside footprints (common on F.Fab). These appear as
`Reference copy` rows; their dynamic expressions remain intact when moved. Arbitrary
footprint legends and pin-1/polarity text remain obstacles. Disable this option to arrange
only the native reference fields. Selecting a reference text copy selects its owning
footprint for Auto Text purposes.

**Also arrange visible values** is optional and off by default.
**Show hidden references** can make hidden reference fields visible when a clear destination
is found; it never reveals hidden values. Copper, mask, paste and board-outline layers are
not destinations. Layer names use KiCad's conventional identifiers, including legacy
Dwgs.User/Cmts.User identifiers for the user drawing/comment layers.

## Consistent, readable labels

The default **Uniform references** style uses 1.0 mm text height, 0.15 mm stroke and
0.25 mm placement grid. These are adjustable TraceForge defaults, not dimensions specified
by the Altium article. Explicit silkscreen height, stroke and clearance requests are raised
to the PCB's configured minima. **Preserve existing typography** keeps existing height and
stroke; zero in either control preserves that property. Review preserved typography against
your manufacturer's limits. Custom settings are available in millimetres.

**Align repeated rows / columns** detects runs of at least three small components with the
same footprint. It places their references on a shared baseline in physical component order,
trying either side of the group. A whole bank must fit without collisions; otherwise labels
fall back to individual placement. Bank alignment takes precedence over keeping existing
positions. Disable it to retain individual placement throughout.

New placements use readable 0?/90? angles, with horizontal text preferred. Grid snapping
keeps positions consistent. **Keep already-clear nearby labels** reduces individual-label
churn. Locked footprints are skipped unless **Text on locked footprints** is enabled.
That option edits text only: placement and footprint locks stay unchanged. Individually
locked text is always skipped. An empty preview explains hidden/locked-field counts.

The [Altium silkscreen guide](https://resources.altium.com/p/your-guide-pcb-silkscreen)
explains the assembly and debugging value of clear designators and arranging dense groups
in the same order as their components. Existing pin-1, polarity and connector markings remain
protected obstacles. Auto Text arranges fields; it does not generate certification marks,
logos or connector pinouts.

## Preview and apply

Preview reports each field as `move`, `keep` or `unplaced`, with its destination layer,
position, rotation, height and stroke. Preview also reports aligned-bank counts and settings warnings. It never edits or saves the PCB. Applying places only the `move`
rows. Unresolved crowded labels retain their original layer, visibility and position for
manual cleanup. Changing settings invalidates the preview.

Placement uses conservative bounding boxes for bodies, pads including solder-mask expansion, holes, vias, relevant graphics
and visible fields. Labels on different drawing layers do not collide with each other;
component/pad bodies and holes are considered where applicable. Original visible label
positions are reserved so a label that cannot be moved is not overwritten by another label.
These reservations can leave more labels unresolved on dense boards.

A valid Edge.Cuts outline bounds the search. Boards without a usable outline can still be
previewed and show an outline warning. Bounding-box and outline checks are approximations;
run KiCad DRC and visually inspect the result before manufacture.

Apply re-scans the board and rejects stale or already-used previews. The existing native
board-edit transaction provides one Undo step and rollback on failure. Only reference/value field and enabled reference-copy positions,
text angle, requested layer/mirroring, optional reference visibility, optional text size and stroke
are edited. Newly arranged fields use centered justification to match their planned boxes.
Footprint placement, pads, tracks, vias, nets, reference strings and value strings remain intact.
The board is not saved automatically.

## Verification

`tests/test_auto_text.py` covers collision handling, deterministic placement, preserving clear
labels, layer separation, crowded labels, search limits, aligned banks, grid snapping,
upright rotation, stroke bounds and settings validation.
Run `tools/verify_auto_text_native.py` with KiCad's bundled Python for in-memory checks of
layer changes, visibility, mirroring, preview/stale-token rejection and component/net preservation.
The headless check substitutes the transaction wrapper; confirm live-editor Undo/Redo on a
disposable board when installing a new KiCad build.
