param([switch]$ReplaceExisting)

$ErrorActionPreference = 'Stop'
$taskSource = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\native_bridge')).Path
$taskConfig = if ($env:KICAD_CONFIG_HOME) {
    Join-Path $env:KICAD_CONFIG_HOME '10.0'
} else {
    Join-Path $env:APPDATA 'kicad\10.0'
}
$taskPlugins = Join-Path $taskConfig 'scripting\plugins'
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
$taskHotkeys = Join-Path $taskConfig 'user.hotkeys'
$taskLines = if (Test-Path -LiteralPath $taskHotkeys) {
    [System.IO.File]::ReadAllLines($taskHotkeys)
} else { @() }
$taskAction = 'pcbnew.EditorControl.highlightNetSelection'
$taskAssigned = @($taskLines | Where-Object { ($_ -split "`t")[0] -eq $taskAction })
$taskBinding = if ($taskAssigned.Count) { ($taskAssigned[0] -split "`t")[1] } else { '' }
if (-not $taskBinding) {
    $taskShortcut = 'Ctrl+Alt+Shift+F12'
    $taskConflict = @($taskLines | Where-Object {
        $taskFields = $_ -split "`t"
        $taskFields.Count -gt 1 -and $taskFields[1] -eq $taskShortcut
    })
    if ($taskConflict.Count) {
        Write-Warning 'Native net focus needs a Highlight Net (selected nets) shortcut in KiCad Preferences. The suggested shortcut is already in use; existing bindings were preserved.'
    } else {
        if (Test-Path -LiteralPath $taskHotkeys) {
            Copy-Item -LiteralPath $taskHotkeys -Destination ($taskHotkeys + '.traceforge.bak')
        }
        $taskLines = @($taskLines | Where-Object { ($_ -split "`t")[0] -ne $taskAction })
        $taskLines += "$taskAction`t$taskShortcut`t"
        [System.IO.File]::WriteAllLines($taskHotkeys, $taskLines,
                                      [System.Text.UTF8Encoding]::new($false))
        Write-Output "Assigned $taskShortcut to KiCad Highlight Net (selected nets) for native dimming."
    }
}
Write-Output "Native helper installed at $taskDestination. Restart PCB Editor once to load it."
