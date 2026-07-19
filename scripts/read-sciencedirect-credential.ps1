param(
  [Parameter(Mandatory)][string]$ExpectedHost,
  [string]$SecretPath = ""
)

$ErrorActionPreference = "Stop"
if ($ExpectedHost.Trim().ToLowerInvariant() -ne "vpn.scau.edu.cn") {
  throw "Credential release denied for unapproved host."
}

. (Join-Path $PSScriptRoot "secret-store.ps1")
if ([string]::IsNullOrWhiteSpace($SecretPath)) { $SecretPath = Get-AcquisitionSecretPath }

$password = $null
try {
  $payload = Import-AcquisitionSecrets -Path $SecretPath
  if ($payload.Scopes.PSObject.Properties.Name -notcontains "sciencedirect_scau") {
    throw "ScienceDirect SCAU credential scope is missing."
  }
  $credential = $payload.Scopes.sciencedirect_scau.Credential
  $password = ConvertFrom-AcquisitionSecureString $credential.Password
  [pscustomobject]@{
    username = $credential.UserName
    password = $password
  } | ConvertTo-Json -Compress
}
finally {
  $password = $null
  $credential = $null
  $payload = $null
}
