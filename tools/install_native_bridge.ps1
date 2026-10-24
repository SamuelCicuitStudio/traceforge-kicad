$ErrorActionPreference = 'Stop'
$taskSource = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\native_bridge')).Path
$taskPlugins = Join-Path $env:APPDATA 'kicad\10.0\scripting\plugins'
New-Item -ItemType Directory -Path $taskPlugins -Force | Out-Null
$taskDestination = Join-Path $taskPlugins 'traceforge_native_bridge'
if (Test-Path -LiteralPath $taskDestination) {
    $taskExisting = Get-Item -LiteralPath $taskDestination
    if ($taskExisting.LinkType -ne 'Junction' -or $taskExisting.Target[0] -ne $taskSource) {
        throw "Existing plugin path does not point to this checkout: $taskDestination"
    }
} else {
    New-Item -ItemType Junction -Path $taskDestination -Target $taskSource | Out-Null
}
Write-Output "Native helper installed at $taskDestination. Restart PCB Editor once to load it."
