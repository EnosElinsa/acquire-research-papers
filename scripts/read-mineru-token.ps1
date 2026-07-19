param([string]$SecretPath = "")

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "secret-store.ps1")
if ([string]::IsNullOrWhiteSpace($SecretPath)) { $SecretPath = Get-AcquisitionSecretPath }

$token = $null
try {
  $payload = Import-AcquisitionSecrets -Path $SecretPath
  $token = ConvertFrom-AcquisitionSecureString $payload.Scopes.mineru.Token
  if ([string]::IsNullOrWhiteSpace($token)) { throw "MinerU token scope is empty." }
  Write-Output $token
}
finally {
  $token = $null
  $payload = $null
}
