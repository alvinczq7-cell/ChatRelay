# Builds ChatRelay.ShareTarget, lays it out in the install root, packs and signs the
# sparse MSIX. Does NOT trust the certificate or register the package
# (see trust-cert.ps1 and register.ps1).
[CmdletBinding()]
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'ChatRelay\App'),
    [string]$Subject = 'CN=ChatRelay Dev'
)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$project = Join-Path $repo 'src\ChatRelay.ShareTarget\ChatRelay.ShareTarget.csproj'
$packagingDir = Join-Path $repo 'packaging'
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)

function Resolve-SdkTool([string]$name) {
    $c = Get-Command $name -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    $f = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\$name" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1
    if ($f) { return $f.FullName }
    throw "$name not found. Install the Windows SDK."
}

# 1. Publish the exe into <InstallRoot>\share-target
Write-Host "[1/5] dotnet publish -> $InstallRoot\share-target"
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
# Intermediates go to a short path: this repo may sit in a deep folder and MSBuild
# still trips over the 260-character path limit for obj\.
$artifacts = Join-Path $env:LOCALAPPDATA 'ChatRelay\build'
# Always start clean: a stale obj\ (e.g. apphost.exe removed by antivirus or a half
# finished earlier build) makes incremental publish fail with MSB3030.
# rd with the \\?\ prefix, because Windows PowerShell's Remove-Item cannot delete
# paths longer than 260 characters.
function Remove-Tree([string]$path) {
    if (Test-Path -LiteralPath $path) { cmd /c "rd /s /q `"\\?\$path`"" | Out-Null }
}
Remove-Tree $artifacts
Remove-Tree (Join-Path $repo 'src\ChatRelay.ShareTarget\obj')
Remove-Tree (Join-Path $repo 'src\ChatRelay.ShareTarget\bin')
# Do not reuse long-lived MSBuild / compiler server processes: one started from a
# different (e.g. sandboxed) context writes its outputs where this build cannot see
# them, which surfaces as MSB3030 "apphost.exe not found".
& dotnet build-server shutdown | Out-Null
& dotnet publish $project -c Release -o (Join-Path $InstallRoot 'share-target') --artifacts-path $artifacts --nologo `
    -nodeReuse:false -p:UseSharedCompilation=false
if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed ($LASTEXITCODE)" }

# 2. Logos. A sparse package resolves manifest paths against the external location,
#    so the assets must exist there too, or the shell silently skips the target.
Write-Host "[2/5] assets"
$assets = Join-Path $packagingDir 'Assets'
& (Join-Path $PSScriptRoot 'make-assets.ps1') -OutDir $assets
New-Item -ItemType Directory -Force -Path (Join-Path $InstallRoot 'Assets') | Out-Null
Copy-Item (Join-Path $assets '*') (Join-Path $InstallRoot 'Assets') -Force

# 3. Pack (manifest + assets + resources.pri) into an MSIX
Write-Host "[3/5] makepri + makeappx"
$stage = Join-Path ([IO.Path]::GetTempPath()) ("ChatRelay-stage-" + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $stage | Out-Null
try {
    Copy-Item (Join-Path $packagingDir 'AppxManifest.xml') $stage
    Copy-Item $assets (Join-Path $stage 'Assets') -Recurse
    $makePri = Resolve-SdkTool 'makepri.exe'
    $priConfig = Join-Path $stage 'priconfig.xml'
    & $makePri createconfig /cf $priConfig /dq en-US /o | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "makepri createconfig failed" }
    $pri = Join-Path $stage 'resources.pri'
    & $makePri new /pr $stage /cf $priConfig /of $pri /in 'ChatRelay.ShareTarget' /o | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "makepri new failed" }
    Remove-Item $priConfig -Force
    Copy-Item $pri (Join-Path $InstallRoot 'resources.pri') -Force

    $msix = Join-Path $InstallRoot 'ChatRelay.ShareTarget.msix'
    & (Resolve-SdkTool 'makeappx.exe') pack /d $stage /p $msix /nv /o | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "makeappx failed" }
}
finally {
    if ($stage.StartsWith([IO.Path]::GetTempPath()) -and (Split-Path $stage -Leaf).StartsWith('ChatRelay-stage-')) {
        Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# 4. Self-signed code signing certificate in the current user's personal store
Write-Host "[4/5] certificate"
$cert = Get-ChildItem Cert:\CurrentUser\My | Where-Object { $_.Subject -eq $Subject -and $_.NotAfter -gt (Get-Date).AddDays(30) } |
    Sort-Object NotAfter -Descending | Select-Object -First 1
if (-not $cert) {
    $cert = New-SelfSignedCertificate -Type Custom -Subject $Subject -KeyUsage DigitalSignature `
        -FriendlyName 'ChatRelay Dev (local MSIX signing)' -CertStoreLocation Cert:\CurrentUser\My `
        -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3', '2.5.29.19={text}') -NotAfter (Get-Date).AddYears(2)
}
$cer = Join-Path $InstallRoot 'ChatRelay.Dev.cer'
Export-Certificate -Cert $cert -FilePath $cer -Force | Out-Null

# 5. Sign
Write-Host "[5/5] signtool"
& (Resolve-SdkTool 'signtool.exe') sign /fd SHA256 /sha1 $cert.Thumbprint $msix | Out-Null
if ($LASTEXITCODE -ne 0) { throw "signtool failed ($LASTEXITCODE)" }

$sig = Get-AuthenticodeSignature $msix
Write-Host ""
Write-Host "Built:       $msix"
Write-Host "Certificate: $cer  (thumbprint $($cert.Thumbprint))"
Write-Host "Signature:   $($sig.Status)"
if ($sig.Status -ne 'Valid') {
    Write-Host "Next: run scripts\trust-cert.ps1 as Administrator once, then scripts\register.ps1"
} else {
    Write-Host "Next: scripts\register.ps1"
}
