# TraceForge 0.9.0

- Signals: select two vias/pads to detect, highlight and fit a routed endpoint path.
- Configurable resistor/capacitor traversal and reviewed differential partner detection.
- Report existing chain coverage; append new definitions without overwriting groups.
- Via Fencing: RF spacing helper with frequency, saved dielectric data and editable
  permittivity; choose wavelength/10 or wavelength/20 independently of copper gap.
- Validated the actual Both sides tab controls and native placement on a synthetic
  RF route containing a straight section, an arc and 45-degree bends.

Restart PCB Editor and reopen TraceForge after updating the native helper. Detection
is manual and does not change copper. Saved chains continue to cover whole nets;
the selected-endpoint preview is a separate routed-path view. RF suggestions are
estimates, not an impedance or antenna solver.
