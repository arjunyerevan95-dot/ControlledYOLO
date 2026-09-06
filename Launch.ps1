param([switch]$Minimized)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$arguments = @()
if (Test-Path -LiteralPath (Join-Path $root 'ControlledYOLO.exe')) {
    $executable = Join-Path $root 'ControlledYOLO.exe'
} else {
    $executable = (Get-Content -LiteralPath (Join-Path $root 'python-path.txt') -Raw).Trim()
    $arguments = @('"' + (Join-Path $root 'app\main.py') + '"')
}
if ($Minimized) { $arguments += '--minimized' }
if ($arguments.Count) {
    Start-Process -FilePath $executable -ArgumentList $arguments -WindowStyle Hidden
} else {
    Start-Process -FilePath $executable -WindowStyle Hidden
}

