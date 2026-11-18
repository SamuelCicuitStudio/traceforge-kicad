# Components and workspace verification

Acceptance record for the local 0.17.0 testing build, 18 November 2026. The final installation receipt and archive checksum are recorded in `build/installed-components-verification.json`.

## Verified

- Full Python test suite: 314 passing tests.
- Six-workspace native wx construction and stable-ID navigation checked with KiCad 10 Python.
- Exact LCSC retail lookup: C2040 resolves to RP2040 with manufacturer, stock, USD quantity tiers and observation time.
- Exact EasyEDA acquisition: C702221 / TPS386000RGPR stages symbol, footprint and STEP independently of active libraries.
- Fixture installation creates qualified `Fixture:TPS386000RGPR` symbol/footprint IDs and project library tables.
- KiCad CLI exports the installed fixture symbol to SVG.
- KiCad native footprint loader accepts the installed fixture footprint and finds 21 pads.
- STEP bytes are preserved, including non-UTF-8 bytes in exchange-file strings; transaction journals encode binary payloads explicitly.
- Generic passive tests preserve shared symbol defaults across two exact MPN records.
- Stale preview hashes reject installation. Conflicting footprint definitions remain untouched.
- Interrupted-import recovery preserves later user edits and reports conflicts rather than overwriting them.
- BOM arithmetic tests cover aggregated quantity tiers, DNP exclusion, MOQ/multiples, spares, stock shortages, conflicting MPNs and incomplete price totals.
- Missing-helper behavior, pre-launch cancellation and owned-child timeout termination pass.
- Actual management, SIM and front project tables resolve their primary local libraries; auxiliary capture libraries remain available.
- Fresh saved netlist extraction counts 1,228 management, 713 SIM and 211 front-board components; no schematic/PCB changes are made.
- Local 0.17.0 testing PCM builds and archive verification passes. Previous installed plugin was backed up, then 109 plugin files were checked byte-for-byte against the archive.
- Installed-package imports report the new native build identity and all configured external helpers ready. Installed native wx smoke passes all stable IDs, legacy launchers and retained field state.
- Existing Layout Clone UI, Unrouted UI, native Auto Text and quick-access checks pass.
- Actual project-library copies preserve TPS25940ARVCR, TPS3702_Window, both XC6SLX16 definitions, generic R/C/L/bead/LED symbols and NANO_SIM_7P_H1.37. Source-library hashes remain unchanged.
- Actual Coilcraft inductor, side-view LED and push-push SIM footprint copies reject same-name candidates with changed pad positions; customized originals and source files remain unchanged.
- Checked-model mapping tests verify project-relative links, explicit transforms and preservation of an existing model link.
- Compact 820×560 dark-theme screenshots inspected for Components search/assets and BOM Cost; dark contrast corrected and the real application's dark-mode initialization included in the UI verifier.
- Companion browser's 19 tests pass after fixing continuous-idle navigation settling. Its advertised LCSC capability remains generic/unverified; exact C-number retail and EasyEDA acquisition have separate successful live checks.
- Updated default browser helper passes live exact identity for C702221 / TPS386000RGPR after fixing explicit-MPN extraction. Companion tests now total 21 passing tests. A direct LCSC PDF download passes content validation and SHA256 recording (1,616,802 bytes); the product-page document link returning HTML is correctly rejected.
- New paired CAD imports compare electrical symbol pin numbers against footprint pad numbers and reject mismatches; procurement aliases preserve existing field names. Import records include reuse flags and acquisition-time asset hashes.
- CAD failure does not block an independently requested STEP download. The native LCSC datasheet action resolves the exact part's direct PDF URL when the page provides only a landing link. Helper responses enforce schema 1.0, and readiness checks its capability handshake.
- Each import emits `plan.json`, `validation.json`, `source.json` and the recovery journal before active-library writes.
- Symbol-only then footprint-only installation enriches the same exact part record, preserves the existing symbol and leaves unresolved converter footprint IDs blank.
- Exact-part lookup also searches registered project symbols; the actual management TPS25940ARVCR resolves to its existing customized symbol and assigned footprint. Multiple exact definitions are reported as ambiguous.
- Selected-reference updates have a dedicated native preview/apply and pad-envelope comparison. In-memory KiCad tests cover rotations and both sides, preserved footprint UUID/path, MPN/value/text, pad nets, group membership, existing models and track geometry; locked footprints, lost copper contacts, stale placement and changed library files are rejected.
- Selected-update wx tests cover read-only comparison painting, explicit Apply, native token forwarding and option invalidation. Apply calls the shared native undoable transaction and refills zones. These tests exercise its edit callback in memory; they do not claim an automated live-editor Undo-key test.

## Final acceptance matrix

| Plan stage | Evidence |
| --- | --- |
| Navigation | `tools/verify_workspaces_ui.py`: all six workspaces, stable IDs, numeric legacy routing, persistent controls, compact-window construction; existing UI regression checks |
| Project resolver | Three actual project tables; unique primary-library selection, ambiguity and scope tests in `tests/test_component_library.py` |
| Browser adapter | Schema/capability handshake, isolated and updated-default-helper live LCSC exact identity, direct retail observations and validated PDF acquisition; 21 companion tests |
| CAD import | Exact C702221 staging, fresh transactional installation with 21/21 pin/pad comparison, native footprint load and symbol SVG export; symbol-only/footprint-only and stale/conflict tests |
| Passive / 3D | Shared R/C definitions stay unchanged, existing small L/bead/LED/SIM assets preserved, explicit checked-transform relative links, binary STEP retention and no existing-model replacement |
| Existing assets | `tools/verify_component_projects.py`, `tools/verify_component_update_native.py` and `tools/verify_component_update_ui.py`; customized asset preservation, native selected-reference workflow, contact and stale guards, rollback tests |
| Package | Local 0.17.0 testing archive validation and installed-file verification; external helpers remain separate, runtime absence/cancellation tested; usage guide documents boundaries |

Final package SHA256 and installed-file counts are recorded in `build/installed-components-verification.json` after the last rebuild. Public release authorization `pcm/publish.json` remains on 0.16.5; no release is published by this work.

No board schematic, PCB placement or routing was changed by these checks. Live supplier quantities/prices are observations, not fixed procurement guarantees. The normal BOM Cost scope is the saved root schematic; live PCB-only scope is explicitly separate.
