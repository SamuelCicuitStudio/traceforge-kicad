param([switch]$ReplaceExisting)

$ErrorActionPreference = 'Stop'
$taskSource = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\native_bridge')).Path
$taskPlugins = Join-Path $env:APPDATA 'kicad\10.0\scripting\plugins'
New-Item -ItemType Directory -Path $taskPlugins -Force | Out-Null
$taskDestination = Join-Path $taskPlugins 'traceforge_native_bridge'
if (Test-Path -LiteralPath $taskDestination) {
    $taskExisting = Get-Item -LiteralPath $taskDestination
    if ($taskExisting.LinkType -ne 'Junction') {
        throw "Existing plugin path is not a junction. Preserve it and inspect manually: $taskDestination"
    }
    if ($taskExisting.Target[0] -ne $taskSource) {
        if (-not $ReplaceExisting) {
            throw "Another installation is linked. Close KiCad, then rerun with -ReplaceExisting to switch to this folder."
        }
        # Delete only the verified junction entry, never its target or contents.
        [System.IO.Directory]::Delete($taskDestination)
        New-Item -ItemType Junction -Path $taskDestination -Target $taskSource | Out-Null
    }
} else {
    New-Item -ItemType Junction -Path $taskDestination -Target $taskSource | Out-Null
}
Write-Output "Native helper installed at $taskDestination. Restart PCB Editor once to load it."
