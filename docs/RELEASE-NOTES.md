# TraceForge 0.9.8

Adds **Dim unrelated nets** in the Signals tab. Enable it to keep the selected
chain or differential pair bright while KiCad dims unrelated copper. Works with
chains crossing series resistors/capacitors and endpoint path detection. Native
net focus includes all branches of each highlighted net. Clear, Esc or a changed
native selection releases focus; panning and zooming retain it.

Rerun the installer with PCB Editor closed, then restart PCB Editor and reopen
TraceForge. The installer configures an unused Ctrl+Alt+Shift+F12 shortcut for
KiCad's Highlight Net (selected nets) action when it has no binding. It preserves
custom bindings and backs up a changed user.hotkeys file. Shortcut conflicts are
reported instead of overwritten. Clear Net Highlighting must also have a shortcut.
The installer now respects KICAD_CONFIG_HOME when set.

Verified on a disposable PCB Editor with repeated visual on/off cycles, switching
nets and Clear. Native geometry/ownership checks cover multi-net differential
chains. No global keyboard input or continuous board/selection polling is used.

Supports KiCad 10 on Windows. Existing signal timing, via stitching, RF fencing
and through-via BGA fanout features remain available. Preview generated geometry,
keep ownership sidecars with the board, and run KiCad DRC before manufacturing.
