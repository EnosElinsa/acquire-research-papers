[CmdletBinding()]
param(
  [string]$LegacyPath = (Join-Path $env:LOCALAPPDATA "Codex\secrets\retrieve-ieee-papers.clixml"),
  [string]$DestinationPath = "",
  [string]$RepoRoot = "",
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
if ($null -eq $legacy -or [int]$legacy.SchemaVersion -ne 1 -or
    $legacy.Organization -ne "Guangxi University" -or
    $legacy.IeeeCredential -isnot [Management.Automation.PSCredential] -or
    $legacy.MinerUToken -isnot [Security.SecureString]) {
  throw "Legacy DPAPI payload is invalid or unsupported."
}
Export-AcquisitionSecrets `
  -IeeeCredential $legacy.IeeeCredential `
  -MinerUToken $legacy.MinerUToken `
  -Path $destination

[ordered]@{ status = "migrated"; path = $destination } | ConvertTo-Json -Compress
