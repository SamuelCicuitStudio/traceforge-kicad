# BGA Fanout: pad-to-via breakout

TraceForge 0.8 adds an independent, native pcbnew BGA breakout tool. It creates short
pad-to-via connections on the selected footprint. It does not route signals from
those vias to other components or guarantee complete escape beyond the package.

## Workflow

1. Restart PCB Editor after updating TraceForge. Select one BGA footprint or pads
   belonging to it, open the **BGA Fanout** tab and click **Analyze PCB selection**.
2. Review detected X/Y pitch, rows/columns, pad count and footprint side. The initial
   version supports regular rectangular SMD grids, including missing balls, rotations
   and back-side placements. Irregular/staggered packages require a different strategy.
3. Choose **Dogbone** for a short stub to a via in an adjacent inter-ball gap. Zero
   X/Y offset means half the respective pitch. Custom positive offsets are supported.
   The planner tries four gap directions, preferring outward sites and processing
   inner pads first. Blocked locations are reported rather than silently forced.
4. Choose active board preset, per-net netclass, a named board preset or custom via
   diameter/drill. Configure track width, clearance and board-edge setback in mm.
   Respect netclass widths is enabled by default. Disabling it uses the requested
   width subject to the board minimum; check custom rules with KiCad DRC.
5. Filter nets and pad numbers using comma-separated wildcard patterns. For example,
   include `*DATA*,*CLK*`, exclude `GND,*VCC*`, or limit pads to `A*,B*`. Patterns are
   case-sensitive. Unconnected pads and existing routed breakouts are skipped.
6. Click **Preview fanout**. Inspect every accepted, blocked and skipped row. Green
   lines/circles are proposed stubs/vias. The board is unchanged by preview.
7. **Apply accepted breakouts** revalidates the live footprint/board and creates the
   accepted vias/tracks as one undoable native operation. Partial fanout requires an
   explicit confirmation. Refill/connectivity checks follow. Save the PCB normally.

**Suggest settings** evaluates a bounded selection of board presets and dimensions
at or above the board's through-via manufacturing limits. It considers pitch, pad
size, available diagonal gaps and track width, then runs the actual geometry planner
on candidate settings. Compare accepted/blocked counts and choose a candidate to load.
Nothing is placed and board rules are not changed. Preview again before Apply.
This is a suggestion search, not a proof of an optimal or fully escaped BGA design.

**Remove generated fanout** removes recorded, unchanged and unlocked tracks/vias for
the analyzed footprint as one undoable action. It preserves ordinary/untracked routing
and manually altered items. Keep `<board>.traceforge-fanout.json` alongside the PCB:
it records exact UUID ownership and recipes, including history for Undo/Redo recovery.
Missing metadata prevents managed removal; the tool never infers ownership from
nearby copper or matching sizes. Remove a generated fanout before evaluating a replacement.

**Via-in-pad** is a separate explicit mode. Confirm fabrication support before using
it. TraceForge does not automatically escalate to via-in-pad, reduce dimensions below
manufacturing limits or change project design rules to force a result.

## Checks and limits

- Through vias span F.Cu to B.Cu and must clear relevant copper and holes on all
  traversed layers. The short track is on the footprint's own outer copper layer.
- Existing pad/track/via shapes, via/track keepouts, other-net filled zones, board
  boundaries/cutouts and already reserved fanout geometry constrain placement.
- The pad's own copper is allowed at the stub start. Dogbone vias cannot overlap
  that source pad; via-in-pad mode must be explicitly requested to allow it.
- Board minimum diameter, drill, annular ring and track width are enforced.
  Clearance uses at least the board minimum and involved netclass values. Full
  custom-rule evaluation, mask/fabrication constraints, teardrops and courtyard
  filtering are not implemented; review the result with KiCad DRC and your fabricator.
- No blind/buried/microvias, differential-pair coupling, length matching, automatic
  layer assignment or channel routing to the package edge in this version.
- Blocked pads remain blocked in the result; a partial result is not a complete
  BGA escape. Unfinished breakout vias can be reported as dangling by DRC until
  subsequent routing connects them onward.
- The initial limits are 1,600 pads and a bounded preview time. GUI-thread native
  work/refill can briefly occupy the editor. There is no polling or automatic retry.
- Atomic replacement/regeneration is not implemented. Use Remove generated fanout,
  then Suggest/Preview/Apply; both mutations can be undone. The copper remains standard
  KiCad tracks/vias if ownership metadata is lost, but managed removal needs that file.

## Completeness and HDI

TraceForge is not currently a more complete BGA router than KiCadRoutingTools.
The reviewed upstream documentation describes channel escape, under-pad routing,
multiple-layer assignment and differential-pair escape. Our implementation focuses
on live-board, previewed pad-to-via placement, editable settings, managed removal and
native undo. Its current limitations should not be confused with a complete escape router.

| Capability | TraceForge 0.8 | Reviewed upstream documentation |
| --- | --- | --- |
| Dogbone / via-in-pad placement | Implemented with through vias | Documented |
| Full channel/under-pad escape to package boundary | Not implemented | Documented |
| Escape-layer allocation and coupled differential pairs | Not implemented | Documented |
| Live-board native preview/apply and managed removal | Implemented in TraceForge | File-oriented workflow described |
| HDI microvia stacks / blind-buried fabrication validation | Not implemented or tested | Not established by the reviewed BGA README |

Dogbone and via-in-pad are placement arrangements. They do not specify whether a via
is mechanically drilled through the board, blind/buried, or a laser microvia. No HDI
claim is made for our two tested arrangements: both currently use through vias.

The suitable technology depends on actual ball/pad geometry, stackup, signal escape
requirements and the fabricator's process limits. A failed through-via fit is not
permission to shrink below manufacturing floors or silently create microvias.

The next HDI implementation needs explicit start/end layers, microvia-specific diameter
and hole limits, stackup dielectric span and aspect ratio, and supported fabrication
process settings. Validate a single permitted microvia hop first, then blind/buried
and stacked/staggered sequences, including filling, connectivity and DRC/export checks.
Microvia stacks described in newer KiCad development documentation must not be assumed
available in the installed KiCad 10 build.

Primary references: [KiCad 10 routing/via documentation](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html#routing-tracks),
[KiCad microvia-stack development](https://gitlab.com/kicad/code/kicad/-/merge_requests/2697),
and the [upstream fanout documentation](https://github.com/drandyhaas/KiCadRoutingTools/tree/main/py_router/bga_fanout).

## Validation and design background

Synthetic integration checks cover 16 independent dogbones, rotated and back-side
footprints, exact native pad-to-via connectivity, existing-route avoidance and
single-use apply tokens. Live editor validation checks native Undo/Redo separately.
Fixtures and local tests remain ignored and are not included in releases.

The external [KiCadRoutingTools BGA fanout documentation](https://github.com/drandyhaas/KiCadRoutingTools/tree/main/py_router/bga_fanout)
was reviewed for general design considerations: pitch detection, manufacturing limits,
site reservation, and distinguishing fanout methods. TraceForge's planner and native
integration are original code; this feature does not import or bundle that project.
