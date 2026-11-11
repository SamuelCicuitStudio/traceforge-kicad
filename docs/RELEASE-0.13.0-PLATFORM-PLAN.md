# TraceForge 0.13.0 manual-install release plan

The release has three independent assets: the existing KiCad 10 PCM ZIP, a Windows standalone ZIP, and a macOS standalone ZIP. Either standalone package installs the same TraceForge Python plugin source into the user's KiCad 10 scripting-plugin directory by linking the extracted folder. Users install one method per machine. The Windows and macOS standalone assets have separate installers and can be downloaded independently.

## Build and release gates

1. Keep the Windows PowerShell installer and Windows ZIP working without a Mac dependency.
2. Add a macOS shell installer that refuses to overwrite an ordinary plugin directory or an unrelated symlink, uses a user-writable KiCad scripting-plugin path, and records a Python interpreter able to import wxPython for the separate panel process.
3. Resolve the panel Python executable by platform; keep the live KiCad `pcbnew` bridge in the KiCad process. Report a clear launch error when macOS Python/wxPython is unavailable.
4. Build both standalone ZIPs plus the PCM ZIP with checksums. Validate file allowlists and archive integrity on CI. Include platform-specific installation instructions in each standalone archive.
5. Publish version 0.13.0 as a prerelease until installation and the main edit/Undo workflows have been exercised inside KiCad 10 on macOS. The macOS packaging check alone does not establish runtime compatibility.

Mac users can verify their actual Action Plugin search path in PCB Editor's Python console with `import pcbnew; print(pcbnew.PLUGIN_DIRECTORIES_SEARCH)`. The installer supports an explicit plugin-directory override when its documented default is not in that list. The macOS package does not require an Apple-signed executable because it is Python source, not a macOS application bundle.
