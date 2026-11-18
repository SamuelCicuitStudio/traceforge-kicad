# Component operations and responsive refresh

Replacement, passive assignment, exact-MPN assignment and component-library changes
share an exclusive operation owner. A second conflicting operation reports that the
active one must finish or be cancelled. The owner remains held through the metadata
transaction and affected-BOM refresh. Batch assignment owns the whole batch, not just
a single row; each row uses that same owner. Analysis dialogs keep their snapshot
exclusive until closed. Read-only catalogue browsing does not require a write lock.

Preparation, parsing, validation and BOM repricing run in worker threads. UI status
shows the current sheet and phase, an ActivityIndicator and elapsed seconds. A cold
scan still needs to parse the project; it reports each sheet instead of appearing idle.
Cancellation is checked during tokenization, parsing and planning. Atomic schematic
and PCB commits finish or roll back safely before another operation may start.

The hierarchy scanner reads and hashes sheet contents. Unchanged sheets reuse a bounded
32 MiB raw-source budget cache of text and compact metadata nodes; embedded library
and drawing trees are not retained. External edits invalidate the matching file's
cache entry. Plans check source text again before recording write hashes, and the
installer retains its compare-and-swap checks before writing. No cache authorizes
writing over a newer file. Only sheets containing affected references are written.

Batch BOM refresh applies all successful metadata changes to its captured source in
one pass, groups/prices once and reuses existing supplier quotes. It does not rerun
full schematic export, catalog search or unchanged-part identity resolution. The UI
retains its incremental row update, selection and scroll handling. Cancellation of
a refresh does not undo already-saved metadata; its status says so.

Local measurement on DroneLink's 24-sheet project: cold hierarchy scan 8.25 seconds;
unchanged scan 0.063 seconds. This measures hierarchy preparation, not supplier network
time, native PCB application or full end-to-end assignment. Progress remains visible
through the final BOM refresh. Other suppliers retain their distinct pricing status.

Cancel operation and the window close control dismiss exact-MPN/passive assignment dialogs immediately. Pending groups stop. An already-started atomic commit and refresh complete through a hidden controller, retaining exclusive ownership until finished. The dialog is destroyed after completion; late callbacks do not reopen it. Previously saved assignments remain saved.
