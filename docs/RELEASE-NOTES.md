# TraceForge 0.9.7 - KiCad 10 preview

TraceForge combines signal-path/timing analysis, managed via stitching, RF trace
fencing and BGA fanout in one native pcbnew-based panel for Windows/KiCad 10.

- Guided first/second endpoint picking and detection through series resistors and
  capacitors across different net names, with differential-pair review.
- Change-aware tab refresh without continuous polling or automatic retry loops.
- Path highlights retained while panning and zooming.
- Symmetric/staggered stitching, trace-following fences on both sides, editable
  net inputs and RF spacing guidance.
- BGA suggestions, preview, apply and managed removal for through-via breakouts.
- Public repository cleanup, illustrated README and install/update instructions.
  Removed obsolete web/Tk dashboards; the Signals tab is the timing interface.
- Installer can safely switch an existing junction with `-ReplaceExisting`.

Extract the Windows ZIP to a permanent folder, close PCB Editor and run
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\install_native_bridge.ps1`.
Restart PCB Editor, open a saved board and launch TraceForge from its toolbar.
Use `-ReplaceExisting` when changing the installation folder.

Keep generated ownership sidecars with the PCB. Preview placements and run KiCad
DRC. Microvias, full BGA escape routing and live parallel multirouting are not
implemented. This is a pre-release for review and testing.
