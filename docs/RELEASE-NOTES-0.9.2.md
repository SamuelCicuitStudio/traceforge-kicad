# TraceForge 0.9.2

Endpoint detection accepts two pads, vias, tracks/arcs or footprints, including mixed
types. Selecting components with several possible signals opens a pad-pair choice
before routed-copper tracing. Candidates use the configured passive traversal rules;
the chosen path must still be physically routed. Up to 128 choices are shown.

Both Chain Editor selection buttons use this workflow for any two selected PCB items.
AC-coupling capacitor traversal is enabled by default. The resistor limit remains
visible and adjustable; errors explain restrictions rather than saying a path is
not allowed. Power/ground rails and component internals remain excluded.

Restart PCB Editor once and reopen TraceForge to load the updated native detector.
