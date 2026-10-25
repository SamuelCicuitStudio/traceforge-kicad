# Via Fencing along RF / antenna traces

The dedicated **Via Fencing** tab places ground vias beside a selected signal path.
It follows the trace, not a stitching rectangle or board perimeter. Perimeter fencing
remains a separate optional pattern in the Via Stitching tab.

## Workflow

1. Restart PCB Editor after updating the native helper.
2. Select connected straight track segments and/or arcs of the RF feed line.
   Select one net on one copper layer, without vias, footprints, branches or closed loops.
3. Open **Via Fencing** and click **Use selected trace**. The preview shows the source
   signal path in blue and marks its Start. Left/right is relative to that direction.
4. Choose a separate fence net, normally GND. The tool rejects using the signal net
   as the fence net. Select Both sides, Left side or Right side.
5. Set spacing along the trace, via diameter/drill and **Copper gap to signal trace**.
   The gap is measured from the widest selected signal copper edge to the via's
   annular-ring edge. The centerline offset includes half the widest track width,
   half the via diameter and the requested gap. Bends use joined offset paths.
6. Choose board/netclass/custom via sizes, board-edge setback and optional copper-fill
   setback. Fences require filled same-net copper contact on at least two layers
   (or every traversed layer when selected). Refill zones before previewing.
7. Preview. Green locations pass geometry checks; amber locations are rejected.
   Inspect the largest gap along either side, including end gaps. Missing ground
   copper can require a different offset, pour or setback.
8. Apply. Select, remove or edit/regenerate the fence from this tab's set list.
   Operations are undoable and preserve source signal traces. Save normally.

## Persistence and changes

Trace fences share `<board>.traceforge-stitching.json` ownership storage with ordinary
stitching, but their lists and Select/Remove all actions are separated by tab.
Keep the sidecar with the board. Source UUIDs, geometry and widths are stored with
each recipe. Preview reads the live path again; Apply rejects a changed preview.
If rerouting deletes recorded tracks, select the new source before regeneration.

## Limits

- Through vias; one open, connected, single-layer path.
- Arcs are sampled to a small tolerance; native collision checks use actual copper
  shapes. Very sharp reversals are rejected.
- The widest selected track determines offset. Narrower segments can therefore
  have a larger copper-to-via gap than requested.
- Obstacles, corner spacing, edge/cutout clearance and absent ground copper can leave
  gaps. A partial result does not imply a continuous RF fence.
- Custom-rule and full RF validation are incomplete. Choose pitch and gap for your
  stackup/RF design; placement does not verify antenna impedance, shielding performance
  or antenna keepouts. Run KiCad DRC after placement.
- Existing candidate/time limits and GUI-thread refill limitations apply.

Synthetic checks cover lines/arcs, left/right/both, invalid path topology, separate
signal/fence nets, stale source widths, native connectivity, saved ownership and
removal preserving the original RF path.
