param(
    [string]$SelectTitle = 'Bootstrap ControlPlane Console',
    [ValidateSet('notify','auto_local')][string]$Mode = 'auto_local',
    [switch]$NoStartup,
    [switch]$NoLaunch
)
$ErrorActionPreference = 'Stop'
$source = $PSScriptRoot
$destination = Join-Path $env:LOCALAPPDATA 'ControlledYOLO\app'
$state = Join-Path $env:LOCALAPPDATA 'ControlledYOLO\state'
$pythonPath = $null
$bundled = Test-Path -LiteralPath (Join-Path $source 'ControlledYOLO.exe')
if (-not $bundled) {
    foreach ($candidate in @('py.exe','python.exe','python3.exe')) {
        $resolved = Get-Command $candidate -ErrorAction SilentlyContinue
        if (-not $resolved) { continue }
        $probe = "import sys,tkinter; assert sys.version_info >= (3,10); print(sys.executable)"
        try {
            if ($candidate -eq 'py.exe') { $answer = & $resolved.Source -3 -c $probe 2>$null }
            else { $answer = & $resolved.Source -c $probe 2>$null }
            if ($LASTEXITCODE -eq 0 -and $answer) { $pythonPath = ($answer | Select-Object -Last 1).Trim(); break }
        } catch { continue }
    }
    if (-not $pythonPath) {
        $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
        if (-not $winget) { throw 'Python 3.10+ with tkinter is required for the source package. Install Python from python.org, then run Install.cmd again.' }
        Write-Host 'Installing Python for this Windows user...'
        & $winget.Source install --id Python.Python.3.12 --exact --scope user --accept-package-agreements --accept-source-agreements --silent
        if ($LASTEXITCODE -ne 0) { throw 'Python installation did not finish. Install Python 3.10+ from python.org and rerun Install.cmd.' }
        $installed = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
        if (-not (Test-Path -LiteralPath $installed)) { throw 'Python was installed but its executable could not be located. Reopen this installer in a new terminal.' }
        $pythonPath = $installed
        & $pythonPath -c 'import tkinter,sys; assert sys.version_info >= (3,10)'
        if ($LASTEXITCODE -ne 0) { throw 'Python tkinter verification failed.' }
    }
}
New-Item -ItemType Directory -Path $destination -Force | Out-Null
New-Item -ItemType Directory -Path $state -Force | Out-Null
# Graceful exit only, through the existing app's own state channel.
if (Test-Path -LiteralPath (Join-Path $destination 'app\main.py')) {
    $oldPythonFile = Join-Path $destination 'python-path.txt'
    if (Test-Path -LiteralPath $oldPythonFile) {
        $oldPython = (Get-Content -LiteralPath $oldPythonFile -Raw).Trim()
        & $oldPython (Join-Path $destination 'app\main.py') --request-exit
        if ($LASTEXITCODE -ne 0) { throw 'Close ControlledYOLO before updating.' }
    }
}
if (Test-Path -LiteralPath (Join-Path $destination 'ControlledYOLO.exe')) {
    & (Join-Path $destination 'ControlledYOLO.exe') --request-exit
    if ($LASTEXITCODE -ne 0) { throw 'Close ControlledYOLO before updating.' }
}
foreach ($item in @('app','_internal','Launch.ps1','Uninstall.ps1','Uninstall.cmd','README.md','docs','downloads')) {
    $from = Join-Path $source $item
    if (Test-Path -LiteralPath $from) { Copy-Item -LiteralPath $from -Destination $destination -Recurse -Force }
}
if ($bundled) {
    Copy-Item -LiteralPath (Join-Path $source 'ControlledYOLO.exe') -Destination $destination -Force
    $runner = Join-Path $destination 'ControlledYOLO.exe'
    $prefix = @()
} else {
    # A previous bundled executable must not shadow this installed source version.
    $previousExe = Join-Path $destination 'ControlledYOLO.exe'
    if (Test-Path -LiteralPath $previousExe) { Move-Item -LiteralPath $previousExe -Destination ($previousExe + '.previous') -Force }
    Set-Content -LiteralPath (Join-Path $destination 'python-path.txt') -Value $pythonPath -Encoding UTF8
    $runner = $pythonPath
    $prefix = @((Join-Path $destination 'app\main.py'))
}
& $runner @prefix --install-hooks
if ($LASTEXITCODE -ne 0) { throw 'Hook setup failed. Existing approvals have not been changed; see the error above.' }
if ($SelectTitle) {
    & $runner @prefix --configure-title $SelectTitle --mode $Mode
    if ($LASTEXITCODE -ne 0) { throw 'Could not configure the requested chat.' }
}
$wsh = New-Object -ComObject WScript.Shell
$shortcutPaths = @((Join-Path ([Environment]::GetFolderPath('Desktop')) 'ControlledYOLO.lnk'))
if (-not $NoStartup) { $shortcutPaths += Join-Path ([Environment]::GetFolderPath('Startup')) 'ControlledYOLO.lnk' }
foreach ($path in $shortcutPaths) {
    $shortcut = $wsh.CreateShortcut($path)
    $shortcut.TargetPath = Join-Path $PSHOME 'powershell.exe'
    $minimized = if ($path -like '*Startup*') { ' -Minimized' } else { '' }
    $shortcut.Arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + (Join-Path $destination 'Launch.ps1') + '"' + $minimized
    $shortcut.WorkingDirectory = $destination
    $shortcut.WindowStyle = 7
    $shortcut.Description = 'Selected-chat approvals and persistent attention alerts'
    $shortcut.IconLocation = (Join-Path $destination 'app\icons\running.ico') + ',0'
    $shortcut.Save()
}
Write-Host 'ControlledYOLO 2 installed. Open /hooks in Codex and review the new hook definitions once.'
Write-Host 'The tray app shows whether native events have actually been observed. Choose additional chats in its Chats tab.'
if (-not $NoLaunch) { & (Join-Path $destination 'Launch.ps1') }
