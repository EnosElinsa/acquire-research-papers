param(
  [Parameter(Mandatory)][string]$ExpectedHost,
  [string]$SecretPath = ""
)

$ErrorActionPreference = "Stop"
if ($ExpectedHost.Trim().ToLowerInvariant() -ne "api.elsevier.com") {
  throw "API key release denied for unapproved host."
}

. (Join-Path $PSScriptRoot "secret-store.ps1")
if ([string]::IsNullOrWhiteSpace($SecretPath)) { $SecretPath = Get-AcquisitionSecretPath }

$apiKey = $null
try {
  $payload = Import-AcquisitionSecrets -Path $SecretPath
  if ($payload.Scopes.api_keys.PSObject.Properties.Name -notcontains "elsevier") {
    throw "Elsevier API key scope is missing."
  }
  $apiKey = ConvertFrom-AcquisitionSecureString $payload.Scopes.api_keys.elsevier
  if ([string]::IsNullOrWhiteSpace($apiKey)) {
    throw "Elsevier API key scope is empty."
  }
  Write-Output $apiKey
}
finally {
  $apiKey = $null
  $payload = $null
}
