# KiCad Plugin and Content Manager submission

TraceForge 0.11.0 targets KiCad 10 on Windows. Its PCM package identifier is
`com.github.samuelcicuitstudio.traceforge-kicad`; it uses the legacy `swig`
runtime and declares KiCad 10.0 as both minimum and maximum compatible version.

## Build and local verification

From the repository root, run:

```powershell
python -m ruff check .
python -m pytest -q
python tools/build_release.py
```

The build creates two distinct ZIPs under `dist/`:

- `TraceForge-0.11.0-KiCad10-Windows.zip` for the existing standalone installer.
- `TraceForge-0.11.0-KiCad10-PCM.zip` for KiCad's Plugin and Content Manager.

`dist/SHA256SUMS.txt` covers both. The PCM archive has `metadata.json` and
`resources/icon.png` at its root, plus the plugin and its runtime files under
`plugins/`. It does not need the standalone PowerShell installer or junction.

`dist/pcm-submission/com.github.samuelcicuitstudio.traceforge-kicad/` contains
the metadata and icon to copy into a fork of KiCad's
[Package Metadata repository](https://gitlab.com/kicad/addons/metadata).
The submission metadata includes the ZIP's direct GitHub Release URL, SHA-256,
compressed size and installed size. Rebuild it after **any** package change.

Local validation used the official KiCad metadata repository's v1/v2 schemas
and package validator. KiCad 10 PCM accepted **Install from file** with an
isolated KiCad configuration, installed the icon and plugin, and PCB Editor
loaded the TraceForge toolbar action. On first launch TraceForge assigned its
unused net-focus shortcut; after restarting PCB Editor the panel opened and
read the disposable test board through the native bridge. The user's KiCad
settings and project boards were not used for this installation test.

## Publish and submit

1. Review the release contents and commit/tag the tested version `v0.11.0`.
   The GitHub Actions release workflow builds both ZIPs and creates a **draft**
   release for review.
2. Publish that GitHub release so the PCM ZIP has a public direct download URL.
3. Verify the published PCM ZIP's SHA-256 matches `dist/SHA256SUMS.txt` and
   the generated submission metadata. Any changed ZIP needs new metadata.
4. Fork [KiCad Addon Metadata](https://gitlab.com/kicad/addons/metadata), create
   `packages/com.github.samuelcicuitstudio.traceforge-kicad/`, and copy in the
   generated `metadata.json` and `icon.png`.
5. Run KiCad's repository validation and test the temporary PCM repository
   produced by its CI. Submit the merge request for KiCad team review.

The official catalog lists TraceForge only after KiCad accepts the merge request
and its repository refresh completes. Until then users can install the PCM ZIP
with **Install from file**.
