param(
  [Parameter(Mandatory)][string]$ExpectedHost,
  [string]$SecretPath = "",
  [string]$ProfileId = "",
  [switch]$Optional
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
. (Join-Path $PSScriptRoot "secret-store.ps1")
if ([string]::IsNullOrWhiteSpace($SecretPath)) { $SecretPath = Get-AcquisitionSecretPath }
if (-not [string]::IsNullOrWhiteSpace($ProfileId) -and
    $ProfileId -cnotmatch '^[a-z0-9][a-z0-9-]{0,62}$') {
  throw 'Invalid institutional profile ID.'
}
if ($Optional -and -not (Test-Path -LiteralPath $SecretPath)) {
  Write-Output 'null'
  return
}

$password = $null
try {
  $payload = Import-AcquisitionSecrets -Path $SecretPath
  if (-not [string]::IsNullOrWhiteSpace($ProfileId)) {
    if ($Optional) {
      if ($payload.Scopes.PSObject.Properties.Name -notcontains 'ieee_profiles') {
        Write-Output 'null'
        return
      }
      if ($null -eq $payload.Scopes.ieee_profiles) {
        throw 'Named institutional credential scope is invalid.'
      }
      if ($payload.Scopes.ieee_profiles.PSObject.Properties.Name -notcontains $ProfileId) {
        Write-Output 'null'
        return
      }
    }
    $credential = Get-IeeeNamedCredential -ProfileId $ProfileId -ExpectedHost $ExpectedHost -Payload $payload
    $password = ConvertFrom-AcquisitionSecureString $credential.Password
    [pscustomobject]@{ username = $credential.UserName; password = $password } | ConvertTo-Json -Compress
    exit 0
  }
  if ($payload.Scopes.PSObject.Properties.Name -notcontains "ieee_institution") {
    if ($Optional) { Write-Output 'null'; return }
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
