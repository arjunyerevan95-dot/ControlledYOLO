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
        previous=$null; next=$null; parent=$null
    }
}
$walker = New-Object PSObject
$walker | Add-Member ScriptMethod GetPreviousSibling { param($node) return $node.previous }
$walker | Add-Member ScriptMethod GetNextSibling { param($node) return $node.next }
$walker | Add-Member ScriptMethod GetParent { param($node) return $node.parent }
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
    @{name='truncated running label'; command=$scriptCommand; truncated=$true; expected=$false},
    @{name='quoted executable call'; command="& 'C:\Tools\python.exe' 'Board_Work/download_images.py' review_images.json"; expected=$true},
    @{name='running label outside card scope'; command=$scriptCommand; detached=$true; expected=$false},
    @{name='matching transcript row scrolled offscreen'; command="& 'C:\Tools\python.exe' 'Board_Work/download_images.py' review_images3.json"; hiddenRunning=$true; expected=$true},
    @{name='different offscreen running label'; command=$scriptCommand; hiddenRunning=$true; mismatch=$true; expected=$false},
    @{name='ambiguous matching running labels'; command=$scriptCommand; duplicateRunning=$true; expected=$false}
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
    $running.Current.IsOffscreen=[bool]$case.hiddenRunning
    $window=[pscustomobject]@{running=@($running)}
    if ($case.duplicateRunning) { $window.running+=New-Node $label $buttonType }
    $window | Add-Member ScriptMethod FindAll {
        param($treeScope,$condition)
        return @($this.running | Where-Object { $_.Current.Name -ceq $condition.Value })
    }
    $button.parent=$window
    if ($case.detached) {
        $button.parent=New-Object PSObject
        $button.parent | Add-Member ScriptMethod FindAll { param($treeScope,$condition) return @() }
    }
    $actual=Get-TerminalCommand $window $button
    $expected=if($case.expected){$case.command}else{''}
    if ($actual -cne $expected) { throw ('Layout regression: ' + $case.name) }
}
Write-Output '16 layout cases passed'

function New-HeaderParent($nodes) {
    $parent=[pscustomobject]@{nodes=$nodes}
    $parent | Add-Member ScriptMethod FindAll { param($treeScope,$condition) return @($this.nodes) }
    return $parent
}
function New-TestHeader($name,$left,$valid) {
    $node=New-Node $name $buttonType
    $node.Current.BoundingRectangle=[pscustomobject]@{Top=45;Bottom=70;Left=$left}
    $siblings=@($node)
    if($valid){$siblings+=New-Node 'Chat actions' $buttonType; $siblings+=New-Node 'Share' $buttonType}
    $node.parent=New-HeaderParent $siblings
    return $node
}
$chats=@([pscustomobject]@{id='one';title='Worker 1'},[pscustomobject]@{id='two';title='Worker 2'})
$cases=@(
    @{nodes=@((New-TestHeader 'Worker 1' 30 $true)); expected='one'},
    @{nodes=@((New-TestHeader 'Worker 1' 294 $true),(New-TestHeader 'Worker 1' 7 $false)); expected='one'},
    @{nodes=@((New-TestHeader 'Worker 1' 7 $false)); expected=''},
    @{nodes=@((New-TestHeader 'Worker 2' 950 $false)); expected=''},
    @{nodes=@((New-TestHeader 'Worker 1' 30 $true),(New-TestHeader 'Worker 2' 200 $true)); expected=''},
    @{nodes=@((New-TestHeader 'Unselected chat' 30 $true)); expected=''}
)
foreach($case in $cases){
    $window=[pscustomobject]@{nodes=$case.nodes;Current=[pscustomobject]@{BoundingRectangle=[pscustomobject]@{Top=0}}}
    $window | Add-Member ScriptMethod FindAll {
        param($treeScope,$condition)
        return @($this.nodes | Where-Object {$_.Current.Name -ceq $condition.Value})
    }
    $target=Get-Target $window $chats
    if([string]$target.id -cne $case.expected){throw 'Header identity regression'}
}
Write-Output '6 header cases passed'
