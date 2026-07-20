param(
  [string]$Path = "",
  [switch]$Force
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "secret-store.ps1")

if ([string]::IsNullOrWhiteSpace($Path)) { $Path = Get-AcquisitionSecretPath }
if ((Test-Path -LiteralPath $Path -PathType Leaf) -and -not $Force) {
  $existing = Import-AcquisitionSecrets -Path $Path
  if ($existing.Scopes.PSObject.Properties.Name -contains "ieee_institution") {
    throw "IEEE institution profile already exists. Re-run with -Force to replace that scope."
  }
}

$organization = Read-Host "Institution display name"
$carsiSchoolPlaceholder = Read-Host "CARSI institution-search placeholder"
$carsiSearchText = Read-Host "CARSI search text"
$carsiInstitution = Read-Host "Exact CARSI institution option"
$carsiLoginButtonName = Read-Host "CARSI login button name"
$credentialHost = Read-Host "Exact institutional IdP hostname (no scheme or path)"
$usernameLabel = Read-Host "Username field label"
$passwordLabel = Read-Host "Password field label"
$loginButtonName = Read-Host "Institution login button name"
$consentTitle = Read-Host "Optional attribute-release page title"
$consentButtonName = Read-Host "Optional attribute-release accept button name"
$usernameSecure = Read-Host "Institution username" -AsSecureString
$password = Read-Host "Institution password" -AsSecureString
$username = $null
try {
  $username = ConvertFrom-AcquisitionSecureString $usernameSecure
  if ([string]::IsNullOrWhiteSpace($username)) { throw "Username cannot be empty." }
  $credential = [Management.Automation.PSCredential]::new($username.Trim(), $password)
  $institution = [ordered]@{
    Organization = $organization
    CarsiSchoolPlaceholder = $carsiSchoolPlaceholder
    CarsiSearchText = $carsiSearchText
    CarsiInstitution = $carsiInstitution
    CarsiLoginButtonName = $carsiLoginButtonName
    CredentialHost = $credentialHost
    UsernameLabel = $usernameLabel
    PasswordLabel = $passwordLabel
    LoginButtonName = $loginButtonName
    ConsentTitle = $consentTitle
    ConsentButtonName = $consentButtonName
  }
  Set-IeeeInstitutionCredential -Institution $institution -Credential $credential -Path $Path
  [ordered]@{ status = "stored"; scope = "ieee_institution"; path = $Path } |
    ConvertTo-Json -Compress
}
finally {
  $username = $null
  $credential = $null
  $institution = $null
}
