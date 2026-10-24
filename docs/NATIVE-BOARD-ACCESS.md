# Native board access for KiCad 10

KiCad may continue returning AS_BUSY after rerouting or tuning even when the editor remains usable. Retrying or reconnecting the IPC client cannot safely reset the editor's internal tool state. TraceForge therefore supports a KiCad 10 in-process helper for its board operations. This avoids the blocked IPC server; it does not patch or reset KiCad's busy flag.

## Installation

From the toolkit checkout, run `tools/install_native_bridge.ps1` on Windows. It installs a directory junction under `%APPDATA%/kicad/10.0/scripting/plugins/traceforge_native_bridge`. No KiCad binaries or board files are replaced. Restart PCB Editor once so its legacy Python plugin loader can import the helper. Launch TraceForge as usual and click Refresh. The status line must include `native board access`; startup logging also records `Board access backend: native`. If it says IPC API, the helper was not loaded and the blocked-server issue can still occur.

The helper also has a Tools > External Plugins > TraceForge: Native board access command. It starts automatically after plugin discovery; the menu command can confirm that it is enabled. To uninstall, remove only the directory junction created above, leaving its source directory intact, and restart PCB Editor.

## Behavior

Refresh reads the current in-memory board, including unsaved reroutes and tuning changes. Highlighting, clearing, chain detection, selection lookup, CSV export and DRC name lookup also use the helper. Board geometry is never loaded from disk during a refresh. Existing timing/stackup profiles still come from the project files, as before.

The explicit Zoom selection command currently continues using KiCad's IPC tool action. It may still fail if the native KiCad IPC state is stuck; this does not stop native refresh or native highlighting. Selection remains manual and there is no automatic polling.

A localhost socket accepts requests authenticated by a random per-process token stored in the user's local application-data folder. Every request validates the intended board path. Socket handling runs in a background thread; all model access is scheduled on the editor's wx main thread. Only specific read/highlight operations are exposed, not arbitrary code execution. Requests and responses have size/time limits. The helper does not save, route, tune, delete, or rewrite board copper. Highlighting uses item selection/brightening flags; the normal KiCad selection tool may maintain additional state beyond these visual flags. Do not treat this command as an automatic move/edit selection operation.

This helper uses the legacy pcbnew Python interface included in KiCad 10. It is not a KiCad 11 solution, where that interface is being removed. The IPC backend remains available when the helper is not installed.

## Verification

Run KiCad's Python with `tools/check_native_bridge.py BOARD.kicad_pcb`. It tests a separate in-memory board copy, alters track geometry twice without saving, and verifies fresh lengths, highlight/clear, board-path validation and unchanged source-file hash. It makes no KiCad IPC requests. Tests also verify that Session.evaluate and chain selection use the native transport when the IPC board object is unusable.

A real PCB Editor test with a temporary management-board copy verified plugin auto-loading, native discovery, live geometry reads and selection/clear through the installed helper. That temporary editor was closed afterward. Re-test your actual rerouting/tuning sequence after restarting with the helper loaded; the source-level KiCad busy flag itself has not been repaired or reproduced in a debugger.
