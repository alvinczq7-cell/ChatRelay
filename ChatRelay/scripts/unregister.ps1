# Removes the ChatRelay share target. Inbox files under %LOCALAPPDATA%\ChatRelay\Inbox are kept.
Get-AppxPackage -Name 'ChatRelay.ShareTarget' | Remove-AppxPackage
Write-Host 'Unregistered ChatRelay.ShareTarget.'
