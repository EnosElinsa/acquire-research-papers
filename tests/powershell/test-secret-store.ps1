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
$migrationPath = Join-Path $root "scripts\migrate-legacy-secrets.ps1"
foreach ($required in @($storePath, $bridgePath, $migrationPath)) {
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

  Assert-Throws {
    & $bridgePath -ExpectedHost "idp.gxu.edu.cn.evil.example" -SecretPath $secretPath | Out-Null
  } "lookalike host must be rejected"
  $credentialJson = & $bridgePath -ExpectedHost "idp.gxu.edu.cn" -SecretPath $secretPath | ConvertFrom-Json
  Assert-Equal $credentialJson.username "synthetic-user" "bridge username"
  Assert-Equal $credentialJson.password "synthetic-password" "bridge password"

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
  Write-Output "PASS legacy ciphertext migration"
}
finally {
  if (Test-Path -LiteralPath $tempRoot) {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force
  }
}
