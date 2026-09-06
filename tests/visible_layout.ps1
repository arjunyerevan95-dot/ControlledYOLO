param([Parameter(Mandatory=$true)][string]$MonitorPath)
$ErrorActionPreference = 'Stop'
. $MonitorPath -FunctionsOnly

# Exercise the production recognition function with captured sibling shapes.
# No windows, permissions, or input actions are created or invoked by this test.
function New-Node($name, $type) {
    return [pscustomobject]@{
        Current=[pscustomobject]@{
            Name=$name; ControlType=$type; IsOffscreen=$false
            BoundingRectangle=[pscustomobject]@{Top=100;Bottom=120}
        }
        previous=$null; next=$null
    }
}
$walker = New-Object PSObject
$walker | Add-Member ScriptMethod GetPreviousSibling { param($node) return $node.previous }
$walker | Add-Member ScriptMethod GetNextSibling { param($node) return $node.next }
$buttonType=[System.Windows.Automation.ControlType]::Button
$textType=[System.Windows.Automation.ControlType]::Text
$groupType=[System.Windows.Automation.ControlType]::Group
$scriptCommand = '$priorEditor = Get-Process -Id 21852 -ErrorAction SilentlyContinue' + "`n" + 'if ($priorEditor) { $priorEditor.WaitForExit(30000) }'
$cases = @(
    @{name='short with dropdown'; command='python check.py'; dropdown=$true; expected=$true},
    @{name='short without dropdown'; command='gh api example'; expected=$true},
    @{name='collapsed script without dropdown'; command=$scriptCommand; extra='Expand'; expected=$true},
    @{name='expanded script with dropdown'; command=$scriptCommand; extra='Collapse'; dropdown=$true; expected=$true},
    @{name='unrelated interposed control'; command=$scriptCommand; extra='Send email'; expected=$false},
    @{name='different running command'; command=$scriptCommand; mismatch=$true; expected=$false},
    @{name='missing deny'; command=$scriptCommand; noDeny=$true; expected=$false},
    @{name='offscreen command'; command=$scriptCommand; hidden=$true; expected=$false},
    @{name='multiline git push'; command=('git -C example push origin worker/test' + [Environment]::NewLine + 'if ($LASTEXITCODE -ne 0) { throw ''Push failed'' }' + [Environment]::NewLine + 'git -C example ls-remote origin'); expected=$true},
    @{name='preserve repeated whitespace in original'; command=('python -c "print(''two  spaces'')"' + [Environment]::NewLine + 'git status'); expected=$true},
    @{name='truncated running label'; command=$scriptCommand; truncated=$true; expected=$false}
)
foreach ($case in $cases) {
    $text=New-Node $case.command $textType
    $text.Current.IsOffscreen=[bool]$case.hidden
    $before=New-Node $(if ($case.noDeny) {'Question'} else {'Deny'}) $buttonType
    if ($case.extra) {
        $extra=New-Node $case.extra $buttonType
        $extra.previous=$text
        $before.previous=$extra
    } else { $before.previous=$text }
    $button=New-Node 'Allow once' $buttonType
    $button.Current.BoundingRectangle.Top=160
    $button.previous=$before
    $button.next=if($case.dropdown){New-Node 'Approval options' $buttonType}else{New-Node 'User messages' $groupType}
    # Captured Chromium UIA behavior: the running name flattens all whitespace.
    # Build independently from the production normalizer to test its contract.
    $label = 'Running ' + (($case.command -split '\s+' | Where-Object {$_}) -join ' ')
    if ($case.mismatch) { $label='Running another command' }
    if ($case.truncated) { $label=$label.Substring(0,30) }
    $running=New-Node $label $buttonType
    $window=[pscustomobject]@{running=$running}
    $window | Add-Member ScriptMethod FindAll {
        param($treeScope,$condition)
        return @($this.running | Where-Object { $_.Current.Name -ceq $condition.Value })
    }
    $actual=Get-TerminalCommand $window $button
    $expected=if($case.expected){$case.command}else{''}
    if ($actual -cne $expected) { throw ('Layout regression: ' + $case.name) }
}
Write-Output '11 layout cases passed'
