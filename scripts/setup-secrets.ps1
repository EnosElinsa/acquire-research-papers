param(
  [string]$Path = "",
  [switch]$Force
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "secret-store.ps1")
if ([string]::IsNullOrWhiteSpace($Path)) { $Path = Get-AcquisitionSecretPath }
if ((Test-Path -LiteralPath $Path -PathType Leaf) -and -not $Force) {
  $existing = Import-AcquisitionSecrets -Path $Path
  if ($existing.Scopes.PSObject.Properties.Name -contains "ieee_institution" -or
      $existing.Scopes.PSObject.Properties.Name -contains "mineru") {
    throw "An IEEE institution or MinerU scope already exists. Re-run with -Force to replace both scopes."
  }
}
$arguments = @{}
$arguments.Path = $Path
if ($Force) { $arguments.Force = $true }

$ieeeResult = & (Join-Path $PSScriptRoot "setup-ieee-institution.ps1") @arguments |
  Select-Object -Last 1 | ConvertFrom-Json
$mineruResult = & (Join-Path $PSScriptRoot "setup-mineru-token.ps1") @arguments |
  Select-Object -Last 1 | ConvertFrom-Json
[ordered]@{
  status = "stored"
  scopes = @($ieeeResult.scope, $mineruResult.scope)
  path = $ieeeResult.path
} | ConvertTo-Json -Compress
