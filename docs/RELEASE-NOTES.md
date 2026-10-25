# TraceForge 0.10.2

Trace Cleanup now reports **every enabled copper layer on the open PCB**,
including layers hidden in PCB Editor and layers with no tracks. The layer
selector marks hidden layers, and the summary shows cleanup findings and scanned
track counts for each layer. Full-board Scan / Preview does not depend on the
active or visible layer. The selected layer filters review and checked actions.

Verified with a six-layer synthetic PCB: F.Cu, In1.Cu, In2.Cu, In3.Cu, In4.Cu
and B.Cu each contained duplicate and fuse candidates. In1.Cu and In3.Cu were
hidden; both were still detected and could be selected in Trace Cleanup. The
saved management PCB was also scanned read-only: all six layers appeared, with
three correctly showing zero tracks/findings.

Fusion, duplicate removal, native dangling detection and KiCad Undo remain
available. Restart PCB Editor after updating TraceForge. Run DRC after edits.
Supports KiCad 10 on Windows.
