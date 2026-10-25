# TraceForge 0.9.9

Native net focus now applies automatically whenever TraceForge highlights a signal
path or differential pair. Unrelated copper dims without enabling an option.
The Signals checkbox has been removed. Clear, Esc or a changed native selection
releases focus; panning and zooming retain it. All branches on highlighted nets
remain bright.

Close PCB Editor, run `tools/install_native_bridge.ps1`, then restart PCB Editor.
The installer configures the required native highlight shortcut while preserving
existing custom bindings. This step is required when updating from older versions.

Supports KiCad 10 on Windows.
