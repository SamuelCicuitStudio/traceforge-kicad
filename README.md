# KiCad PCB Automation Toolkit

An independent multi-tool KiCad add-on for repetitive and advanced PCB-layout work.
The toolkit combines end-to-end signal-path analysis, copper-zone-aware via
stitching, and interactive parallel routing in one IPC plug-in.

The intended interaction model follows the useful parts of EasyEDA Pro rather than
using blind via arrays or batch autorouting:

- **Signal Path Analyzer:** an Altium xSignal-like workflow built around KiCad Net
  Chains, `fromTo()` rules, tuning profiles, and time-domain length tuning.
- **Zone Via Stitching:** select an existing filled copper zone or draw a bounded
  region, choose the net, via diameter, drill, row/column pitch, offsets, and edge
  clearance, then place only vias that connect valid same-net copper and pass DRC.
- **Parallel Multi-Routing:** select an ordered group of unrouted nets or starting
  pads and route them interactively as a parallel bus. Track order, width, spacing,
  45-degree corners, and obstacle behavior remain controlled while the cursor moves.

## Current status

Version 0.2.0 is the tested foundation and read-only first release:

- connects to a running KiCad 10 PCB Editor through the official IPC API;
- collects routed copper length by net and layer;
- applies optional per-layer propagation-delay values;
- exports a deterministic CSV report beside the board;
- keeps the calculation engine independent from KiCad for automated testing.

It does **not yet** create schematic Net Chains or modify board copper. Via stitching
and parallel routing are specified but not exposed as actions until their placement
engines have undo support, collision checks, and tests. The analyzer does not replace
a field solver.

## Requirements

- KiCad 10.0.1 or newer
- Python 3.9 or newer
- KiCad IPC API enabled in **Preferences → Plugins**

KiCad manages the plug-in Python environment and installs `requirements.txt`.

## Development installation on Windows

Clone this repository into KiCad's plug-in directory, or create a directory junction
from the development checkout:

```powershell
$source = "C:\Tools\TraceForge"
$destination = "$env:USERPROFILE\Documents\KiCad\10.0\plugins\kicad-pcb-automation-toolkit"
New-Item -ItemType Junction -Path $destination -Target $source
```

Restart PCB Editor, enable the IPC API if necessary, and run:

**Tools → External Plugins → Analyze Signal Paths**

The add-on writes `<board-name>.signal-paths.csv` next to the open board. Console
messages appear in KiCad's warning/message area.

## Delay profiles

The core engine accepts propagation delay in picoseconds per millimetre for each
signal layer. The IPC action currently uses physical length only until profile import
is implemented; therefore the generated `delay_ps` cells are blank by default.

Correct time-domain results ultimately require the PCB manufacturer's final stackup,
including dielectric thickness and Dk. The planned profile importer will read KiCad
tuning profiles rather than inventing these values.

## Development

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check .
```

## Tool behavior

The implementation contract is maintained in
[docs/FEATURE-SCOPE.md](docs/FEATURE-SCOPE.md). It distinguishes interactive
parallel routing from automatic routing and defines zone-aware stitching so the tool
does not merely create a rectangular via array.

## Roadmap

1. Import KiCad tuning-profile layer and via delays.
2. Include pad-to-die delay and electrical via height.
3. Add zone-aware via stitching with selectable zone/region, via geometry, pitch,
   offsets, edge setback, layer-connectivity policy, preview, and one-step undo.
4. Add interactive parallel multi-routing with ordered nets, configurable width and
   spacing, 45-degree corners, push/block/walk-around behavior, preview, and undo.
5. Traverse explicit start-pin/end-pin paths with branch detection.
6. Recognize and report schematic Net Chains through series passives.
7. Compare bus groups and differential pairs in picoseconds.
8. Generate reviewed `fromTo()`, `net_chain_length`, `length`, and `skew` rules.
9. Package the toolkit for KiCad's Plugin and Content Manager.

## Safety model

Analysis is read-only. Via placement and routing operations will use KiCad commits so
that every operation is a single undo step. Both tools will show a preview and require
explicit confirmation; they will never suppress DRC violations to force placement.

## License

MIT. See [LICENSE](LICENSE).

