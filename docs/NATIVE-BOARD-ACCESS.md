# Native board access for KiCad 10

KiCad may continue returning AS_BUSY after rerouting or tuning even when the editor remains usable. Retrying or reconnecting the IPC client cannot safely reset the editor's internal tool state. TraceForge therefore supports a KiCad 10 in-process helper for its board operations. This avoids the blocked IPC server; it does not patch or reset KiCad's busy flag.

## Installation

From the toolkit checkout, run `tools/install_native_bridge.ps1` on Windows. It installs a directory junction under `%APPDATA%/kicad/10.0/scripting/plugins/traceforge_native_bridge`. No KiCad binaries or board files are replaced. Restart PCB Editor once so its legacy Python plugin loader can import the helper. Launch TraceForge as usual and click Refresh. The status line must include `native board access`; startup logging also records `Board access backend: native`. If it says IPC API, the helper was not loaded and the blocked-server issue can still occur.

The helper also has a Tools > External Plugins > TraceForge: Native board access command. It starts automatically after plugin discovery; the menu command can confirm that it is enabled. To uninstall, remove only the directory junction created above, leaving its source directory intact, and restart PCB Editor.

## Behavior

Refresh reads the current in-memory board, including unsaved reroutes and tuning changes. Highlighting, clearing, chain detection, selection lookup, CSV export and DRC name lookup also use the helper. Board geometry is never loaded from disk during a refresh. Existing timing/stackup profiles still come from the project files, as before.

Selecting a chain automatically zooms with the native helper. It calibrates from the editor's Zoom Auto view, chooses a conservative zoom preset for the combined chain bounds, and centers that area with an unregistered focus point. This changes the view without adding a board object or requesting IPC zoom. Differential partners are included in the same bounds. The Zoom selection button repeats this explicitly. There is no automatic polling.

A localhost socket accepts requests authenticated by a random per-process token stored in the user's local application-data folder. Every request validates the intended board path. Socket handling runs in a background thread; all model access is scheduled on the editor's wx main thread. Only specific read/highlight operations are exposed, not arbitrary code execution. Requests and responses have size/time limits. The helper does not save, route, tune, delete, or rewrite board copper. Highlighting uses transient item selection/brightening flags; the normal KiCad selection tool maintains additional state beyond these visual flags. The helper stores UUIDs and previous flags, not pointers to items that routing could delete. A wx event filter restores only Forge-owned flags before the next click or key action in PCB Editor. It does not consume the input or clear unrelated selections. Do not treat highlighting as an automatic move/edit selection operation.

This helper uses the legacy pcbnew Python interface included in KiCad 10. It is not a KiCad 11 solution, where that interface is being removed. The IPC backend remains available when the helper is not installed.

## Verification

Run KiCad's Python with `tools/check_native_bridge.py BOARD.kicad_pcb`. It tests a separate in-memory board copy, alters track geometry twice without saving, and verifies fresh lengths, highlight/clear, board-path validation and unchanged source-file hash. It makes no KiCad IPC requests. Tests also verify that Session.evaluate and chain selection use the native transport when the IPC board object is unusable.

A real PCB Editor test with a temporary management-board copy verified plugin auto-loading, native discovery, live geometry reads and selection/clear through the installed helper. That temporary editor was closed afterward. Re-test your actual rerouting/tuning sequence after restarting with the helper loaded; the source-level KiCad busy flag itself has not been repaired or reproduced in a debugger.

After updating this helper, restart PCB Editor once to reload its in-process Python module. Protocol 2 advertises transient_highlight and native_zoom features. The source-file hash check and the runtime test also cover interaction-triggered highlight cleanup and preservation of unrelated selection flags.
