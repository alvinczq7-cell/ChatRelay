# Registers the signed sparse package for the current user (no admin needed once the
# certificate is trusted). Re-run after every build.ps1.
param([string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'ChatRelay\App'))
$ErrorActionPreference = 'Stop'
$msix = Join-Path $InstallRoot 'ChatRelay.ShareTarget.msix'
$sig = Get-AuthenticodeSignature $msix
if ($sig.Status -ne 'Valid') { throw "MSIX signature is $($sig.Status). Run scripts\trust-cert.ps1 as Administrator first." }

Get-AppxPackage -Name 'ChatRelay.ShareTarget' | Remove-AppxPackage
Add-AppxPackage -Path $msix -ExternalLocation $InstallRoot
$pkg = Get-AppxPackage -Name 'ChatRelay.ShareTarget'
if (-not $pkg) { throw 'Add-AppxPackage returned but the package is not registered.' }
Write-Host "Registered: $($pkg.PackageFullName)"

$exe = Join-Path $InstallRoot 'share-target\ChatRelay.ShareTarget.exe'
$p = Start-Process -FilePath $exe -ArgumentList '--registration-check' -Wait -PassThru
Write-Host ("Package identity check: " + $(if ($p.ExitCode -eq 0) { 'OK' } else { "FAILED (exit $($p.ExitCode))" }))
Write-Host 'Restart WeChat completely (end all Weixin / WeChatAppEx processes) so its share menu re-enumerates.'
