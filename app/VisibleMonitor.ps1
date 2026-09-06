param([string]$ConfigPath, [switch]$FunctionsOnly)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$ae = [System.Windows.Automation.AutomationElement]
$scope = [System.Windows.Automation.TreeScope]
$walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
$buttonCondition = New-Object System.Windows.Automation.PropertyCondition($ae::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button)
$allow = @('allow once','approve once','approve','yes, allow','allow','accept')
$deny = @('decline','deny',"don't allow",'do not allow','cancel')
$done = @{}

function Get-Target($window, $chats) {
    $bounds = $window.Current.BoundingRectangle
    $matches = @()
    foreach ($chat in $chats) {
        $condition = New-Object System.Windows.Automation.PropertyCondition($ae::NameProperty, $chat.title)
        foreach ($element in $window.FindAll($scope::Descendants, $condition)) {
            $r = $element.Current.BoundingRectangle
            if (-not $element.Current.IsOffscreen -and $r.Left -ge ($bounds.Left + [Math]::Min(220,$bounds.Width*.18)) -and $r.Top -ge $bounds.Top -and $r.Top -le ($bounds.Top + [Math]::Max(160,$bounds.Height*.25))) {
                $matches += $chat
                break
            }
        }
    }
    if ($matches.Count -eq 1) { return $matches[0] }
    return $null
}

function Get-TerminalCommand($window, $button) {
    # The dropdown is optional; collapsed long scripts add an Expand control.
    if ($button.Current.Name -cne 'Allow once') { return '' }
    $before = $walker.GetPreviousSibling($button)
    if (-not $before -or $before.Current.Name -cne 'Deny' -or $before.Current.ControlType -ne [System.Windows.Automation.ControlType]::Button -or $before.Current.IsOffscreen) { return '' }
    $text = $walker.GetPreviousSibling($before)
    if ($text -and $text.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button -and $text.Current.Name -cin @('Expand','Collapse')) {
        $text = $walker.GetPreviousSibling($text)
    }
    if (-not $text -or $text.Current.ControlType -ne [System.Windows.Automation.ControlType]::Text -or $text.Current.IsOffscreen) { return '' }
    $command = $text.Current.Name
    if (-not $command -or $command.Length -gt 32768) { return '' }
    $r = $text.Current.BoundingRectangle
    $b = $button.Current.BoundingRectangle
    if ($r.Top -gt $b.Top -or ($b.Top - $r.Bottom) -gt 260) { return '' }
    $condition = New-Object System.Windows.Automation.PropertyCondition($ae::NameProperty, "Running $command")
    $running = @($window.FindAll($scope::Descendants, $condition) | Where-Object {
        $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button -and -not $_.Current.IsOffscreen
    })
    if ($running.Count -ne 1) { return '' }
    return $command
}

function Test-FreshPolicy($config, $payload) {
    # Hidden helper reads SQLite and the current chat index immediately before Invoke.
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $config.runner[0]
    $info.Arguments = (@($config.runner | Select-Object -Skip 1 | ForEach-Object {
        if ($_ -match '"') { throw 'Invalid runner argument' }
        '"' + $_ + '"'
    }) -join ' ')
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardInput = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.StandardOutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $child = New-Object System.Diagnostics.Process
    $child.StartInfo = $info
    try {
        if (-not $child.Start()) { return $false }
        $bytes = [Text.Encoding]::UTF8.GetBytes(($payload | ConvertTo-Json -Compress))
        $child.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length)
        $child.StandardInput.BaseStream.Flush()
        $child.StandardInput.Close()
        if (-not $child.WaitForExit(3000)) { $child.Kill(); return $false }
        if ($child.ExitCode -ne 0) { return $false }
        return (($child.StandardOutput.ReadToEnd() | ConvertFrom-Json).allow -eq $true)
    } catch { return $false } finally { $child.Dispose() }
}

if ($FunctionsOnly) { return }
if (-not $ConfigPath) { throw 'ConfigPath is required to run the monitor.' }

while ($true) {
    try {
        $config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $cards = @()
        $approved = @()
        $seen = @{}
        $windows = $ae::RootElement.FindAll($scope::Children, [System.Windows.Automation.Condition]::TrueCondition)
        foreach ($window in $windows) {
            try {
                $process = Get-Process -Id $window.Current.ProcessId -ErrorAction Stop
                if ($process.ProcessName -notmatch '^(Codex|ChatGPT)$' -or $window.Current.IsOffscreen) { continue }
                $target = Get-Target $window @($config.chats)
                if (-not $target) { continue }
                $buttons = @($window.FindAll($scope::Descendants,$buttonCondition) | Where-Object {
                    -not $_.Current.IsOffscreen -and $_.Current.IsEnabled -and $allow -contains $_.Current.Name.Trim().ToLowerInvariant()
                })
                foreach ($button in $buttons) {
                    $parent = $button
                    $paired = $false
                    for ($level=0; $level -lt 4; $level++) {
                        $parent = $walker.GetParent($parent)
                        if (-not $parent -or $parent -eq $window) { break }
                        foreach ($sibling in $parent.FindAll($scope::Descendants,$buttonCondition)) {
                            if (-not $sibling.Current.IsOffscreen -and $deny -contains $sibling.Current.Name.Trim().ToLowerInvariant()) { $paired = $true; break }
                        }
                        if ($paired) { break }
                    }
                    if (-not $paired) { continue }
                    $command = Get-TerminalCommand $window $button
                    $hash = [System.Security.Cryptography.SHA256]::Create()
                    try { $digest = [BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($command))) } finally { $hash.Dispose() }
                    $runtime = $button.GetRuntimeId() -join '-'
                    $key = '{0}:{1}:{2}' -f $window.Current.ProcessId,$runtime,$digest
                    $card = @{session_id=$target.id; title=$target.title; key=$key}
                    $cards += $card
                    $seen[$key] = $true
                    if ($done.ContainsKey($key)) { $approved += $card; continue }
                    if (-not $command -or $buttons.Count -ne 1) { continue }
                    $payload = @{session_id=$target.id; title=$target.title; key=$key; command=$command; running_command="Running $command"}
                    if (-not (Test-FreshPolicy $config $payload)) { continue }
                    # Re-read the UI after policy lookup; never switch chats or focus windows.
                    $currentTarget = Get-Target $window @($config.chats)
                    if (-not $currentTarget -or $currentTarget.id -ne $target.id -or $button.Current.IsOffscreen -or -not $button.Current.IsEnabled) { continue }
                    if (($button.GetRuntimeId() -join '-') -ne $runtime -or (Get-TerminalCommand $window $button) -cne $command) { continue }
                    $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
                    $done[$key] = $true
                    $approved += $card
                }
            } catch { continue }
        }
        foreach ($key in @($done.Keys)) { if (-not $seen.ContainsKey($key)) { $done.Remove($key) } }
        @{cards=@($cards); approved=@($approved); error=''} | ConvertTo-Json -Compress -Depth 5
    } catch {
        @{cards=@(); approved=@(); error='Visible-card monitor could not complete a scan.'} | ConvertTo-Json -Compress
    }
    Start-Sleep -Seconds 2
}
