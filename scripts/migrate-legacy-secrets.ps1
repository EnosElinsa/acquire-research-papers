[CmdletBinding()]
param(
  [string]$LegacyPath = (Join-Path $env:LOCALAPPDATA "Codex\secrets\retrieve-ieee-papers.clixml"),
  [string]$DestinationPath = "",
  [string]$RepoRoot = "",
  [Parameter(Mandatory)][string]$CarsiSchoolPlaceholder,
  [Parameter(Mandatory)][string]$CarsiSearchText,
  [Parameter(Mandatory)][string]$CarsiInstitution,
  [Parameter(Mandatory)][string]$CarsiLoginButtonName,
  [Parameter(Mandatory)][string]$CarsiEntityId,
  [Parameter(Mandatory)][string]$CredentialHost,
  [Parameter(Mandatory)][string]$UsernameLabel,
  [Parameter(Mandatory)][string]$PasswordLabel,
  [Parameter(Mandatory)][string]$LoginButtonName,
  [Parameter(Mandatory)][string]$ResourceAccessUrl,
  [string]$AttributeReleaseTitle = "",
  [string]$AttributeReleaseAcceptControlName = "",
  [string]$AttributeReleaseRejectControlName = "",
  [switch]$Force
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "secret-store.ps1")

if ([string]::IsNullOrWhiteSpace($DestinationPath)) {
  $DestinationPath = Get-AcquisitionSecretPath
}
$destination = [IO.Path]::GetFullPath($DestinationPath)
if (-not [string]::IsNullOrWhiteSpace($RepoRoot)) {
  $repository = [IO.Path]::GetFullPath($RepoRoot).TrimEnd('\', '/')
  if ($destination.Equals($repository, [StringComparison]::OrdinalIgnoreCase) -or
      $destination.StartsWith($repository + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Secret destination must remain outside the Git repository."
  }
}
if ((Test-Path -LiteralPath $destination) -and -not $Force) {
  throw "Destination already exists. Re-run with -Force to replace it: $destination"
}
if (-not (Test-Path -LiteralPath $LegacyPath -PathType Leaf)) {
  throw "Legacy DPAPI payload is missing: $LegacyPath"
}

$legacy = Import-Clixml -LiteralPath $LegacyPath
if ($null -eq $legacy -or [int]$legacy.SchemaVersion -ne 1) {
  throw "Legacy DPAPI payload is invalid or unsupported."
}
$legacyCredential = $null
$legacyToken = $null
$legacyOrganization = [string]$legacy.Organization
if ($legacy.IeeeCredential -is [Management.Automation.PSCredential]) {
  $legacyCredential = $legacy.IeeeCredential
}
if ($legacy.MinerUToken -is [Security.SecureString]) {
  $legacyToken = $legacy.MinerUToken
}
if ($null -ne $legacy.Scopes) {
  foreach ($property in $legacy.Scopes.PSObject.Properties) {
    $scope = $property.Value
    if ($null -eq $legacyCredential -and $scope.Credential -is [Management.Automation.PSCredential]) {
      $legacyCredential = $scope.Credential
      if ([string]::IsNullOrWhiteSpace($legacyOrganization)) {
        $legacyOrganization = [string]$scope.Organization
        if ([string]::IsNullOrWhiteSpace($legacyOrganization)) {
          $legacyOrganization = [string]$scope.Profile.Organization
        }
      }
    }
    if ($null -eq $legacyToken -and $scope.Token -is [Security.SecureString]) {
      $legacyToken = $scope.Token
    }
  }
}
if ([string]::IsNullOrWhiteSpace($legacyOrganization) -or
    $legacyCredential -isnot [Management.Automation.PSCredential] -or
    $legacyToken -isnot [Security.SecureString]) {
  throw "Legacy DPAPI payload is invalid or unsupported."
}
$institution = [ordered]@{
  Organization = $legacyOrganization
  CarsiSchoolPlaceholder = $CarsiSchoolPlaceholder
  CarsiSearchText = $CarsiSearchText
  CarsiInstitution = $CarsiInstitution
  CarsiLoginButtonName = $CarsiLoginButtonName
  CarsiEntityId = $CarsiEntityId
  CredentialHost = $CredentialHost
  UsernameLabel = $UsernameLabel
  PasswordLabel = $PasswordLabel
  LoginButtonName = $LoginButtonName
  ResourceAccessUrl = $ResourceAccessUrl
  AttributeReleaseTitle = $AttributeReleaseTitle
  AttributeReleaseAcceptControlName = $AttributeReleaseAcceptControlName
  AttributeReleaseRejectControlName = $AttributeReleaseRejectControlName
}
Set-IeeeInstitutionCredential `
  -Institution $institution `
  -Credential $legacyCredential `
  -Path $destination
Set-MineruToken -Token $legacyToken -Path $destination

[ordered]@{ status = "migrated"; path = $destination } | ConvertTo-Json -Compress
