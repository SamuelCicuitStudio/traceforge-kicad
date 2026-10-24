# TraceForge — KiCad PCB Automation Toolkit

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

Version 0.4.0 puts everything behind **one toolbar button, TraceForge**, which opens a floating
**TraceForge panel** over the PCB editor:

- **One button.** Clicking it again brings the open panel to the front instead of opening a second.
- **Floating panel.** On Windows it is owned by the PCB editor window: it stays above KiCad, can be
  left open, minimises with KiCad and does not cover other applications. It uses wxPython, KiCad's
  own toolkit, which is available in KiCad's plugin environment.
- **Live signal timing.** The panel refreshes every second with the chain totals through series
  resistors and chokes, group targets, delta, P-N skew and stub length. Status is shown as
  ✔ ok, ▲ short, ▼ long, … pending, and ✖ stub too long.
- **Tools.** Highlight chain, Highlight group, Clear, Write DRC targets, Export paths, Shortcuts.
- **Keyboard shortcuts.** These work from the KiCad canvas while the panel is open, and can be
  changed under **Shortcuts…** (saved in `%APPDATA%\TraceForge\settings.json`):

  | Shortcut | Action |
  |---|---|
  | Ctrl+Alt+H | highlight the chain of the item selected in KiCad |
  | Ctrl+Alt+G | highlight its whole group |
  | Ctrl+Alt+C | clear the selection |
  | Ctrl+Alt+W | write DRC targets |
  | Ctrl+Alt+E | export signal paths |
  | Ctrl+Alt+T | show or hide the panel |

**Any project works.** With no `xsignals.json`, TraceForge finds the chains on the board
automatically. Every resistor of 100 Ω or less between nets of a netclass that has a KiCad tuning
profile becomes a chain, and multi-resistor paths are joined. Chains are grouped by netclass, and
`_P`/`_N` chains become pairs. The status line says "auto-detected". **Save config** writes them to
`xsignals.json` so you can set the driver side, stub limits and skew. DRC targets are written only
from a saved, reviewed config.

**Theme.** The panel follows KiCad's light or dark setting (`kicad_common.json` →
`appearance.app_theme`), using wxWidgets 3.3 dark mode.

**Overlay.** The panel is always on top only while KiCad or the panel is the active application.
It is a separate window, because KiCad does not let plugins dock panels. An earlier build tied the
panel to KiCad's window across processes, which crashed on exit; that is no longer used.

**Log.** `%APPDATA%\TraceForge	raceforge.log` (KiCad runs plugins without a console).

The individual actions also remain in **Tools → External Plugins**, without toolbar buttons. The
browser dashboard of 0.3.x is still available from the **TraceForge: Signal Timing Monitor** menu
action.

Version 0.3.0 added **net chains (xSignals)** for KiCad 10.0.1, which has no native net chains:

- **Net Chain Monitor:** a live window, refreshed every second while you route. It shows each
  chain's total delay through series resistors and chokes (tracks + vias + pad-to-die), the group
  target, the delta, P-N skew on chain totals, and stub length. It can highlight a chain or group,
  and it writes ps length targets into the project `.kicad_dru`, so KiCad's own tuner brings each
  whole chain to its target.
- **Highlight Net Chain:** select any track, via, pad or series part and run the action. Every net
  of the chain and its series parts are selected end to end. It uses the project's chain config,
  or auto-detects through resistors of 100 Ω or less and 4-pad common-mode chokes.
- **Delay model identical to KiCad 10.0.1:** tuning-profile per-layer delay; via delay = via unit
  delay × the via's barrel height (top of start layer to bottom of end layer). On the reference board
  board it reproduces KiCad's `GetDelay()`: 128.668 ps for F.Cu 10 mm + In2 10 mm, and 11.374 ps
  per through via.
- Signal Path Analyzer CSV export (0.2.0) is unchanged.

Limits in 10.0.1:

- KiCad's length tuner still shows only the single net being dragged; the monitor shows the chain.
- The IPC API has no change events, so the monitor polls only the chain nets.
- The IPC API does not expose pad-to-die *delay*. Pad-to-die length × `pad_to_die_ps_per_mm`
  from the chain config is used instead.
- `kicad-cli pcb drc` ignores ps limits; the PCB editor's DRC applies them.

Via stitching and parallel routing are specified but not exposed as actions until their placement
engines have undo support, collision checks, and tests. The analyzer does not replace a field
solver.

## Net chain configuration

Put `xsignals.json` in the project root or in `docs/design/`:

```json
{
 "pad_to_die_ps_per_mm": 6.952,
 "groups": {
  "RGMII_RX": {"skew_ps": 20, "stub_max_ps": 15, "chains": {
   "RXD0": {"nets": ["/ETHERNET/PHY1_RXD0_PHY", "/PHY1_RXD0_RXDLY"], "series": ["R141"]}}},
  "USB_OTG0": {"pair_skew_ps": 0.7, "stub_max_ps": 15, "chains": {
   "P": {"nets": ["/USB/CON_P", "/USB/OTG0_P"], "series": ["L10"], "pair": "N"},
   "N": {"nets": ["/USB/CON_N", "/USB/OTG0_N"], "series": ["L10"], "pair": "P"}}}
 }
}
```

- **Chain nets** are listed from driver to receiver. The first net of a multi-net chain is the stub
  (driver → series part). The last net is the one you tune.
- **Group target** is the slowest routed chain.
- **Pair-only groups** match P to N on the chain totals.
- **Net names** use the schematic form ('/' plain); `{slash}` board names are matched
  automatically.

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

**Tools → External Plugins → TraceForge: Signal Timing Monitor**, **TraceForge: Highlight Signal Chain** (toolbar buttons with icons), or
**TraceForge: Export Signal Paths**

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
6. Recognize and report schematic Net Chains through series passives. (0.3.0: config + auto-detected chains, live monitor, highlighting)
7. Compare bus groups and differential pairs in picoseconds.
8. Generate reviewed `fromTo()`, `net_chain_length`, `length`, and `skew` rules.
9. Package the toolkit for KiCad's Plugin and Content Manager.

## Safety model

Analysis is read-only. Via placement and routing operations will use KiCad commits so
that every operation is a single undo step. Both tools will show a preview and require
explicit confirmation; they will never suppress DRC violations to force placement.

## License

MIT. See [LICENSE](LICENSE).

