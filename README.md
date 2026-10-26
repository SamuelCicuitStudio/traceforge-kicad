# TraceForge

<img src="icons/traceforge-light-48.png" alt="TraceForge icon" width="72" height="72">

**Signal paths, trace cleanup, via stitching, RF fencing and BGA fanout for KiCad 10 on Windows.**

TraceForge puts five PCB tools in one colored panel. It reads the open board through
KiCad's native `pcbnew` bindings, including unsaved routing changes. No official
IPC API setup, API token, or pip runtime dependencies are needed.

![TraceForge Signals tab over the management switch PCB in KiCad](docs/screenshots/signals-xsignals.png)

*Current TraceForge in PCB Editor on the 03-MANAGEMENT-SWITCH-BOARD project. The
selected signal path is highlighted on the board.*

## Install

**Requirements:** Windows and KiCad 10 with its bundled Python/scripting support.

### KiCad Plugin and Content Manager

Download `TraceForge-0.11.6-KiCad10-PCM.zip` from the GitHub release. In KiCad
Manager, open **Plugin and Content Manager > Install from file**, select that ZIP,
then close all KiCad windows and reopen PCB Editor. Once KiCad accepts TraceForge into its official catalog,
you can instead install or update it directly from the Manager's Repository tab.

The first launch may assign KiCad's unused **Ctrl+Alt+Shift+F12** shortcut for
native net focus. If TraceForge asks, restart PCB Editor once more. An existing
`user.hotkeys` file is backed up as `user.hotkeys.traceforge.bak`; shortcut
conflicts are reported without changing the existing binding. PCM installation
does not require PowerShell or a manually created plugin junction.

### Standalone Windows ZIP

1. Download the **TraceForge KiCad10 Windows ZIP** from this repository's Releases
   page. Extract it completely into a permanent folder, for example
   `C:\Tools\TraceForge`. Do not run the plugin from inside the ZIP.
2. Save your work and close all KiCad windows, including KiCad Manager.
3. Open the extracted folder, right-click inside it and choose **Open in Terminal**.
   In PowerShell run:

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\install_native_bridge.ps1
   ```

   This applies the script policy to that process only. Administrator access is
   normally unnecessary. The installer creates a junction at
   `%APPDATA%\kicad\10.0\scripting\plugins\traceforge_native_bridge`
   pointing to the extracted `native_bridge` folder. Keep the extracted files there.
4. Start PCB Editor, open and save a board, then click the **TraceForge** toolbar
   icon or **Tools > External Plugins > TraceForge**.
5. Open a feature tab. It loads automatically. **F5** or **Refresh** forces a refresh.

Cloning this repository into a permanent folder and running the same installer
also works. No separate Python installation is needed to use the plugin.

### Update or remove a standalone installation

Close PCB Editor and extract the new version. If its folder differs from the old
installation, run the installer from the new folder with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\install_native_bridge.ps1 -ReplaceExisting
```

This switches the plugin junction and preserves the previous installation folder.
The installer refuses to replace an ordinary folder. Restart PCB Editor afterward.
For a Git checkout already linked by the installer, pull updates, rerun the
installer with all KiCad windows closed, and restart PCB Editor.

To uninstall, close PCB Editor and remove **only the junction** at the plugin path
above; keep your board files and TraceForge sidecars. Removing the installation
folder while the junction exists leaves a broken plugin link.

## Choose a tool

| Tab | Workflow |
| --- | --- |
| **Signals / xSignals** | Detect paths through series passives, inspect chain length/timing, highlight differential pairs, export CSV and write reviewed DRC targets. |
| **Via Stitching** | Preview symmetric or staggered via grids in a whole board, selected zone, rectangle or polygon; select, regenerate or remove managed sets. |
| **BGA Fanout** | Analyze a selected BGA, check geometric fit, and preview dogbone, via-in-pad, or bounded escape-to-edge routes. |
| **Via Fencing** | Place managed ground-via rows on either or both sides of a routed RF trace; control copper gap, spacing and via size. |
| **Trace Cleanup** | Preview redundant copper and native dangling-end findings, remove reviewed tracks with Undo, then recheck Signals. |

### Signals and path detection

The screenshot above shows the current Signals / xSignals tab on the management
switch board, including chain timing, pair status, and the PCB highlight.

Select two pads, vias, tracks or components, then use **Detect path between 2 selected
PCB items**. Alternatively choose **Pick first, then second** and click each endpoint
in PCB Editor. The Chain Editor supports the same guided workflow.

The detector crosses series resistors and enabled AC-coupling capacitors across
different net names. Review crossed parts, inferred differential partners and any
existing-chain matches before saving. A resistor limit is optional. Component
selections with multiple candidate signals offer a path choice.

Click a chain to highlight and zoom to it. Highlights stay visible during panning
and zooming; changing the native selection or pressing Esc clears them. Green,
amber, red, blue and gray states distinguish matched, warning, error, routed and
pending results. Signals refresh preserves scrolling and expanded groups.

Selecting a path automatically keeps the chain's nets bright while KiCad dims
unrelated copper. This also applies to endpoint detection and both
differential legs. Other branches belonging to those same nets remain bright.
Clear, Esc or a changed native selection releases the effect; panning/zooming keeps it.

For a PCM installation, TraceForge assigns **Ctrl+Alt+Shift+F12** to KiCad's
**Highlight Net (selected nets)** action on first launch if the action is
unassigned and that shortcut is unused. Restart PCB Editor when prompted. For
a standalone installation, rerun the installer with all KiCad windows closed.
Existing custom bindings are preserved; a changed hotkey file is backed up as
`user.hotkeys.traceforge.bak`. A conflict is reported instead of overwritten.
The native **Clear Net Highlighting** action also needs its shortcut enabled.
TraceForge sends these actions directly to KiCad's visible canvas, without global
keyboard input or a polling loop. Net focus is automatic; no checkbox is needed.

See [endpoint detection](docs/SELECTED-ENDPOINTS.md) for details. Saved chain timing
sums whole-net copper, including branches; the endpoint preview follows one routed
path. Neither is an exact reproduction of KiCad's point-to-point tuner. Timing
requires validated project propagation profiles and stackup data. Review driver
orientation and limits before writing DRC targets.

### Via stitching

![Via Stitching tab in the published 0.11.0 build on the management switch PCB](docs/screenshots/via-stitching.png)

*This capture precedes Preview; no stitching vias were added to the project.
The 0.11.5 release has a condensed basic form.*

Choose the net, via preset/netclass/custom size, and center-to-center X/Y spacing.
Choose the whole board, a PCB zone/drawing, or draw a rectangle/polygon in the
tab's overview, then **Preview** and **Apply stitching**. Accepted locations are
green; rejected locations are amber. Symmetric is the default placement pattern;
staggered/perimeter patterns, copper-contact rules, grid offsets and setbacks are
under **Advanced options**. Whole-board grids are evaluated without a fixed
5,000-location limit; dense boards can take longer to preview and apply.
The **About** tab and window title show the version currently running; About also
shows the loaded code path and log location when checking an installation.

Select, edit/regenerate or remove tool-created sets from the list. Changes support
KiCad Undo/Redo. Read [stitching usage and checks](docs/VIA-STITCHING-TESTING.md).

### Via fencing

![Current Via Fencing tab on the management switch PCB](docs/screenshots/via-fencing.png)

*Current fencing controls over the management board before a signal trace is chosen.
No fence was applied to the project.*

Type the **Signal net to fence** or use **Pick signal net in PCB**. For a specific
section, select connected track segments/arcs and click **Use selected trace**.
Type or pick the separate fence net, normally GND. Choose **Both sides**, **Left**
or **Right**, copper-to-via gap, spacing and via dimensions, then Preview and Apply.

The **RF spacing helper** estimates wavelength/10 or wavelength/20 spacing from
frequency and dielectric data. It does not calculate impedance or choose the
lateral copper gap. Inspect the reported largest gap after skipped locations.
See [RF fencing](docs/VIA-FENCING.md).

### BGA fanout

![Current BGA Fanout Auto escape preview and per-pad results in PCB Editor](docs/screenshots/bga-fanout.png)

*Live PCB Editor preview on a disposable 4 by 4 BGA test board: 16 pads escaped
to the field edge. The management board has no BGA footprint.*

![The same BGA test board after applying 16 escaped routes](docs/screenshots/bga-fanout-applied.png)

*Apply added 16 vias and 32 track segments. KiCad Undo removed them, Redo restored
them, and Remove generated fanout returned the test board to zero tracks and vias.
The removal itself also passed Undo and Redo.*

Select a BGA footprint and open **BGA Fanout**. Review detected pitch, fabrication
limits, offsets and filters. Fit guidance explains board-rule floors and nominal
inter-ball space; **Suggest settings** evaluates candidates without placing them.
Choose Dogbone, Via-in-pad, or **Auto escape to BGA edge**. The escape preview shows
which selected single-ended pads have a connected route past the pad field and which
are blocked. Apply only reviewed routes. Managed removal preserves edited routing.

Through vias are supported. Via-in-pad requires explicit fabrication confirmation.
Escape endpoints still need onward routing to their destination. Microvias, HDI
layer assignment, differential-pair escape and full-board autorouting are not implemented.
See [BGA fanout](docs/BGA-FANOUT.md).

### Trace cleanup

![Current Trace Cleanup tab showing all six copper layers on the management switch PCB](docs/screenshots/trace-cleanup.png)

*The real management board reports all six enabled copper layers and track counts
before Scan / Preview. Opening the tab does not start the full scan or change copper.*

Scan the whole board or an exact net to find duplicate tracks, overlapping
collinear tracks and native dangling endpoints. Filter findings by copper layer;
partially overlapping same-net segments can be fused into one continuous track.
Every enabled copper layer appears in the summary, including hidden and empty
layers; counts show findings and scanned track objects per layer. Preview rows
highlight in PCB Editor. Redundant copper starts checked; dangling tracks require review and start
unchecked. Cleanup is undoable. **Recheck length matching** returns to Signals and
refreshes the measurements. Partial overlaps, vias, locked and grouped copper are
preserved. See [trace cleanup](docs/TRACE-CLEANUP.md).

## Keep project metadata

Save the PCB normally and keep these sidecars alongside it when copying a project:

| File | Stores |
| --- | --- |
| `<board>.traceforge.json` | Signal-chain definitions and reviewed limits |
| `<board>.traceforge-stitching.json` | Stitching/fencing recipes and owned via UUIDs |
| `<board>.traceforge-fanout.json` | Generated fanout ownership and recipes |

Removal/regeneration preserves locked or manually altered generated items. Missing
ownership sidecars prevent managed removal. Legacy `xsignals.json` can be imported.

## Refresh, shortcuts and troubleshooting

Opening a tab or returning from PCB Editor checks for changes once and refreshes
stale data. There is no continuous board/selection polling or automatic retry loop.
F5 forces a refresh. All board operations share one worker; large previews and zone
refills can briefly occupy KiCad's GUI thread.

Default shortcuts: **Ctrl+Alt+H** highlight chain, **Ctrl+Alt+G** highlight group,
**Ctrl+Alt+C** clear, **Ctrl+Alt+W** write DRC targets, **Ctrl+Alt+E** export CSV,
**Ctrl+Alt+T** show/hide. Configure them through **Shortcuts**.

- **Plugin missing:** confirm the installer succeeded and restart PCB Editor.
- **Old panel after updating:** close TraceForge and restart PCB Editor.
- **Pick waiting:** click one item in PCB Editor; Esc cancels. Picks expire after 90 seconds.
- **No path:** check that routing is continuous and passive traversal is enabled.
- **No via candidates:** refill zones, check fence/stitch net copper on two layers,
  and review the preview's clearance/keepout rejection reasons.
- **Multiple boards open:** launch TraceForge from the intended editor's toolbar.
- **Logs:** `%APPDATA%\TraceForge\traceforge.log`.

## Scope and development

Run KiCad DRC after generated placement; custom-rule and RF validation are incomplete.
Live parallel multirouting is planned, not implemented. This release targets KiCad
10 on Windows and uses its legacy pcbnew bindings; KiCad 11 is not supported.
See [feature scope](docs/FEATURE-SCOPE.md) and [native access](docs/NATIVE-BOARD-ACCESS.md).

Development checks:

```powershell
python -m pip install -e ".[dev]"
python -m ruff check .
python -m compileall -q signal_path_analyzer native_bridge tools
python tools/build_release.py
```

The build writes a standalone ZIP and `SHA256SUMS.txt` under `dist/`, using an
explicit public-file allowlist. Tests, fixtures, logs, caches, credentials and user
boards are ignored. `tools/build_chains.py` is an optional offline chain builder;
`tools/make_icons.py` regenerates icons with Pillow installed.

See [PCM publishing steps](docs/PCM-PUBLISHING.md),
[release notes](docs/RELEASE-NOTES.md), [changelog](CHANGELOG.md) and
[MIT license](LICENSE).
