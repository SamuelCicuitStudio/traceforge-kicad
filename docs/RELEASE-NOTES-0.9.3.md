# TraceForge 0.9.3

- Via Fencing accepts typed fence-net names and a one-click **Pick fence net in PCB**.
- Type or pick the source signal net to load its routed, connected single-layer path.
  Use selected trace for branched, disconnected or multilayer nets.
- Guided path detection prompts for first and second PCB endpoints sequentially,
  then detects and highlights the path. Available in both chain dialogs.
- Native picking completes a single pending request from a canvas event, without
  selection polling. Esc cancels, and a pending pick expires after 90 seconds.

Restart PCB Editor and reopen TraceForge to load the new native picker.
