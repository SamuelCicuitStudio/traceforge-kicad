# TraceForge 0.11.0 — BGA escape and KiCad PCM package

This version adds BGA fit guidance and **Auto escape to BGA edge**. TraceForge
previews connected routes from selected single-ended pads to the BGA field edge,
reports pads it cannot escape, and rechecks the board before applying reviewed
routes. Through vias and one selected escape layer are supported. Routes end at
the BGA edge for you to continue; this is not full-board autorouting.

The new KiCad Plugin and Content Manager ZIP installs TraceForge under KiCad's
managed plugin directory on Windows. The existing standalone Windows ZIP remains
available for manual installation. Both target KiCad 10 and its native `pcbnew`
Python bindings. KiCad 11 is not supported.

The README now shows the current interface on the management switch board and
live BGA preview/apply on a disposable test board. On that 4 by 4 board, Apply
created 16 escaped routes (16 vias and 32 segments). KiCad Undo and Redo worked;
managed removal returned the board to zero tracks and vias and was itself undoable.
The test suite, lint and release builds pass. Run KiCad DRC after applying routes.
