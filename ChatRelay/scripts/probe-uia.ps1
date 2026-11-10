# Read-only probe: does WeChat's main window currently expose a UI Automation tree?
# Prints only counts and control types / class names. Never prints element names or
# text, so no message content is read. Changes nothing (registry is only read).
$ErrorActionPreference = 'Continue'
"== Narrator RunningState (WeChat 4.x exposes UIA only when this is 1)"
try { Get-ItemPropertyValue 'HKCU:\SOFTWARE\Microsoft\Narrator\NoRoam' -Name RunningState -ErrorAction Stop } catch { 'not set' }

Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition ([System.Windows.Automation.AutomationElement]::ClassNameProperty), 'mmui::MainWindow'
$win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond)
if (-not $win) {
    "== top-level windows owned by Weixin.exe"
    $pids = (Get-Process Weixin -ErrorAction SilentlyContinue).Id
    $all = $root.FindAll([System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)
    foreach ($w in $all) { if ($pids -contains $w.Current.ProcessId) { "  class={0}" -f $w.Current.ClassName; if (-not $win) { $win = $w } } }
}
if (-not $win) { 'WeChat main window not found (is it open and not minimized to tray?)'; return }
"== main window class: $($win.Current.ClassName)"
$walker = [System.Windows.Automation.TreeWalker]::RawViewWalker
$stats = @{}; $count = 0
$queue = New-Object System.Collections.Queue; $queue.Enqueue(@($win, 0))
while ($queue.Count -gt 0 -and $count -lt 3000) {
    $pair = $queue.Dequeue(); $el = $pair[0]; $d = $pair[1]
    $count++
    $key = '{0} / {1}' -f $el.Current.ControlType.ProgrammaticName.Replace('ControlType.', ''), $el.Current.ClassName
    $stats[$key] = 1 + [int]$stats[$key]
    if ($d -lt 25) {
        $c = $walker.GetFirstChild($el)
        while ($c) { $queue.Enqueue(@($c, ($d + 1))); $c = $walker.GetNextSibling($c) }
    }
}
"== UIA nodes under main window: $count"
$stats.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 25 | ForEach-Object { '  {0,5}  {1}' -f $_.Value, $_.Key }
