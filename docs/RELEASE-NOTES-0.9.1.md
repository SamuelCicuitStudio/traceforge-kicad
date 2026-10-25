# TraceForge 0.9.1

Fixed the Signal Chain Editor's **Use KiCad selection** buttons silently ignoring
selected pads and vias. Both buttons now detect the routed endpoint path, highlight
and fit it, preview crossed parts, include a resolvable differential partner and
report existing-chain matches. New definitions are staged until **Apply & save**.

Added an explicit **Detect path from 2 selected pads / vias** button in the editor.
Footprint selection continues to fill component references. Invalid selections
display a useful error; endpoint searches run in a worker without polling.

Close and reopen the TraceForge window to load this panel update. No new helper
operation is required when the native helper from 0.9.0 is already running.
