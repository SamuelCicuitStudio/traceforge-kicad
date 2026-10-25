# TraceForge 0.9.4

Endpoint path detection now follows all two-pad series resistors by default rather
than silently stopping at the old 100-ohm threshold. This supports indicator and
other signal paths crossing higher-value series resistors and multiple net names.
The new **Follow all series resistors** checkbox can be disabled to restore the
explicit resistor limit. Series capacitor traversal remains configurable.

This is a connectivity path view, not a claim that arbitrary resistors preserve
high-speed signal integrity. Power/ground rails and component internals remain
excluded. Geometry and routing must still connect the selected endpoints.

Restart PCB Editor and reopen TraceForge to load the updated native detector.
