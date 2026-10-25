# TraceForge 0.8.0

Adds **BGA Fanout**, a third tab for selected-footprint pad-to-via breakout.

- Detect rectangular-grid X/Y pitch and footprint orientation/side.
- Preview dogbone stubs with automatic half-pitch or custom X/Y offsets.
- Explicit via-in-pad mode with fabrication-support confirmation.
- Active/named board presets, per-net netclass or custom via dimensions.
- Net/pad wildcard filters, clearance and width controls, per-pad rejection reasons.
- Native, undoable placement with live revalidation, single-use tokens, refill and
  pad-to-via connectivity checking. Existing routed pads are skipped.
- Geometry-checked through-via suggestions and UUID-based removal of generated fanout,
  preserving manual routing and edited/locked items. Ownership recipes are stored
  alongside the board in `.traceforge-fanout.json`.
- Perimeter via fencing in the Via Stitching tab, with inset contours/cutouts,
  managed placement/removal and largest-gap reporting when sites are rejected.

This is an initial breakout implementation, not full BGA escape routing or live
multirouting. Vias are through-hole only; no pair coupling or length matching.
See [BGA Fanout](BGA-FANOUT.md) for limitations and the test workflow.

Signals / xSignals and Via Stitching remain available in the first two tabs.
Install the same way as 0.7 and restart PCB Editor once after upgrading.
