param(
  [Parameter(Mandatory)][string]$ExpectedHost,
  [string]$SecretPath = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
. (Join-Path $PSScriptRoot "secret-store.ps1")
if ([string]::IsNullOrWhiteSpace($SecretPath)) { $SecretPath = Get-AcquisitionSecretPath }

$password = $null
try {
  $payload = Import-AcquisitionSecrets -Path $SecretPath
  if ($payload.Scopes.PSObject.Properties.Name -notcontains "ieee_institution") {
    throw "IEEE institution profile is not configured."
  }
  $scope = $payload.Scopes.ieee_institution
  $expected = $ExpectedHost.Trim()
  if ($expected.EndsWith(".") -or
      $expected.ToLowerInvariant() -ne $scope.Profile.CredentialHost.ToLowerInvariant()) {
    throw "Credential release denied for unapproved host."
  }
  $credential = $scope.Credential
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
