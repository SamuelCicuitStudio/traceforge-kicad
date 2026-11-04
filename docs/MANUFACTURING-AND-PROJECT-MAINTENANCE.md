# Manufacturing and project maintenance

TraceForge provides a deterministic workflow for saved KiCad 10 projects. It reads
project files, runs `kicad-cli` checks, and packages board deliverables with the
bundled PCBWay or PCBPower exporters. It does not choose a stackup, infer a
manufacturer quote, approve a substitute part, or release an order. Those decisions
remain explicit inputs. The separate `pcb` skill remains available for engineering
analysis; its AI workflow is not part of the plugin.

## How to use the Manufacturing tab

Open and save a board in KiCad. TraceForge handles **that board project only** by
default and loads its profile for the selected manufacturer. For the exceptional
case of related boards, select **Include sibling boards (optional)** to switch
to a separate bundle profile. The profile is an internal file; the tab presents
named controls and a readable engineering review instead of JSON.

1. **Set up project** creates a profile only if one does not already exist. A
   optional multi-board profile has one configuration per board. Single-board
   output is created outside the source project so it cannot enter its own source
   archive. For PCBPower, existing
   board-specific `tools/export_config_rev_b.json` settings are imported, including
   BOM exclusions and CAM notes. The existing config and deliverables are not
   replaced. PCBWay choices begin unselected; only layer count is read from KiCad.
2. **Manufacturer choices** opens a labeled form for one board. Enter only values
   confirmed by a quote, order, or design record. PCBWay assembly sourcing can be
   `turnkey`, `partial_turnkey`, or `consigned`. Controlled impedance and stackup
   confirmation are separate decisions. Saving makes a backup and requires a new
   review. PCBPower can link a folder of verified CAM and ordering notes.
3. **Review project** shows each board's copper layers, schematic sheet count,
   local library state, missing manufacturer choices, output status, and the
   planned package sections. **Run KiCad checks** adds ERC, DRC, BOM, and SMD
   centroid results. Checks use saved files. External/global KiCad libraries are
   reported as unverified instead of being called missing. Fabrication archive
   checks run during export, after Gerbers exist.
4. **Generate new package** writes a new output folder. PCBWay produces schematic,
   layout, checks, fabrication, assembly, mechanical, ordering, bring-up, and
   reference sections. PCBPower produces five core sections; it also copies the
   additional numbered sections present in the linked CAM notes folder. The
   review lists the sections actually planned for each board, including linked
   PCBPower mechanical files when configured. Bundles
   contain a top-level board index and one folder per board. Package facts,
   checksums, and unresolved items determine HOLD. The export log is saved under
   `%APPDATA%/TraceForge/manufacturing-logs`.

**Review existing output** shows whether generated files are missing, edited, or
mixed with user files. **Rebuild generated package** requires confirmation and a
fresh backend check. It refuses unmanaged folders or edited generated files.
Project-local library maintenance is separate: **Find unused entries** scans only
`sym-lib-table` and `fp-lib-table`, including usages found on the PCB. Removing
reviewed entries backs up the table first. It never deletes library files or
changes global library tables.

The post-export `.traceforge-inputs.json` file lives next to the generated package.
It records source and config hashes so the next inspection can report input drift
without altering vendor package checksums. Save the board and schematic before
inspection or export; unsaved PCB Editor changes are outside this file workflow.

## Runtime and package sources

The PCM and standalone archives contain a reviewed snapshot of four deterministic
exporter scripts in `signal_path_analyzer/manufacturing_resources`. Run
`python tools/sync_manufacturing_exporters.py` when the source exporter scripts in
the sibling `pcb` repository change. The snapshot manifest contains SHA256 hashes;
TraceForge checks them before export. Runtime does not require the `pcb` repository.

KiCad's bundled Python supplies `wx` for the tab. The exporter also needs a Python
installation with `openpyxl` and a working `kicad-cli`; TraceForge detects such a
Python for the exporter process. Without it, inspection and project-local cleanup
remain available, while export reports the missing dependency. This requirement is
specific to manufacturing export, not the other TraceForge tabs.

## Release limits

An exporter HOLD, an unknown quote field, an ERC/DRC finding, or a failed package
check needs review before ordering. A passing export means the generated files
passed the implemented checks; the manufacturer must still approve CAM and assembly
details. The tab does not rewrite board design rules, calculate impedance, or apply
vendor-specific stackups.
