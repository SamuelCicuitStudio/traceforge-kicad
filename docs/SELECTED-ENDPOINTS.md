# Detect a signal path from selected vias or pads

1. In PCB Editor select exactly **two vias or pads on one signal**. Do not select a
   whole track, footprint, or the two opposite legs at one end of a differential pair.
2. Open TraceForge's **Signals / xSignals** tab and click **Detect between selected
   vias / pads**. Detection runs once, highlights the routed path and fits it in view.
3. Review the path's nets, crossed components, track-object length and existing-chain
   status. Adjust the resistor limit, series capacitor option or differential partner
   option, then click **Detect / update path** to reuse the same endpoints.
4. To use different endpoints, select two new items in PCB Editor, then click
   **Use new PCB endpoints**. Ordinary PCB interactions clear the temporary highlight.
5. Enter a group and chain name, then **Add reviewed chain(s)**. This rechecks the live
   route and appends definitions without replacing other chains or group limits.
   The dialog reports chains already covered by an existing definition. Click Signals
   **Refresh** for timing; use Chain editor to review direction and timing limits.

The search uses touching copper shapes on common layers, including arcs and via
layer spans. It can cross two-pad resistors below the chosen limit and two-pad
series capacitors when enabled. Power/ground rails, other parts, unrouted gaps and
zone-only connections are excluded. A capacitor to ground is not a series bridge.

Differential partners use existing chain pairing where available; otherwise common
`_P/_N`, `_DP/_DN` and terminal `+/-` names are recognized. The partner must have
nearby matching endpoint types within 3 mm; pads must be on the same footprint.
Equal-distance candidates are ambiguous and are not guessed. Review inferred pairs.
If a named partner cannot be resolved, fix the endpoints or explicitly disable
**Include differential partner** and detect again before adding a single chain.

At a branch or loop, the preview chooses one shortest routed-item path. Dangling
branches are excluded from that preview. The displayed length sums whole track/arc
objects on the chosen path; it excludes via barrels, pad internals and component
internals. Contact partway along a track does not clip its reported object length.
Endpoint selection order is not a driver-direction measurement.

Saved chain definitions still describe **whole nets**, not an endpoint-bounded
measurement. Their timing table and later chain highlights include net branches.
Consequently, an endpoint path can already be included in a larger chain. This
workflow does not change that model or write guessed timing targets. Saved chains
live in `<board>.traceforge.json`. Adding with auto-detected chains present also
saves those current definitions; review them in Chain editor.

Detection is manual, read-only and time bounded. It does not poll the editor or
change routed geometry. The helper must be updated: restart PCB Editor once after
installing this version, then reopen TraceForge.
