# Native board access

TraceForge uses KiCad 10's embedded `pcbnew` Python bindings for live board access.
The wxPython panel runs separately using KiCad's bundled Python. The official IPC API
and kicad-python SDK are not required or used as a fallback.

## Installation and connection

For a PCM installation, use KiCad Manager > Plugin and Content Manager > Install
from file with the `TraceForge-*-KiCad10-PCM.zip` archive. PCM installs the plugin
in KiCad's managed third-party directory. Restart PCB Editor, open a saved board
and use the TraceForge toolbar button. On first launch, TraceForge may assign the
unused native net-focus shortcut; restart PCB Editor again when prompted.

For a standalone installation, extract the Windows ZIP to a permanent directory
and run `tools/install_native_bridge.ps1`. This creates a junction at
`%APPDATA%/kicad/10.0/scripting/plugins/traceforge_native_bridge`.
Restart PCB Editor after installing.

Each editor registers an authenticated localhost endpoint under
`%LOCALAPPDATA%/TraceForge/native-bridge/`. The launcher passes its endpoint and board
identity to the panel. Standalone discovery rejects ambiguous editors. Endpoint files
contain session credentials: do not share or commit them.

Requests accept predefined operations, verify board identity and have size/deadline
limits. Board access executes on KiCad's GUI thread. The socket worker does not access
pcbnew objects. Tabs share one worker and busy guard. Opening a tab or returning to
TraceForge checks the revision and geometry signature once, refreshing stale data.
No periodic board polling or automatic replay of failed commands occurs. F5 remains
available to force a read. Region drawing is not interrupted by automatic checks.
Whole-board Trace Cleanup uses the long board-operation deadline because its
connectivity scan can take longer than a signal snapshot. The panel waits for the
scan result before accepting another request; a slow scan does not require a panel
restart. Restart PCB Editor after updating the native helper so it loads the new
deadline.
Opening the Trace Cleanup tab reads enabled/hidden copper layers and track counts
only. It does not run overlap or dangling-track analysis. Scan / Preview or F5 starts
the full scan. Board operations show a rotating loader centered over the active
tab's results area; only editable controls are disabled while an operation runs,
so findings stay visible.

## Signals

Snapshots read live unsaved routing/tuning geometry. Timing profiles and stackup settings
are read from project files. Refresh never reloads or saves the PCB. Highlight cleanup
records UUIDs and prior flags, not item pointers. Mouse-down, navigation drags, wheel
zoom and navigation keys preserve the highlight. After a click or key action, a
deferred check clears Forge's visual flags if native selection changed, or Esc was
pressed. Cleanup preserves the user's new native selection. It does not poll.

Automatic zoom retains magnification for nearby or shorter chains after the initial
fit and zooms out when a larger chain needs room. Explicit Zoom selection refits.
Signal highlights are visual flags, not guaranteed editable multi-object selections.

Every signal-path highlight automatically invokes KiCad's native renderer
highlight for all selected copper nets. Board highlight flags alone do not update
the canvas renderer, so the helper uses targeted wx key events for the configured
`pcbnew.EditorControl.highlightNetSelection` and `clearHighlight` actions. Events
target the visible drawing canvas; no global key simulation, internal action-ID
guessing, or selection polling is used. The PCM launcher or standalone installer
assigns an unused default shortcut for an unbound selection action, preserving
existing custom bindings. Restart PCB Editor after a shortcut change. Clearing
releases the native focus.
Net focus includes same-net branches outside the chosen endpoint path.
Lengths and delays are aggregate estimates, not replicas of KiCad's point-to-point tuner.

## Via stitching

Stitching commands create/remove through vias, refill zones and validate connectivity.
Changes execute through an internal registered ActionPlugin so KiCad captures undo
history. The user saves the PCB normally; TraceForge never silently rewrites the PCB.

Sets use exact generated via UUIDs, with recipes and ownership history in
`<board>.traceforge-stitching.json`. Native groups are not used. Selection synchronizes
individual via flags through native Refresh. Ownership recovers from live UUIDs after
undo/redo and save/reopen. Ordinary vias are not inferred from size or location.
Locked or manually altered vias are preserved by automatic removal/regeneration.

Preview is non-destructive. Apply revalidates live geometry and uses a single-use token.
Drawing and preview use the tab's board overview, not KiCad's canvas. Custom DRC-rule
evaluation and courtyard exclusion are incomplete: run KiCad DRC after placement.
Native geometry/refill may briefly occupy the editor's GUI thread.

## Compatibility and diagnostics

In 0.8, `fanout_*` commands provide BGA pad-to-via breakout using the same native
undo transaction path. A third tab shares the existing worker/guard and performs no
automatic polling. Preview tokens are single-use and revalidated against current
footprint and geometry before Apply. See [BGA Fanout](BGA-FANOUT.md) for method,
fabrication and routing limitations.

This release targets KiCad 10 on Windows. Legacy pcbnew bindings are planned for removal
in KiCad 11. TraceForge does not modify KiCad's official API implementation.
Logs are at `%APPDATA%/TraceForge/traceforge.log`. Review private board paths before
sharing logs. See [stitching testing](VIA-STITCHING-TESTING.md) for manual acceptance.
