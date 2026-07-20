param(
  [string]$Path = "",
  [switch]$Force
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "secret-store.ps1")

if ([string]::IsNullOrWhiteSpace($Path)) { $Path = Get-AcquisitionSecretPath }
if ((Test-Path -LiteralPath $Path -PathType Leaf) -and -not $Force) {
  $existing = Import-AcquisitionSecrets -Path $Path
  if ($existing.Scopes.PSObject.Properties.Name -contains "mineru") {
    throw "MinerU token already exists. Re-run with -Force to replace that scope."
  }
}

$token = Read-Host "MinerU API token" -AsSecureString
Set-MineruToken -Token $token -Path $Path
[ordered]@{ status = "stored"; scope = "mineru"; path = $Path } | ConvertTo-Json -Compress
