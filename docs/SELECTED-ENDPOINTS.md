# Detect a signal path from selected PCB items

For guided selection, click **Pick first, then second endpoint in PCB** in Chain
Editor (or **Pick first, then second** in the endpoint dialog). TraceForge prompts
you to click the first pad, via, track or component in PCB Editor, remembers that
item, then prompts for the second. Detection runs automatically after the second
click. The clicked items supply both their nets and physical endpoints, so the
tool can trace between two points even when both belong to the same net. You do
not need to Shift-select both together. Esc in PCB Editor cancels a pending pick;
an unanswered pick expires after 90 seconds. No selection polling is used.

You can also use the **Signal Chain Editor** directly: select two pads, vias, tracks
or components, then click either **Use KiCad selection** button or **Detect path
from 2 selected PCB items**. The editor previews the highlighted path and crossed parts,
selects any existing matching rows, and stages new chains for **Apply & save**.
Detection runs in a worker without blocking the dialog. Invalid selections show an
error instead of silently clearing the component reference field. Selecting source
or destination footprints individually still fills references for component search.
With both component fields empty, **Find chains** also uses endpoint detection.

1. Select exactly **two pads, vias, tracks/arcs or footprints** as path endpoints.
   Mixed types work. Components with multiple signal candidates open a pad-pair
   choice (up to 128 shown); the chosen path must still be continuously routed.
   Select opposite ends of one signal, not both differential legs at the same end.
2. Open **Signals / xSignals** and click **Detect path between 2 selected PCB items**.
   Detection runs once, highlights the routed path and fits it in view.
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
layer spans. **Follow all series resistors** is enabled by default for endpoint
paths, so a 1 kOhm or 10 kOhm series part does not silently break detection at the
old 100-ohm threshold. Turn it off to use the resistor limit. In Chain Editor this
option applies to endpoint paths; component searches retain their explicit limit.
Multiple successive two-pad resistors and series capacitors can join different
net names along one path; endpoints need not share a net name. Capacitor traversal
must be enabled. Power/ground rails, other parts, unrouted gaps and
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
