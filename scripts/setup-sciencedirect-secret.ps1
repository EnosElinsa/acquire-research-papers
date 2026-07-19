param([string]$Path = "")

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "secret-store.ps1")
if ([string]::IsNullOrWhiteSpace($Path)) { $Path = Get-AcquisitionSecretPath }

$usernameSecure = Read-Host "South China Agricultural University username" -AsSecureString
$password = Read-Host "South China Agricultural University password" -AsSecureString
$username = $null
try {
  $username = ConvertFrom-AcquisitionSecureString $usernameSecure
  if ([string]::IsNullOrWhiteSpace($username)) { throw "Username cannot be empty." }
  $credential = [Management.Automation.PSCredential]::new($username.Trim(), $password)
  Set-ScienceDirectCredential -Credential $credential -Path $Path
  [ordered]@{ status = "stored"; scope = "sciencedirect_scau"; path = $Path } |
    ConvertTo-Json -Compress
}
finally {
  $username = $null
  $credential = $null
}
