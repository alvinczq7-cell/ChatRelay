# Read-only: did anything reach ChatRelay, and is WeChat producing share files at all?
$ErrorActionPreference = 'Continue'
"== ChatRelay package"
Get-AppxPackage -Name 'ChatRelay.ShareTarget' | Select-Object PackageFullName, Status, InstallLocation | Format-List | Out-String
"== relay.log (last 20)"
$log = Join-Path $env:LOCALAPPDATA 'ChatRelay\relay.log'
if (Test-Path $log) { Get-Content $log -Tail 20 -Encoding UTF8 } else { 'no relay.log' }
"== Inbox"
Get-ChildItem (Join-Path $env:LOCALAPPDATA 'ChatRelay\Inbox') -ErrorAction SilentlyContinue | Select-Object Name, LastWriteTime | Format-Table -AutoSize | Out-String
"== WeixinShare temp (WeChat writes share payloads here)"
Get-ChildItem (Join-Path $env:TEMP 'WeixinShare') -Recurse -ErrorAction SilentlyContinue | Select-Object -First 20 FullName, Length, LastWriteTime | Format-Table -AutoSize | Out-String -Width 250
"== Weixin version"
Get-Process Weixin -ErrorAction SilentlyContinue | Select-Object -First 1 @{n='Ver';e={$_.MainModule.FileVersionInfo.FileVersion}}, StartTime | Format-List | Out-String
"== Recent AppX deployment errors"
Get-WinEvent -LogName 'Microsoft-Windows-AppXDeploymentServer/Operational' -MaxEvents 200 -ErrorAction SilentlyContinue |
    Where-Object { $_.LevelDisplayName -in 'Error', 'Warning' -and $_.Message -match 'ChatRelay' } |
    Select-Object -First 5 TimeCreated, Id, Message | Format-List | Out-String -Width 250
"== WeChat log lines mentioning share (last hour)"
$xlog = Join-Path $env:APPDATA 'Tencent\xwechat\log'
if (Test-Path $xlog) {
    Get-ChildItem $xlog -Recurse -File -ErrorAction SilentlyContinue | Where-Object LastWriteTime -gt (Get-Date).AddHours(-1) |
        Select-Object -First 10 FullName, Length, LastWriteTime | Format-Table -AutoSize | Out-String -Width 250
} else { "no $xlog" }
