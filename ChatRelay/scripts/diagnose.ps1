# Read-only diagnostics for the "apphost.exe not found" (MSB3030) build failure.
$ErrorActionPreference = 'Continue'
"== apphost template packs"
Get-ChildItem 'C:\Program Files\dotnet\packs' -Directory -Filter 'Microsoft.NETCore.App.Host*' -ErrorAction SilentlyContinue |
    ForEach-Object { Get-ChildItem $_.FullName -Directory | ForEach-Object { $t = Get-ChildItem $_.FullName -Recurse -Filter apphost.exe -ErrorAction SilentlyContinue | Select-Object -First 1; "{0}  apphost={1}" -f $_.FullName, $(if ($t) { $t.FullName } else { 'MISSING' }) } }
"== NuGet apphost packs"
Get-ChildItem "$env:USERPROFILE\.nuget\packages\microsoft.netcore.app.host.win-x64" -Directory -ErrorAction SilentlyContinue |
    ForEach-Object { $t = Get-ChildItem $_.FullName -Recurse -Filter apphost.exe -ErrorAction SilentlyContinue | Select-Object -First 1; "{0}  apphost={1}" -f $_.FullName, $(if ($t) { $t.FullName } else { 'MISSING' }) }
"== obj after failed build"
Get-ChildItem "$env:LOCALAPPDATA\ChatRelay\build\obj\ChatRelay.ShareTarget\release" -ErrorAction SilentlyContinue | Select-Object Name, Length | Format-Table -AutoSize | Out-String
"== Defender recent detections"
try { Get-MpThreatDetection -ErrorAction Stop | Sort-Object InitialDetectionTime -Descending | Select-Object -First 5 InitialDetectionTime, ThreatID, @{n='Resources';e={$_.Resources -join '; '}} | Format-List | Out-String } catch { "Get-MpThreatDetection unavailable: $($_.Exception.Message)" }
"== Other AV products"
try { Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct -ErrorAction Stop | Select-Object displayName | Out-String } catch { "n/a" }
"== dotnet info"
& dotnet --info | Select-String -Pattern 'Version|RID|Base Path|Host' | Select-Object -First 10 | Out-String
