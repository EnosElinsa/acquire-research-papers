[CmdletBinding()]
param(
  [string]$Path = "",
  [Parameter(Mandatory)][string]$ResourceAccessUrl,
  [string]$AttributeReleaseTitle = "",
  [string]$AttributeReleaseAcceptControlName = "",
  [string]$AttributeReleaseRejectControlName = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "secret-store.ps1")
if ([string]::IsNullOrWhiteSpace($Path)) { $Path = Get-AcquisitionSecretPath }

Set-IeeeInstitutionRoute `
  -ResourceAccessUrl $ResourceAccessUrl `
  -AttributeReleaseTitle $AttributeReleaseTitle `
  -AttributeReleaseAcceptControlName $AttributeReleaseAcceptControlName `
  -AttributeReleaseRejectControlName $AttributeReleaseRejectControlName `
  -Path $Path

[ordered]@{ status = "updated"; scope = "ieee_institution"; path = $Path } |
  ConvertTo-Json -Compress
