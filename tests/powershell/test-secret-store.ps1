$ErrorActionPreference = "Stop"

function Assert-True([bool]$Condition, [string]$Message) {
  if (-not $Condition) { throw "ASSERT TRUE FAILED: $Message" }
}

function Assert-Equal($Actual, $Expected, [string]$Message) {
  if ($Actual -ne $Expected) {
    throw "ASSERT EQUAL FAILED: $Message expected=[$Expected] actual=[$Actual]"
  }
}

function Assert-Throws([scriptblock]$Action, [string]$Message) {
  $threw = $false
  try { & $Action } catch { $threw = $true }
  if (-not $threw) { throw "ASSERT THROWS FAILED: $Message" }
}

$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$storePath = Join-Path $root "scripts\secret-store.ps1"
$bridgePath = Join-Path $root "scripts\read-browser-credential.ps1"
$elsevierBridgePath = Join-Path $root "scripts\read-elsevier-api-key.ps1"
$elsevierSetupPath = Join-Path $root "scripts\setup-elsevier-api-key.ps1"
$mineruPath = Join-Path $root "scripts\read-mineru-token.ps1"
$migrationPath = Join-Path $root "scripts\migrate-legacy-secrets.ps1"
foreach ($required in @(
  $storePath,
  $bridgePath,
  $elsevierBridgePath,
  $elsevierSetupPath,
  $mineruPath,
  $migrationPath
)) {
  if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
    throw "Expected implementation file is missing: $required"
  }
}

. $storePath

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("arp-secret-test-" + [guid]::NewGuid().ToString("N"))
try {
  New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
  $localAppData = Join-Path $tempRoot "LocalAppData"
  $secretPath = Join-Path $localAppData "Codex\secrets\acquire-research-papers\secrets.clixml"
  $password = ConvertTo-SecureString "synthetic-password" -AsPlainText -Force
  $token = ConvertTo-SecureString "synthetic-token" -AsPlainText -Force
  $credential = [Management.Automation.PSCredential]::new("synthetic-user", $password)
  $elsevierKey = ConvertTo-SecureString "synthetic-elsevier-key" -AsPlainText -Force

  $elsevierOnlyPath = Join-Path $tempRoot "elsevier-only\secrets.clixml"
  Set-ElsevierApiKey -ApiKey $elsevierKey -Path $elsevierOnlyPath
  $elsevierOnly = Import-AcquisitionSecrets -Path $elsevierOnlyPath
  Assert-Equal (
    ConvertFrom-AcquisitionSecureString $elsevierOnly.Scopes.api_keys.elsevier
  ) "synthetic-elsevier-key" "standalone Elsevier API key"
  Assert-True (
    $elsevierOnly.Scopes.PSObject.Properties.Name -notcontains "ieee_gxu"
  ) "Elsevier-only setup must not require an IEEE scope"
  Assert-True (
    $elsevierOnly.Scopes.PSObject.Properties.Name -notcontains "mineru"
  ) "Elsevier-only setup must not require a MinerU scope"

  Assert-Equal (Get-AcquisitionSecretPath $localAppData) $secretPath "default path"
  Export-AcquisitionSecrets -IeeeCredential $credential -MinerUToken $token -Path $secretPath
  $serialized = Get-Content -Raw -LiteralPath $secretPath
  Assert-True (-not $serialized.Contains("synthetic-password")) "password must stay encrypted"
  Assert-True (-not $serialized.Contains("synthetic-token")) "token must stay encrypted"

  $payload = Import-AcquisitionSecrets -Path $secretPath
  Assert-Equal $payload.SchemaVersion 1 "schema version"
  Assert-Equal $payload.Scopes.ieee_gxu.Organization "Guangxi University" "IEEE scope"
  Assert-Equal $payload.Scopes.ieee_gxu.Credential.UserName "synthetic-user" "username"
  Assert-Equal (ConvertFrom-AcquisitionSecureString $payload.Scopes.mineru.Token) "synthetic-token" "token"

  Set-ElsevierApiKey -ApiKey $elsevierKey -Path $secretPath
  $withElsevier = Import-AcquisitionSecrets -Path $secretPath
  $serialized = Get-Content -Raw -LiteralPath $secretPath
  Assert-True (-not $serialized.Contains("synthetic-elsevier-key")) "Elsevier key must stay encrypted"
  Assert-Equal $withElsevier.Scopes.ieee_gxu.Credential.UserName "synthetic-user" "IEEE scope preserved after Elsevier update"
  Assert-Equal (ConvertFrom-AcquisitionSecureString $withElsevier.Scopes.mineru.Token) "synthetic-token" "MinerU scope preserved after Elsevier update"
  Assert-Equal (ConvertFrom-AcquisitionSecureString $withElsevier.Scopes.api_keys.elsevier) "synthetic-elsevier-key" "Elsevier API key"

  Assert-Throws {
    & $bridgePath -ExpectedHost "idp.gxu.edu.cn.evil.example" -SecretPath $secretPath | Out-Null
  } "lookalike host must be rejected"
  $credentialJson = & $bridgePath -ExpectedHost "idp.gxu.edu.cn" -SecretPath $secretPath | ConvertFrom-Json
  Assert-Equal $credentialJson.username "synthetic-user" "bridge username"
  Assert-Equal $credentialJson.password "synthetic-password" "bridge password"
  foreach ($rejectedHost in @(
    "api.elsevier.com.evil.example",
    "www.sciencedirect.com",
    "API.ELSEVIER.COM."
  )) {
    Assert-Throws {
      & $elsevierBridgePath -ExpectedHost $rejectedHost -SecretPath $secretPath | Out-Null
    } "Elsevier lookalike or publisher host must be rejected: $rejectedHost"
  }
  $elsevierApiKey = & $elsevierBridgePath -ExpectedHost "api.elsevier.com" -SecretPath $secretPath
  Assert-Equal $elsevierApiKey "synthetic-elsevier-key" "Elsevier exact-host key bridge"
  $mineruToken = & $mineruPath -SecretPath $secretPath
  Assert-Equal $mineruToken "synthetic-token" "MinerU token bridge"

  $legacyPath = Join-Path $tempRoot "legacy.clixml"
  [pscustomobject]@{
    SchemaVersion = 1
    Organization = "Guangxi University"
    IeeeCredential = $credential
    MinerUToken = $token
  } | Export-Clixml -LiteralPath $legacyPath
  $migratedPath = Join-Path $tempRoot "migrated\secrets.clixml"
  $migration = & $migrationPath -LegacyPath $legacyPath -DestinationPath $migratedPath -Force | ConvertFrom-Json
  Assert-Equal $migration.status "migrated" "migration status"
  Assert-Equal (Import-AcquisitionSecrets -Path $migratedPath).Scopes.ieee_gxu.Credential.UserName "synthetic-user" "migrated username"

  Write-Output "PASS scoped DPAPI secret storage"
  Write-Output "PASS exact-host credential gate"
  Write-Output "PASS independent Elsevier API key scope"
  Write-Output "PASS standalone Elsevier API key setup"
  Write-Output "PASS legacy ciphertext migration"
}
finally {
  if (Test-Path -LiteralPath $tempRoot) {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force
  }
}
