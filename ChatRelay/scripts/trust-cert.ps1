# Run ONCE in an elevated (Administrator) PowerShell.
# Adds the local ChatRelay Dev signing certificate to Local Computer > Trusted People,
# which Windows requires before it will install a self-signed MSIX.
# Undo: certlm.msc -> Trusted People -> Certificates -> delete "ChatRelay Dev".
param([string]$Cer = (Join-Path $env:LOCALAPPDATA 'ChatRelay\App\ChatRelay.Dev.cer'))
$ErrorActionPreference = 'Stop'
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw 'Please run this script from an Administrator PowerShell.' }
if (-not (Test-Path $Cer)) { throw "Certificate not found: $Cer (run build.ps1 first)" }
Import-Certificate -FilePath $Cer -CertStoreLocation Cert:\LocalMachine\TrustedPeople | Format-List Subject, Thumbprint, NotAfter
Write-Host 'Trusted. Now run scripts\register.ps1 (no admin needed).'
