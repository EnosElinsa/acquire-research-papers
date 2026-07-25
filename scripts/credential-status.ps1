param([string]$SecretPath = "")

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "secret-store.ps1")
if ([string]::IsNullOrWhiteSpace($SecretPath)) {
  $SecretPath = Get-AcquisitionSecretPath
}

$status = [ordered]@{
  ieee = $false
  mineru = $false
  elsevier = $false
  semantic_scholar = $false
  openalex = $false
}
if (Test-Path -LiteralPath $SecretPath -PathType Leaf) {
  $payload = Import-AcquisitionSecretPayload -Path $SecretPath
  if ($payload.Scopes.PSObject.Properties.Name -contains "ieee_institution") {
    $scope = $payload.Scopes.ieee_institution
    $status.ieee = (
      $null -ne $scope.Profile -and
      $scope.Credential -is [Management.Automation.PSCredential]
    )
  }
  if ($payload.Scopes.PSObject.Properties.Name -contains "mineru") {
    $status.mineru = (
      $payload.Scopes.mineru.Token -is [Security.SecureString] -and
      $payload.Scopes.mineru.Token.Length -gt 0
    )
  }
  if ($payload.Scopes.PSObject.Properties.Name -contains "api_keys") {
    foreach ($provider in @("elsevier", "semantic_scholar", "openalex")) {
      if ($payload.Scopes.api_keys.PSObject.Properties.Name -contains $provider) {
        $value = $payload.Scopes.api_keys.$provider
        $status[$provider] = ($value -is [Security.SecureString] -and $value.Length -gt 0)
      }
    }
  }
}
$status | ConvertTo-Json -Compress
