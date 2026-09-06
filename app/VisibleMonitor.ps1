param([Parameter(Mandatory=$true)][string]$ConfigPath)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$ae = [System.Windows.Automation.AutomationElement]
$scope = [System.Windows.Automation.TreeScope]
$pc = [System.Windows.Automation.PropertyCondition]
$buttonCondition = New-Object System.Windows.Automation.PropertyCondition($ae::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button)
$allow = @('allow once','approve once','approve','yes, allow','allow','accept')
$deny = @('decline','deny',"don't allow",'do not allow','cancel')
while ($true) {
    try {
        $config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $titles = @($config.titles | Where-Object { $_ -is [string] -and $_.Length -gt 0 })
        $cards = @()
        if ($titles.Count -gt 0) {
            $windows = $ae::RootElement.FindAll($scope::Children, [System.Windows.Automation.Condition]::TrueCondition)
            foreach ($window in $windows) {
                try {
                    $process = Get-Process -Id $window.Current.ProcessId -ErrorAction Stop
                    if ($process.ProcessName -notmatch '^(Codex|ChatGPT)$') { continue }
                    if ($window.Current.IsOffscreen) { continue }
                    $bounds = $window.Current.BoundingRectangle
                    $target = $null
                    foreach ($title in $titles) {
                        if ($window.Current.Name -eq $title -or $window.Current.Name -eq "$title - Codex" -or $window.Current.Name -eq "$title - ChatGPT") { $target = $title; break }
                        $condition = New-Object System.Windows.Automation.PropertyCondition($ae::NameProperty, $title, [System.Windows.Automation.PropertyConditionFlags]::IgnoreCase)
                        foreach ($element in $window.FindAll($scope::Descendants, $condition)) {
                            $r = $element.Current.BoundingRectangle
                            if (-not $element.Current.IsOffscreen -and $r.Left -ge ($bounds.Left + [Math]::Min(220,$bounds.Width*.18)) -and $r.Top -ge $bounds.Top -and $r.Top -le ($bounds.Top + [Math]::Max(160,$bounds.Height*.25))) { $target = $title; break }
                        }
                        if ($target) { break }
                    }
                    if (-not $target) { continue }
                    foreach ($button in $window.FindAll($scope::Descendants,$buttonCondition)) {
                        if ($button.Current.IsOffscreen -or -not $button.Current.IsEnabled) { continue }
                        if ($allow -notcontains $button.Current.Name.Trim().ToLowerInvariant()) { continue }
                        $parent = $button
                        $paired = $false
                        for ($level=0; $level -lt 4; $level++) {
                            $parent = [System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($parent)
                            if (-not $parent -or $parent -eq $window) { break }
                            foreach ($sibling in $parent.FindAll($scope::Descendants,$buttonCondition)) {
                                if (-not $sibling.Current.IsOffscreen -and $deny -contains $sibling.Current.Name.Trim().ToLowerInvariant()) { $paired = $true; break }
                            }
                            if ($paired) { break }
                        }
                        if ($paired) {
                            $key = "$($window.Current.ProcessId):$($button.GetRuntimeId() -join '-')"
                            $cards += @{ title=$target; key=$key }
                        }
                    }
                } catch { continue }
            }
        }
        # Observation only: this adapter never invokes controls or sends input.
        @{cards=@($cards); error=''} | ConvertTo-Json -Compress -Depth 5
    } catch {
        @{cards=@(); error='Visible-card monitor could not complete a scan.'} | ConvertTo-Json -Compress
    }
    Start-Sleep -Seconds 2
}
