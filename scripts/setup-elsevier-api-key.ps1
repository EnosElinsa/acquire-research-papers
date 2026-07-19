param([string]$Path = "")

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "secret-store.ps1")
if ([string]::IsNullOrWhiteSpace($Path)) { $Path = Get-AcquisitionSecretPath }

$apiKey = Read-Host "Elsevier API key" -AsSecureString
try {
  Set-ElsevierApiKey -ApiKey $apiKey -Path $Path
  [ordered]@{ status = "stored"; scope = "api_keys.elsevier"; path = $Path } |
    ConvertTo-Json -Compress
}
finally {
  $apiKey = $null
}
