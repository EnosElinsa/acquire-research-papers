param(
  [Parameter(Mandatory)][string]$Provider,
  [Parameter(Mandatory)][string]$ExpectedHost,
  [string]$SecretPath = "",
  [switch]$AllowMissing
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "secret-store.ps1")

$approvedHost = Get-DiscoveryApiProviderHost -Provider $Provider
if (-not [string]::Equals($ExpectedHost, $approvedHost, [StringComparison]::OrdinalIgnoreCase)) {
  throw "API key release denied for unapproved host."
}
if ([string]::IsNullOrWhiteSpace($SecretPath)) {
  $SecretPath = Get-AcquisitionSecretPath
}
if (-not (Test-Path -LiteralPath $SecretPath -PathType Leaf)) {
  if ($AllowMissing) { return }
  throw "DPAPI secret file is missing."
}

$apiKey = $null
$payload = $null
try {
  $payload = Import-AcquisitionSecrets -Path $SecretPath
  $name = $Provider.Trim().ToLowerInvariant()
  if ($payload.Scopes.PSObject.Properties.Name -notcontains "api_keys" -or
      $payload.Scopes.api_keys.PSObject.Properties.Name -notcontains $name) {
    if ($AllowMissing) { return }
    throw "Discovery API key scope is missing."
  }
  $apiKey = ConvertFrom-AcquisitionSecureString $payload.Scopes.api_keys.$name
  if ([string]::IsNullOrWhiteSpace($apiKey)) {
    throw "Discovery API key scope is empty."
  }
  Write-Output $apiKey
}
finally {
  $apiKey = $null
  $payload = $null
}
