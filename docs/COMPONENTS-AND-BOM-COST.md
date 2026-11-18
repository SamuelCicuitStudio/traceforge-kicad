# Components and BOM Cost

## Navigation

TraceForge groups its tools into six workspaces. Each selector keeps the tool alive when switching, so settings and previews remain available.

| Workspace | Tools |
| --- | --- |
| Signals | Signal paths / timing / routing geometry; Unrouted navigator |
| Layout | Layout Clone; PCB Rotation; References / Auto Text |
| Vias | Stitching; fencing; array; size manager; via-in-pad inspector |
| Routing | Cleanup; teardrops; rounded corners; BGA fanout |
| Components | Search / details; assets / import; project library |
| Manufacturing | Manufacturing packages / stackup; BOM Cost |

View opens the shared visualization window. About opens runtime/help information. Existing numeric launcher messages remain accepted; new launchers use stable tool IDs.

## Find and add a component

1. Open a saved PCB and select Components. The project folder and its registered local libraries determine the destination. Runtime settings are per-user, separate from project files.
2. Enter an exact LCSC C-number to fetch identity, retail price tiers and stock directly. Keyword/MPN searches use the Component Research browser service. Full supplier pages open in its companion window; supplier challenges stay there.
3. Under Assets, verify the exact manufacturer, MPN, package and ratings. **Locate existing exact part** selects a matching project-catalog entry. Choose the project's destination libraries once when ambiguous.
4. Standard passives reuse compatible generic assets. A uniquely named small symbol is suggested when available. Select the actual compatible footprint; package text alone cannot prove pad geometry. Ratings and MPN stay in the exact-part catalog rather than overwriting shared symbol defaults.
5. Stage the needed symbol, footprint and/or STEP. Downloads remain under that operation's review folder, separate from the active libraries. A failed STEP download does not discard a successful symbol/footprint acquisition.
6. Preview the CAD, check pin/pad correspondence and package geometry, and build the change plan. A STEP stays an unlinked candidate unless its geometry/orientation is checked and its XYZ transform entered.
7. Add the reviewed plan to the project library. The result returns qualified symbol/footprint IDs. Refresh the library list in KiCad as needed before placing the part.

Library-only installation does not place components, rewrite open schematics, update existing PCB footprints or move routing. Existing customized definitions and model links are preserved when a different candidate conflicts. New footprint assets show the native reference on F.SilkS; values and duplicate reference text are hidden while polarity markings remain.

The catalog is `libraries/traceforge-parts.json`; saved destinations are `libraries/traceforge-library.json`. Installed model links use `${KIPRJMOD}`. Downloads retain identity, acquisition and asset-rights metadata. CAD originates from the **JLCEDA/EasyEDA Official Library**: [JLCEDA](https://lceda.cn/) / [EasyEDA](https://easyeda.com/).

## External runtime setup

The normal PCM plugin remains usable without the research/CAD helpers. Components → Runtime settings accepts:

- Component Research folder containing `desktop/tool.cjs`, plus the Node executable.
- PCB helper scripts folder containing `download_easyeda_cad.py` and `download_easyeda_step.py`.
- An external Python executable with the CAD converter available.

These paths are saved in `%APPDATA%/TraceForge/components.json`. Do not install converter dependencies into KiCad's Python. The converter is an external AGPL-3.0 dependency; it and Electron/node_modules are not bundled into the MIT PCM archive. Runtime readiness reports missing capabilities. Live supplier access can be blocked; unavailable data is shown as unavailable.

## Update selected placed footprints

Components → Project library → **Preview / update selected PCB footprints** is a separate board-edit operation. Select the footprints in PCB Editor, preview, inspect the numbered pad envelopes and result table, then apply the reviewed updates.

Each selected reference reloads its currently assigned footprint from a registered project-local library. It preserves the footprint UUID and schematic path, anchor, side, rotation, group membership, existing field content/text placement, pad nets and track/via geometry. Existing placed 3D models stay by default; the explicit library-model option previews using the library's model definitions instead. Zone fills are rebuilt after applying.

Locked parts, missing local assets, different electrical pad numbers, lost routed copper contacts and newly introduced foreign-net copper collisions block the operation. Changing the board, selection, model policy or source library invalidates the preview. Native KiCad Undo uses the same board-edit transaction as the other TraceForge editing tools.

The comparison plots pad envelopes, not a complete DRC or package certification. Run DRC after a geometry update. This operation does not change the component's MPN/value, assign another footprint ID, or update schematic instances.

## BOM Cost

Manufacturing → BOM Cost defaults to the **saved root schematic**, including hierarchical instances and components not yet placed on the PCB. Unsaved schematic edits are excluded. Live PCB fields are a separate selectable scope, useful for placement-only reviews but potentially incomplete as a project BOM.

Set board quantity and spare percentage, then calculate. Exact LCSC codes are grouped before applying quantity tiers. The order quantity includes rounded spares, minimum order quantity and order multiples. DNP and BOM-excluded references are omitted.

Each line shows identity, references, fitted/order quantities, USD unit/line price, stock and observation time. Missing codes/prices and conflicting MPNs remain unpriced. A partial known-price subtotal is never labelled a complete BOM total. Cached observations retain their original timestamp; select live refresh to request new prices. Export CSV/JSON for review.

This is LCSC retail parts cost. Fabrication, assembly, shipping, taxes and fees are outside the total. LCSC stock is not JLCPCB assembly inventory.

## Recovery and cancellation

Installation rechecks file hashes against the preview, backs up original bytes and writes an operation journal under `review/component-imports/<operation>/journal.json`. Filesystem library changes do not use KiCad Undo.

Cancellation stops acquisition workers; a library transaction already writing finishes its recovery-safe operation. Failed writes restore original files. For interrupted transactions, run `component_library.recover(journal_path)` from an external Python session using this package. Recovery restores only unchanged import-written content and reports `recovery_conflict` when later edits must be kept. An installed transaction is not treated as interrupted.
