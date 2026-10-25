# pcbnew-only mode (0.6)

All TraceForge actions, including startup, use the native helper. No kicad-python SDK, official
API command, or API-enabled preference is needed. The panel remains a separate wxPython process;
its colors, table, chain editor, shortcuts, automatic zoom and exports remain available.

Run `tools/install_native_bridge.ps1`, restart PCB Editor and launch from the native TraceForge
button. The helper's distinct ActionPlugin classes register the panel, highlight, export and
optional older monitor commands. The native launcher selects KiCad's bundled Python, passes the
editor endpoint and board filename, and removes official IPC environment variables from its child.
The retired IPC manifest is archived under `docs/legacy/` rather than registered at the repo root.

The helper is installed under `%APPDATA%/kicad/10.0/scripting/plugins/traceforge_native_bridge`.
Its source lives in `native_bridge/` in this checkout. Refresh reports `pcbnew native board access`.
If the helper cannot be found, startup reports how to install it and does not fall back to IPC.
Multiple-editor launches require an explicit endpoint or board identity, preventing accidental
access to a different board. Native toolbar launch supplies both.

The helper binds only to localhost and authenticates requests with a random per-editor token.
Only predefined operations are accepted; arbitrary code and board-saving commands are not exposed.
Requests verify the board path and have size/time limits. Board reads and highlight changes run
on the editor's wx main thread. The socket worker never accesses pcbnew objects.

Snapshots read the live in-memory board, including unsaved routing/tuning changes. Existing
propagation profiles and stackup information are loaded from project files. No board reload or
file snapshot is substituted silently. Native zoom uses the editor's zoom control and a temporary
unregistered focus point. No board object is added. Transient highlight cleanup stores UUIDs and
previous flags so deleted items cannot leave dangling Python pointers. A mouse/key event filter
clears Forge-owned flags before normal PCB interaction without consuming the event.

Automatic zoom calibrates to board extents once per board/window size, rather than fitting
the entire board on each row click. Subsequent selections preserve magnification, except
when a larger chain needs a zoom-out. Native focus pans only if its focus point needs to
be brought into view. The explicit Zoom selection button requests a fresh selection fit.
Five camera regression checks cover adjacent chains, shorter/larger chains, explicit
refitting and manual magnification changes.

Signal chain highlights remain visual flags, not a promise that KiCad's selection manager will
treat the highlighted chain as a multi-object edit selection. Signal commands do not route,
delete, move or save copper. Failure does not trigger automatic retries or an IPC fallback.

In 0.7, separate `stitch_*` commands support the Via Stitching tab. These commands can
add/remove through vias and refill zones, using a registered internal ActionPlugin whose
Run executes inside KiCad's native undo wrapper. Exact generated via UUIDs and settings
are journaled in a separate stitching JSON file before placement; history remains for
Undo/Redo recovery. Native groups were rejected after the prototype exposed inconsistent
membership restoration across regeneration. Stitching selection synchronizes individual
via flags with the real selection tool via native Refresh. Signal highlighting behavior
is unchanged. Stitching operations use longer transport deadlines for refill; they do
not retry or save the PCB automatically. See README for the current placement limits.

For tests, run KiCad's Python with `tools/check_native_bridge.py BOARD.kicad_pcb`.
The test uses an isolated in-memory board, changes geometry twice without saving, verifies
new lengths, transient highlight cleanup and board-path validation, and checks the source file
hash is unchanged. Unit tests also cover startup without the official SDK, missing helpers,
ambiguous editors, and all panel board callbacks.

Migration validation: 48 unit tests and Ruff passed. KiCad's bundled Python, without the
official SDK installed, evaluated the management board's 29 groups and 123 chains. A
disposable PCB Editor instance launched the panel through its native menu, refreshed the
saved chain configuration, displayed the colored status counters, repeated native
highlight/zoom/clear three times, and exported 386 net summaries. The in-memory helper
check verified unsaved geometry changes; real interactive rerouting/tuning remains a
manual acceptance check.

This backend targets KiCad 10. The legacy Python interface is planned for removal in KiCad 11;
this migration does not restore or patch the official API's native busy flag.
