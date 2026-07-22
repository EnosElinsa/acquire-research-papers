[CmdletBinding()]
param(
  [string]$Path = "",
  [Parameter(Mandatory)][string]$CarsiEntityId
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "secret-store.ps1")
if ([string]::IsNullOrWhiteSpace($Path)) { $Path = Get-AcquisitionSecretPath }

Set-IeeeInstitutionEntityId -CarsiEntityId $CarsiEntityId -Path $Path

[ordered]@{ status = "updated"; scope = "ieee_institution"; path = $Path } |
  ConvertTo-Json -Compress
