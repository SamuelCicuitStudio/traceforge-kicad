# TraceForge 0.9.6

Fixed highlighted paths disappearing as soon as a PCB mouse button was pressed.
Hold-and-drag navigation, wheel zoom, middle/right presses and navigation keys
retain the highlight. A deferred check after click/key completion clears it when
the native selection actually changes or Esc is pressed. Cleanup preserves the
new native selection instead of restoring the original one over it.

Checks are event driven, without periodic selection polling. Delayed cleanup from
an earlier highlight cannot clear a newly highlighted path. Restart PCB Editor and
reopen TraceForge to load the updated native event filter.
