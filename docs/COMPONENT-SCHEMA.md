# Shared component information

The canonical contract is `../pcb/assets/component-schema.json` in the PCB skill
repository. `python tools/sync_component_schema.py` copies it into TraceForge and
TraceForgerouter schematic-authoring. `--check` verifies byte equality. The packaged
copy supports offline use. Current schema version: 2.

| Meaning | Canonical fields |
|---|---|
| Physical component identity | Manufacturer, MPN |
| Primary purchasing source | Supplier, Supplier Part #, Supplier URL |
| Supplier-specific order codes | LCSC Part #, DigiKey Part #, Mouser Part #, element14 Part # |
| Engineering data | Value, Package, Footprint, Datasheet, Description and category-specific ratings |

A manufacturer number and a distributor SKU are different facts. LCSC is optional.
Farnell/Newark map to element14. Legacy `PART NUMBER`, `MANUFACTURERPART`, `MP`,
`MF`, Digi-Key part numbers and `Supplier 1` fields are recognized by the shared
alias table. One unambiguous vendor-specific code can establish the primary supplier.
Existing generic passive graphics remain shared; purchasing information belongs to
exact parts and placed references, never the shared generic resistor or capacitor.

## Assign exact MPN matches

Manufacturing > BOM Cost > **Assign exact MPN matches** works for every component
category, including inductors, ferrite beads, ICs and connectors. It never guesses
an MPN from a nominal value. Select **Project supplier information** to normalize
saved supplier identities, or **LCSC** to perform live exact-MPN/manufacturer lookup.
DigiKey, Mouser and element14 choices use saved project data; they do not implement
credential-free live catalog access or quote availability. Saved stock/prices are
not presented as live observations. Other saved suppliers remain valid identities.

Review the checked proposals, then **Assign checked identities**. Existing value,
footprint, symbol, wires, placement and routing stay fixed. Ambiguous searches and
missing manufacturer/order codes remain unchanged. Updates use the existing scoped
transaction, backup, rollback and native PCB undo path, and refresh affected BOM rows.
Close the project's Schematic Editor before writing its saved fields.

BOM Cost currently prices LCSC retail only. Assigned non-LCSC records show **Other
supplier**, not Unassigned, and remain outside the LCSC subtotal. This is not a
multi-distributor quote total. Passive-equivalent optimization stays a separate action.

Imported KiCad quoted text may contain literal tabs/newlines. The parser accepts
these native strings; new metadata writes retain Unicode and canonical field names.

Assignment lock checking follows only the selected root schematic and its actual child sheets. Locks in delivery copies, backups and staging folders do not block this project. A failed batch can be retried after fixing its reported cause.

Local KiCad 10 locks contain hostname/user but no PID. A lock on this workstation is treated as stale only when a successful Windows process enumeration confirms no eeschema.exe exists. Unknown process state, remote ownership and malformed locks remain blocking. Lock files are retained, not deleted.

Assignment expands to every occurrence sharing the canonical exact MPN, manufacturer, footprint and nominal value, across hierarchy and supplier-assignment states. Unassigned exact parts group in the BOM instead of one row per reference. The assignment bar lists the full affected references. Generic value/symbol alone never establishes equivalence; DNP/excluded peers receive metadata updates too, while their flags stay unchanged and they remain excluded from fitted quantities and cost.

Replacement preparation cooperatively checks cancellation during KiCad tokenization, recursive parsing and sheet planning. The lock check reuses the parsed hierarchy rather than parsing it again. Cancellation before commit writes nothing; an atomic commit finishes or rolls back before reporting completion.
