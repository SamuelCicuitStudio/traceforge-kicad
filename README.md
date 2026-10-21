# KiCad Signal Path Analyzer

An independent KiCad add-on for end-to-end signal-path analysis, propagation-delay
reporting, and timing-rule generation. The long-term goal is an Altium xSignal-like
workflow built around KiCad's native Net Chains, `fromTo()` rules, tuning profiles,
and time-domain length tuning.

## Current status

Version 0.1.0 is a tested foundation and read-only first release:

- connects to a running KiCad 10 PCB Editor through the official IPC API;
- collects routed copper length by net and layer;
- applies optional per-layer propagation-delay values;
- exports a deterministic CSV report beside the board;
- keeps the calculation engine independent from KiCad for automated testing.

It does **not yet** create schematic Net Chains, alter routing, or replace a field
solver. Via delay, pad-to-die delay, pin-to-pin path traversal, grouped skew analysis,
and `.kicad_dru` generation are planned next.

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
$destination = "$env:USERPROFILE\Documents\KiCad\10.0\plugins\kicad-signal-path-analyzer"
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

## Roadmap

1. Import KiCad tuning-profile layer and via delays.
2. Include pad-to-die delay and electrical via height.
3. Traverse explicit start-pin/end-pin paths with branch detection.
4. Recognize and report schematic Net Chains through series passives.
5. Compare bus groups and differential pairs in picoseconds.
6. Generate reviewed `fromTo()`, `net_chain_length`, `length`, and `skew` rules.
7. Add an interactive path/group editor and visual PCB highlighting.
8. Package the add-on for KiCad's Plugin and Content Manager.

## Safety model

Analysis is read-only. Future write operations will use KiCad commits so that every
change is undoable, and rule generation will require explicit confirmation.

## License

MIT. See [LICENSE](LICENSE).

