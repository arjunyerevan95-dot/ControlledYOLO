$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
if (Test-Path -LiteralPath (Join-Path $root 'ControlledYOLO.exe')) {
    $runner = Join-Path $root 'ControlledYOLO.exe'
    $prefix = @()
} else {
    $runner = (Get-Content -LiteralPath (Join-Path $root 'python-path.txt') -Raw).Trim()
    $prefix = @((Join-Path $root 'app\main.py'))
}
& $runner @prefix --request-exit
if ($LASTEXITCODE -ne 0) { throw 'Close ControlledYOLO and retry uninstall.' }
& $runner @prefix --remove-hooks
if ($LASTEXITCODE -ne 0) { throw 'Hook removal failed. No app files were deleted.' }
foreach ($folder in @([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Startup'))) {
    $path = Join-Path $folder 'ControlledYOLO.lnk'
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path }
}
Write-Host 'ControlledYOLO stopped and removed from startup. Its hooks were removed; other hooks were preserved.'
Write-Host 'App files and local settings are retained. You may delete the ControlledYOLO folder in LocalAppData when ready.'

