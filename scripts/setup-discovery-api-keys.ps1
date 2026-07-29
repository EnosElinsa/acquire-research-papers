param(
  [Alias("Providers")]
  [ValidateSet("semantic_scholar", "openalex", "elsevier")]
  [string[]]$Provider = @("semantic_scholar", "openalex", "elsevier"),
  [string]$Path = "",
  [switch]$Force
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "secret-store.ps1")
if ([string]::IsNullOrWhiteSpace($Path)) { $Path = Get-AcquisitionSecretPath }

$labels = @{
  semantic_scholar = "Semantic Scholar"
  openalex = "OpenAlex"
  elsevier = "Elsevier"
}

foreach ($requestedProvider in $Provider) {
  $name = $requestedProvider.Trim().ToLowerInvariant()
  [void](Get-DiscoveryApiProviderHost -Provider $name)
  $alreadyConfigured = $false
  if (Test-Path -LiteralPath $Path -PathType Leaf) {
    $existing = Import-AcquisitionSecrets -Path $Path
    $alreadyConfigured = (
      $existing.Scopes.PSObject.Properties.Name -contains "api_keys" -and
      $existing.Scopes.api_keys.PSObject.Properties.Name -contains $name
    )
  }
  if ($alreadyConfigured -and -not $Force) {
    [ordered]@{ status = "unchanged"; capability = $name } | ConvertTo-Json -Compress
    continue
  }

  $label = $labels[$name]
  Write-Host "Configuring optional $label access. Input is hidden; paste the key and press Enter, or press Enter on an empty prompt to skip."
  $apiKey = Read-Host "$label API key" -AsSecureString
  if ($null -eq $apiKey -or $apiKey.Length -eq 0) {
    $status = if ($alreadyConfigured) { "unchanged" } else { "skipped" }
    Write-Host "$label configuration was not changed."
    [ordered]@{ status = $status; capability = $name } | ConvertTo-Json -Compress
    $apiKey = $null
    continue
  }
  try {
    Set-DiscoveryApiKey -Provider $name -ApiKey $apiKey -Path $Path
    Write-Host "$label configuration stored in the local DPAPI secret file."
    [ordered]@{ status = "stored"; capability = $name } | ConvertTo-Json -Compress
  }
  finally {
    $apiKey = $null
  }
}
