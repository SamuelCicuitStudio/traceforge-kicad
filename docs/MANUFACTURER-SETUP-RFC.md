# TraceForge manufacturer setup, high-speed constraints, and fabrication export

Status: product and technical plan, 2026-10-28. No implementation or manufacturer approval is implied.

## Goal and operating principle

A designer selects PCB Power, JLCPCB, or PCBWay, chooses a specific service and stackup, maps critical signals, reviews a proposed KiCad configuration, and exports an order-ready package. TraceForge must show the source and confidence of every generated value. A manufacturer's published manufacturing limits, an interface's electrical requirements, and the actual KiCad project state are three different inputs. The tool combines them only after checking that the combination is possible.

The central promise is **a reproducible, reviewable setup**, not a claim that a board has passed the fabricator's CAM review or that its impedance is certified. PCBWay explicitly frames its online impedance calculator as approximate, and PCB Power says final review occurs after an order is placed. [PCBWay calculator](https://www.pcbway.com/pcb_prototype/impedance_calculator.html); [PCB Power offer evaluation](https://www.pcbpower.com/understanding-our-offer-evaluation-process).

## Why profiles must be specific

Vendor name alone cannot determine width, clearance, stackup, or cost. PCB Power's own circuit limits change with starting copper thickness and distinguish inner from outer layers. PCBWay presents different width/space limits by copper thickness and fabrication difficulty. JLCPCB publishes distinct controlled-impedance stackups and copper-dependent capability guidance. The selected **service, board construction, copper, layer, and order option** must be part of every capability lookup. [PCB Power rigid capabilities](https://www.pcbpower.com/technology/technical-capabilities-rigid-pcb); [PCBWay capabilities](https://www.pcbway.com/capabilities.html); [JLCPCB impedance stackups](https://jlcpcb.com/impedance); [JLCPCB copper guide](https://jlcpcb.com/help/article/jlcpcb-copper-weight).

KiCad 10 already has physical stackups, per-layer single-ended and differential tuning profiles, net classes, custom DRC rules, and a CLI for fabrication exports. Global Board Setup minima are absolute floors that more specific rules cannot relax. TraceForge should configure these native features rather than maintain a second invisible rule system. [KiCad PCB Editor](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html); [KiCad CLI](https://docs.kicad.org/10.0/en/cli/cli.html).

## 1. User journey

1. **Inspect project:** Read `.kicad_pro`, `.kicad_pcb`, `.kicad_dru`, schematic/net classes when available, current stackup, routing geometry, pad/via styles, DRC state, existing tuning profiles, and KiCad version. Show missing or ambiguous data.
2. **Choose fabrication offer:** Manufacturer, service family (prototype/standard/advanced/HDI/flex/assembly as actually offered), manufacturing class, board quantity and turnaround if they affect capability, and selected vendor stackup or quote-specific build-up. Show the source page, capture date, and status of each option.
3. **Set board construction:** Layer count/order, finished thickness and tolerance, material/grade, copper for each layer, mask/finish, drill process, through/blind/buried/microvia options, via fill/cap, controlled-impedance option, test/coupon option, routing/panel preferences. Disable unsupported combinations before application.
4. **Select stackup:** Display exact physical layer sequence and electrical reference layers. Compare current board to candidate; flag layer count mismatch, layer functions, thickness sum mismatch, unapproved dielectric properties, or plated versus base copper confusion.
5. **Map signals:** Suggest candidate nets by name and pin roles, but require confirmation of endpoints, protocol variant, speed, topology, package/device delays, lane/pair/bus membership, and any datasheet targets. Create reusable signal groups and bind them to net classes and tuning profiles.
6. **Solve geometry and timing:** Find viable per-layer width/gap/reference combinations for each target. Display target, calculated estimate, process min/max, margin, length or delay budget, and confidence. If no legal combination exists, show alternatives such as another layer, stackup, copper weight, via process, or manufacturer.
7. **Preview changes:** A field-by-field diff of KiCad board stackup, project constraints, net classes, tuning profiles, custom rules, and export settings. Show existing copper that would fail newly selected rules. Allow scoped apply and reject unresolved hard conflicts.
8. **Apply safely:** Save a project-local manifest and backups, write only owned settings/rule blocks, validate syntax, reload and compare, run DRC, then offer undo. Never silently reroute existing copper or overwrite hand-authored rules.
9. **Export:** Choose bare-board fabrication and optional assembly packages. Run preflight, produce exact vendor-specific files, show an order options checklist, preview/inspect generated files, and record the selected profile/source/quote with hashes.
10. **Revalidate:** On later project changes or profile refresh, show drift, recompute derived geometry/delay, and require review before replacing applied settings.

The UI should expose a **Manufacturing Setup** page with a stepper (Offer → Stackup → Interfaces → Rules → Preflight → Export), plus a persistent board status banner. A compact matrix should compare vendor alternatives before a choice is made.

## 2. Capability catalog and provenance

### Hierarchy

`Manufacturer → Service/product family → Capability variant → Stackup SKU or quote-specific stackup → Conditional rule → Source evidence`.

A rule is conditional on applicable attributes: layer count, signal layer, inner/outer copper, base/finished copper, material, thickness, feature type, drilling class, via span, mask/finish, panelization, quantity/turnaround, impedance service, and possibly special-order approval. Each rule stores units, a limit or range, recommended design target, tolerances, notes, source URL/document revision, capture date, reviewer, and applicability predicate. Numeric values without a matching process scope must never become project constraints.

### Capability dimensions to model

| Domain | Parameters |
| --- | --- |
| Board/outline | Layer counts, min/max X/Y and area, finished thickness/tolerance, internal cutouts, slots, milling radius, castellations, edge plating, bevels, V-score, routing tabs, panel rails, minimum web, edge tolerance. |
| Copper imaging | Minimum trace width and copper spacing per layer/copper class; copper-to-edge, plane-to-plane, neck-down, acid-trap/etch limits, balancing/fill needs, min annular ring, pad-to-track and BGA escape limits. |
| Drilling/vias | Mechanical tool and finished-hole diameters, plated/non-plated status, pad and annular diameter, aspect ratio, hole-to-hole/copper, slot rules, blind/buried/microvia layer spans, laser sequence, via-in-pad/fill/cap, tenting/plugging, backdrill and residual stub limits. |
| Materials/finish | FR-4 or specified laminate, Tg, Dk/Df and frequency, copper roughness, prepreg/core part and thickness, soldermask color/thickness, legend, HASL/ENIG/other finish, controlled impedance/tolerance, impedance coupon. |
| Mask/paste/legend | Mask expansion, mask dams, exposed copper, tented vias, paste reduction, stencil thickness and openings, minimum line/text size, polarity/legend clearance. |
| Assembly | Sides, component placement process, min part/pitch/spacing, BGA/X-ray requirements, DNP/variant support, sourcing IDs, fiducials, tooling holes, panel and rail requirements, BOM/CPL conventions. |
| Ordering | Allowed file formats, naming/layer mapping, maximum upload size, order options, quote reference, exceptions and additional services, cost/lead-time class (shown as informational unless priced by a supported live source). |

Use three-valued support: `supported`, `unsupported`, `quote required/unknown`. Separate `recommended` from `absolute process minimum`, and `public/nominal` from `quote approved`. Warnings should identify the exact unresolved field and source. A quote override must include quote ID, date, attachment/reference, and approver, then supersede only matching rules. Offline catalogs should be pinned to a version; refresh proposals must be diffed, never automatically applied.

Suggested profile record:

```yaml
manufacturer: pcbway
service: <specific service identifier>
stackup_id: <published SKU or quote identifier>
profile_revision: <catalog revision>
validity: published_nominal | quote_approved
conditions: {layers: 4, outer_copper_um: 35, inner_copper_um: 18}
constraints:
  outer_trace_width_mm: {minimum: <value>, recommended: <value>, source: <url>}
  outer_spacing_mm: {minimum: <value>, recommended: <value>, source: <url>}
evidence: [{url: <url>, captured_at: <timestamp>, note: <scope>}]
```

The example intentionally has no vendor numbers; catalog ingestion must verify exact scope first.

## 3. Stackup model and board application

Represent each copper layer and dielectric layer in physical order: KiCad layer name/function, starting and finished copper thickness, plating/etch compensation where relevant, dielectric type and thickness/tolerance, Dk/Df at a stated frequency and test method, mask thickness, and final thickness/tolerance. Include supplier laminate identifiers if vendor provides them; otherwise mark material parameters as nominal. Validate the thickness sum and layer count against the chosen offer. Store the vendor's native nomenclature alongside KiCad layer names.

For each signal layer, select reference plane(s), plane net, transmission-line model (surface microstrip, embedded microstrip, stripline, asymmetric stripline, coplanar with ground, etc.), and whether soldermask is present. A plane continuity check should inspect return-path splits/voids under routed paths where geometrically possible and present visual review for complex regions. Model via spans and transitions, reference-via proximity, stubs, and backdrill if supported. A via delay calculation needs the physical stackup; changing the stackup invalidates saved timing results and requires regeneration. [KiCad PCB Editor: stackup and tuning profiles](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html).

On a new board, the wizard can set the selected layer count and stackup. On a routed board, any change to layer count, layer mapping, or thickness is a migration with a separate preview and explicit confirmation; inspect existing copper, vias, zones, tuned lengths, and newly invalid geometry. Preserve unrelated setup and avoid changes that cannot be reversed cleanly.

## 4. Impedance and geometry engine

### Inputs

Target single-ended or differential impedance and tolerance; frequency/rise-time context; signal layer and reference plane(s); exact stackup dielectric/copper/mask parameters; trace geometry (width, gap, adjacent-copper distance); manufacturing width/spacing tolerances; copper etch/plating assumptions; via transitions; and whether the fabricator owns final CAM width compensation.

### Computation and display

1. Enumerate permitted signal layers and reference configurations.
2. Use KiCad's native tuning-profile calculator for supported microstrip/stripline geometries; validate the generated width/gap against every relevant manufacturer constraint. An optional external field solver may be needed for unsupported geometry, high-frequency loss, roughness, coplanar/broadside structures, and tolerance analysis.
3. Show **estimated nominal impedance**, worst-case range if input tolerances are known, chosen width/gap, manufacturer minimum, routing margin, delay per unit length, and solver/model provenance. A missing Dk or mask parameter gives an estimated/needs-review result, not a precise answer.
4. Present multiple viable solutions ranked by design priorities: manufacturability margin, routability, layer count/cost, loss, and noise. Do not silently choose a geometry that violates a process minimum or a protocol target.
5. Generate native tuning profiles and net-class assignments, then optionally enable KiCad's tuning-profile geometry DRC severity. For any fabricator-controlled impedance, produce an impedance schedule with layer, target/tolerance, line type, nominal width/gap, coupon requirement, and confirmation status.

The displayed result must distinguish **calculated**, **vendor published nominal**, **vendor calculator estimate**, and **quote/CAM confirmed**. PCBWay's calculator states that its results are approximate and that final stackup/values need PCBWay's calculation; similar caution should apply to all unpublished shop-process variables. [PCBWay impedance calculator](https://www.pcbway.com/pcb_prototype/impedance_calculator.html).

## 5. High-speed interface templates

Templates are parameter sets and validation checklists, not universal board rules. Every template needs device/vendor datasheet references; exact target values depend on topology, generation, interface variant, PHY settings, and whether internal delay or equalization is enabled. A template can propose defaults only where the specification supports them and must keep required unknowns visible.

| Family | Objects to map | Main constraints and review questions |
| --- | --- | --- |
| USB 2.0 HS | D+/D− path, connector, protection, common-mode choke, PHY | Differential impedance, pair skew, branch/stub length, reference continuity, ESD placement, connector transition, VBUS/current and chassis return. A Microchip USB2 PHY note cites nominal 90 Ω differential and requires stackup-specific width/spacing. [Microchip AN 15.3](https://www.microchip.com/content/dam/mchp/documents/OTH/ApplicationNotes/ApplicationNotes/en562808.pdf). |
| USB SuperSpeed / USB-C | TX/RX pairs and lane orientation, AC coupling, mux, connector | Differential impedance, intra-pair skew, lane budget, via count/stubs, return vias, insertion loss and crosstalk, orientation/mux mapping. Targets and budgets must match selected generation and components. [Microchip Type-C recommendations](https://support.microchip.com/s/article/USB-Type-C-Layout-Recommendations). |
| Ethernet MDI (10/100/1000/2.5G+) | PHY-to-magnetics-to-connector pairs, center taps, isolation | Pair impedance, intra/inter-pair skew as applicable, topology and pair ordering, reference and chassis boundary, common-mode components, transformer and connector rules, differential-to-single-ended transitions. Use PHY/magnetics/connector guidance for exact targets. |
| RGMII | TX/RX data, clock, control buses between MAC/PHY | Source-synchronous setup/hold budget, internal TX/RX clock-delay settings, PCB propagation delay and group skew, layer/via transitions. RGMII is a parallel timing interface; it must not inherit Ethernet MDI differential-pair rules. TI explains that clock skew can come from PCB routing or internal delay and requires a timing budget. [TI RGMII timing report](https://www.ti.com/lit/an/snla243/snla243.pdf). |
| RMII/MII/GMII | Clocks, data, control, reference clock | Direction, clock source, per-group delay and setup/hold, topology, loading, termination. |
| SGMII/SerDes Ethernet | TX/RX lanes, AC capacitors, connector or PHY | Impedance, loss, skew, AC coupling location, stubs, via transitions, return path; device-specific channel budget. |
| PCIe / SATA / DisplayPort / HDMI | Lanes, refclks, AC caps, connectors | Protocol generation, topology, diff impedance, loss budget, pair skew, lane-to-lane budget, pin swaps/polarity support, vias/backdrill, connector/channel modeling. Exact limits from standards and endpoint datasheets. |
| MIPI CSI-2/DSI, LVDS | Clock/data pairs, lanes | D-PHY/C-PHY or LVDS variant, coupled geometry, intra/inter-lane skew, transition/termination, voltage and mode constraints. |
| DDR/LPDDR/SDRAM | DQ/DQS byte lanes, address/command, clocks, reset | Fly-by or point-to-point topology, byte-lane groups, per-bit and group flight-time windows, package delays, termination, reference and via topology. Datasheet/controller timing is mandatory. |
| SDIO/eMMC and parallel buses | Clock, command, data/strobes | Interface mode and speed, flight-time skew, clock/data relation, stubs, termination. |
| CAN/CAN FD, RS-485 | Transceiver-to-connector pair, termination | Differential impedance/termination if applicable, ESD, common-mode/chassis boundary, trace spacing and isolation; speed and cable context matter. |
| Clocks, RF, ADC/DAC, power | Oscillator and RF nets, analog front end, power rails | Single-ended impedance where required, shielding/reference, isolation, loss, return path, current/temperature, voltage drop, creepage/clearance, thermal vias. These need their own electrical models beyond a generic high-speed label. |

Each signal group stores: interface kind/revision, exact nets and P/N polarity, endpoints/pins, branch structure, selected component datasheets and revision, driver/receiver, signaling voltage, data rate/rise time/frequency, target impedance/tolerance per segment, reference layer/net, allowed layers, width/gap or solver profile, topology, minimum/maximum length or delay, pair and bus skew, package/connector delays, via count/type/span, allowable stub, separation/crosstalk targets, termination and AC-coupling placement, ESD/protection, return-path constraints, and review owner. For power, add current, temperature rise, resistance/drop, copper area, and thermal constraints.

The tool should ask for device-level facts it cannot infer. It should never translate an interface name into an arbitrary length/skew number. It can flag unknown data and generate a checklist even when no numerical rule is possible.

## 6. Rule compilation and validation

The compiler maps the chosen catalog/profile/template to KiCad's global constraints, net classes, tuning profiles, predefined sizes, and owned `.kicad_dru` section. Global minima must use the smallest permitted value anywhere on the board; more demanding per-layer or per-net restrictions become custom rules. The compiler must still check that every feature obeys its own applicable process limit. Existing project-specific design rules remain authoritative unless the user chooses a replacement in the preview. Rule precedence and conflict resolution must be visible. [KiCad Board Setup and custom rules](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html).

Rule coverage should include copper width/clearance, differential geometry, drill/annular/hole spacing, copper-edge, mask slivers, silk, courtyard/assembly, length and skew, via spans, forbidden layers/regions, creepage/voltage, and mechanically unsupported details where KiCad supports them. Maintain a **coverage matrix**: native KiCad DRC; TraceForge geometric check; manual/CAM review. Never report “passed” for a parameter that no checker evaluated. A DRC pass does not verify actual impedance, insertion loss, EMI, via stub electrical effects, fabrication yield, assembly orientation, or protocol compliance.

The preview must classify findings as `hard fail`, `requires quote/CAM approval`, `needs electrical data`, `warning`, and `ready`. Applying a profile should be idempotent and transactional: snapshot → generate → syntax/parse check → reload → DRC → commit or restore. Record hashes of input files and reject stale previews. Keep a manifest of generated rule IDs and user overrides. Undo should restore the exact pre-apply bytes where possible.

## 7. Deliverables and vendor adapters

Core fabrication export: copper/mask/silkscreen/outline Gerbers (prefer X2 when accepted), Excellon plated/non-plated drill files and maps, fabrication drawing, stackup drawing/table, controlled-impedance schedule and coupon notes, readme/order checklist, DRC/preflight report, optional IPC-D-356 netlist, and a manifest with design revision, KiCad version, profile revision, source URLs, quote ID, units, layer map, filenames, SHA-256 hashes, and unresolved exceptions. KiCad 10 CLI also supports ODB++ export; include it only when the selected vendor/service accepts it. [KiCad CLI](https://docs.kicad.org/10.0/en/cli/cli.html).

Assembly export is a separate package: BOM with MPN/sourcing IDs, DNP/variant status, side and reference designators; centroid/CPL with origin, units, rotation conventions and side; top/bottom assembly drawings, paste/stencil data, fiducials and panel notes as required. Validate one-to-one BOM/CPL designator matching, no unintended DNPs, and placement orientation visually. JLCPCB explicitly asks for Gerber, BOM, and CPL for PCB assembly and documents layer/file naming. [JLCPCB assembly FAQ](https://jlcpcb.com/help/article/pcb-assembly-faqs); [JLCPCB Gerber preparation](https://jlcpcb.com/help/article/gerber-files-preparation); [JLCPCB BOM format](https://jlcpcb.com/help/article/bill-of-materials-for-pcb-assembly).

Each vendor adapter defines its accepted outputs, naming, layer order, origin, unit conventions, zip structure, required order options, assembly schema, exception notes, and preflight checks. It must be versioned separately from capability data. Export into a clean staging directory from a saved project snapshot, inspect for stale or extra files, then build separate `fabrication.zip` and `assembly.zip` when needed. A manufacturer upload/quote is an external verification step; the package should contain a human-readable checklist to compare the upload preview and order selections with the chosen TraceForge profile.

## 8. Architecture in this repository

Current TraceForge already reads KiCad 10 tuning profiles/stackup data (`signal_path_analyzer/profiles.py`), detects signal paths and writes a marked `.kicad_dru` section (`chains.py`, `session.py`), offers a wx panel (`hub_ui.py`), and accesses live board geometry through `native_bridge/server.py`. It currently exports signal-path CSV, but not a manufacturer fabrication package. The new feature should reuse these capabilities without mixing manufacturer catalog data into signal analysis.

Suggested package boundaries:

```text
manufacturing/
  catalog/          # versioned, sourced vendor capability profiles
  model.py          # normalized board/stackup/offer/constraint models
  project_reader.py # KiCad project and board state, no mutation
  feasibility.py    # conditional capability matching and conflict graph
  geometry.py       # impedance/timing estimates and solver adapters
  interfaces/       # electrical templates and explicit net binding
  compiler.py       # KiCad settings, tuning profiles, custom DRC diff
  apply.py          # backup, transaction, syntax/DRC checks, undo
  preflight.py      # rule coverage, design and file consistency
  exporters/        # core KiCad CLI and vendor-specific adapters
  manifest.py       # provenance, hashes, quote and review state
```

Keep catalog profiles as reviewed data files with schemas; avoid screen scraping at apply time. The UI calls a read-only `analyze()` then `preview()`; only `apply()` or `export()` mutates/writes. The native bridge should expose only missing board data and visualization actions. The exporter should use the installed KiCad version's supported CLI commands and work from a saved snapshot; it should not launch or reconfigure the KiCad GUI.

## 9. Roadmap and acceptance gates

| Phase | Scope | Exit gate |
| --- | --- | --- |
| 0. Discovery | Confirm KiCad 10 file/API access, rule precedence, current project mutation paths; inventory official vendor service/stackup/export docs and licensing. | Source matrix with date/scope and no guessed hard limits. |
| 1. Read-only advisor | Detect board construction and existing constraints; compare to one selected process; show gaps and source confidence. | Fixtures for 2/4/6/8-layer boards; no project bytes changed. |
| 2. Rule writer | Preview/apply/undo manufacturer minima and custom DRC rules, preserve user rules. | Idempotence, rollback, DRC syntax, negative conflict fixtures. |
| 3. Stackup/impedance | Apply exact published stackup, create KiCad tuning profiles, calculate feasible geometry/delay, print impedance schedule. | Compare against published vendor calculator examples and KiCad results; clearly label estimates and quote-dependent values. |
| 4. Critical interfaces | USB2, Ethernet MDI, RGMII first; then USB SuperSpeed, SGMII, DDR and others. | Datasheet-backed templates, net mapping review, tests showing RGMII never gets MDI pair rules and internal delay is accounted for. |
| 5. Deliverables | Core Gerber/drill/fab drawing/manifest, then three vendor adapters and optional assembly package. | Golden file-set tests, archive/layer/drill inspection, accepted naming/schema against current official vendor docs. |
| 6. Catalog maintenance | Quote overrides, profile refresh, provenance diffs, expiry notifications. | Old projects remain reproducible; refreshed source never changes board settings without review. |

Initial public release should support **rigid FR-4, published 2/4/6-layer offers**, standard through-hole vias, bare-board exports, and USB2 + Ethernet MDI + RGMII templates. Expand to HDI/flex/RF and assembly only after corresponding catalog and verification coverage is real. This is a proposed sequencing decision, not a limitation in the long-term model.

## 10. Verification matrix

Test clean/new and already-routed boards; each supported layer count and vendor; copper-weight-dependent limits; nominal versus quote-approved profiles; impossible impedance target; missing Dk/frequency; mask on/off; asymmetric stackup; layer-change invalidation; existing hand-written custom rules; stale preview; backup/undo; wrong KiCad version; PTH/NPTH/slot drill distinction; top/bottom assembly and DNP; pair polarity/net mapping; via/stub and reference-plane warnings; and export archive contents. Compare calculated impedance to vendor examples and flag deviations, but do not use a tiny tolerance as proof of physical production accuracy.

Release criteria: source traceability for every enforced number; no silent fabrication assumptions; successful parse/DRC of generated settings; full rollback after failure; an explicit coverage report; verified vendor file-set and order checklist; and an end-to-end demonstration on a representative board with a reviewer checking the resulting KiCad setup and export archive.

## Open product decisions

1. Should the first implementation target KiCad 10 only (the current TraceForge code reads KiCad 10 tuning profiles), or also support KiCad 9 with a reduced feature set?
2. Which actual published stackup SKUs and service tiers at PCB Power, JLCPCB, and PCBWay are most important to the first release? A single manufacturer label is too broad.
3. Should quote-approved stackups be entered manually first, or imported from a specific vendor document format?
4. Should an export be permitted with `quote required` findings if the archive clearly records exceptions, or should these block the order package?
5. Which board from the existing projects should be the first end-to-end validation case, and who will provide its PHY/controller timing datasheets and selected fabrication quote?
