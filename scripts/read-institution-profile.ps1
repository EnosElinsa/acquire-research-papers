param(
  [string]$SecretPath = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
. (Join-Path $PSScriptRoot "secret-store.ps1")
if ([string]::IsNullOrWhiteSpace($SecretPath)) { $SecretPath = Get-AcquisitionSecretPath }

$payload = Import-AcquisitionSecrets -Path $SecretPath
if ($payload.Scopes.PSObject.Properties.Name -notcontains "ieee_institution") {
  throw "IEEE institution profile is not configured."
}
$profile = $payload.Scopes.ieee_institution.Profile
[ordered]@{
  organization = $profile.Organization
  carsiSchoolPlaceholder = $profile.CarsiSchoolPlaceholder
  carsiSearchText = $profile.CarsiSearchText
  carsiInstitution = $profile.CarsiInstitution
  carsiLoginButtonName = $profile.CarsiLoginButtonName
  carsiEntityId = $profile.CarsiEntityId
  credentialHost = $profile.CredentialHost
  usernameLabel = $profile.UsernameLabel
  passwordLabel = $profile.PasswordLabel
  loginButtonName = $profile.LoginButtonName
  resourceAccessUrl = $profile.ResourceAccessUrl
  attributeReleaseTitle = $profile.AttributeReleaseTitle
  attributeReleaseAcceptControlName = $profile.AttributeReleaseAcceptControlName
  attributeReleaseRejectControlName = $profile.AttributeReleaseRejectControlName
} | ConvertTo-Json -Compress
