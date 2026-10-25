# TraceForge 0.9.5

Tabs load automatically on first opening. Returning to TraceForge after editing in
PCB Editor, or revisiting a tab, makes one change check. Unchanged tabs skip the
full refresh. Changed tabs refresh through the shared worker; Signals retains its
existing rows, scroll position and expanded groups. Managed via lists retain set
selection across refreshes. BGA analysis also responds to selection changes.

The check uses KiCad's revision plus a read-only geometry/settings signature to
catch direct pcbnew edits that do not advance the revision. No periodic board
polling, selection polling or retry loop is introduced. Region drawing is left
undisturbed. Busy tab checks coalesce until the current operation completes.
Automatic failures retain prior data; F5 remains the explicit refresh fallback.

Automatic updates happen on tab/focus transitions, not continuously while routing.
Restart PCB Editor and reopen TraceForge to load the revision helper update.
