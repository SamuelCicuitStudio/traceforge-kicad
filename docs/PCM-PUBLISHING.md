# Windows PCM release and KiCad catalog

TraceForge 0.13.3 is a **Windows-only, KiCad 10** PCM package. The GitHub
release is stable; it does not include a macOS asset. The PCM identifier is
`com.github.samuelcicuitstudio.traceforge-kicad` and the package uses KiCad's
legacy `swig` runtime. Users install the ZIP with **Plugin and Content Manager
> Install from file**; a GitHub release does not itself add the package to
KiCad's official Repository tab.

## Build and verify

```powershell
python -m ruff check .
python -m pytest -q
python tools/build_pcm.py
```

The release asset is `dist/TraceForge-0.13.3-KiCad10-PCM.zip`. Its root holds
`metadata.json` and `resources/icon.png`; the action and runtime files are under
`plugins/`. The release workflow builds the Windows PCM on a Windows runner,
checks tests and package integrity, then publishes only that ZIP and its
SHA-256 checksum. It requires the matching tag in `pcm/publish.json`.

## Catalog submission

The [KiCad Addon Metadata repository](https://gitlab.com/kicad/addons/metadata)
is a separate review process. The older TraceForge 0.12.10 merge request does
not publish 0.13.3 and should not be merged as an update to this release.
Any future catalog submission must use the published 0.13.3 ZIP's exact URL,
SHA-256 and sizes, then pass KiCad's metadata validation. Until accepted,
**Install from file** remains the documented installation path.
