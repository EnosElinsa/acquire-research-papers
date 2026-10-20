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

function New-TestSecureString([string]$Value) {
  $secure = [Security.SecureString]::new()
  foreach ($character in $Value.ToCharArray()) {
    $secure.AppendChar($character)
  }
  $secure.MakeReadOnly()
  return $secure
}

$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$storePath = Join-Path $root "scripts\secret-store.ps1"
$bridgePath = Join-Path $root "scripts\read-browser-credential.ps1"
$profileBridgePath = Join-Path $root "scripts\read-institution-profile.ps1"
$ieeeSetupPath = Join-Path $root "scripts\setup-ieee-institution.ps1"
$ieeeEntityUpdatePath = Join-Path $root "scripts\update-ieee-institution-entity.ps1"
$ieeeRouteUpdatePath = Join-Path $root "scripts\update-ieee-institution-route.ps1"
$mineruSetupPath = Join-Path $root "scripts\setup-mineru-token.ps1"
$elsevierBridgePath = Join-Path $root "scripts\read-elsevier-api-key.ps1"
$elsevierSetupPath = Join-Path $root "scripts\setup-elsevier-api-key.ps1"
$discoveryBridgePath = Join-Path $root "scripts\read-discovery-api-key.ps1"
$discoverySetupPath = Join-Path $root "scripts\setup-discovery-api-keys.ps1"
$credentialStatusPath = Join-Path $root "scripts\credential-status.ps1"
$mineruPath = Join-Path $root "scripts\read-mineru-token.ps1"
$migrationPath = Join-Path $root "scripts\migrate-legacy-secrets.ps1"
foreach ($required in @(
  $storePath,
  $bridgePath,
  $profileBridgePath,
  $ieeeSetupPath,
  $ieeeEntityUpdatePath,
  $ieeeRouteUpdatePath,
  $mineruSetupPath,
  $elsevierBridgePath,
  $elsevierSetupPath,
  $discoveryBridgePath,
  $discoverySetupPath,
  $credentialStatusPath,
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
  $password = New-TestSecureString "synthetic-password"
  $token = New-TestSecureString "synthetic-token"
  $credential = [Management.Automation.PSCredential]::new("synthetic-user", $password)
  $elsevierKey = New-TestSecureString "synthetic-elsevier-key"
  $semanticScholarKey = New-TestSecureString "synthetic-semantic-key"
  $openAlexKey = New-TestSecureString "synthetic-openalex-key"
  $institution = [ordered]@{
    Organization = "Example University"
    CarsiSchoolPlaceholder = "Institution name"
    CarsiSearchText = "Example University"
    CarsiInstitution = "Example University (Example)"
    CarsiLoginButtonName = "Continue"
    CarsiEntityId = "https://login.example.edu/idp/shibboleth"
    CredentialHost = "login.example.edu"
    UsernameLabel = "Account"
    PasswordLabel = "Passcode"
    LoginButtonName = "Sign in"
    ResourceAccessUrl = "https://ds.carsi.edu.cn/resource/gotoResource.php?id=resource:example-ieee"
    AttributeReleaseTitle = "Release information"
    AttributeReleaseAcceptControlName = "_eventId_proceed"
    AttributeReleaseRejectControlName = "_eventId_AttributeReleaseRejected"
  }
  $sameAttributeControls = [ordered]@{}
  foreach ($entry in $institution.GetEnumerator()) {
    $sameAttributeControls[$entry.Key] = $entry.Value
  }
  $sameAttributeControls.AttributeReleaseAcceptControlName = $institution.AttributeReleaseRejectControlName
  Assert-Throws {
    ConvertTo-IeeeInstitutionProfile -Institution $sameAttributeControls | Out-Null
  } "IEEE accept and reject controls must be different"

  $elsevierOnlyPath = Join-Path $tempRoot "elsevier-only\secrets.clixml"
  Set-ElsevierApiKey -ApiKey $elsevierKey -Path $elsevierOnlyPath
  $elsevierOnly = Import-AcquisitionSecrets -Path $elsevierOnlyPath
  Assert-Equal (
    ConvertFrom-AcquisitionSecureString $elsevierOnly.Scopes.api_keys.elsevier
  ) "synthetic-elsevier-key" "standalone Elsevier API key"
  Assert-True (
    $elsevierOnly.Scopes.PSObject.Properties.Name -notcontains "ieee_institution"
  ) "Elsevier-only setup must not require an IEEE scope"
  Assert-True (
    $elsevierOnly.Scopes.PSObject.Properties.Name -notcontains "mineru"
  ) "Elsevier-only setup must not require a MinerU scope"

  Assert-Equal (Get-AcquisitionSecretPath $localAppData) $secretPath "default path"
  Set-IeeeInstitutionCredential `
    -Institution $institution `
    -Credential $credential `
    -Path $secretPath
  Set-MineruToken -Token $token -Path $secretPath
  $serialized = Get-Content -Raw -LiteralPath $secretPath
  Assert-True (-not $serialized.Contains("synthetic-password")) "password must stay encrypted"
  Assert-True (-not $serialized.Contains("synthetic-token")) "token must stay encrypted"

  $payload = Import-AcquisitionSecrets -Path $secretPath
  Assert-Equal $payload.SchemaVersion 1 "schema version"
  Assert-Equal $payload.Scopes.ieee_institution.Profile.Organization "Example University" "IEEE organization"
  Assert-Equal $payload.Scopes.ieee_institution.Profile.CarsiEntityId $institution.CarsiEntityId "IEEE CARSI entity ID"
  Assert-Equal $payload.Scopes.ieee_institution.Profile.CredentialHost "login.example.edu" "IEEE credential host"
  Assert-Equal $payload.Scopes.ieee_institution.Profile.ResourceAccessUrl $institution.ResourceAccessUrl "IEEE resource access URL"
  Assert-Equal $payload.Scopes.ieee_institution.Credential.UserName "synthetic-user" "username"
  Assert-Equal (ConvertFrom-AcquisitionSecureString $payload.Scopes.mineru.Token) "synthetic-token" "token"

  Set-ElsevierApiKey -ApiKey $elsevierKey -Path $secretPath
  Set-DiscoveryApiKey -Provider "semantic_scholar" -ApiKey $semanticScholarKey -Path $secretPath
  Set-DiscoveryApiKey -Provider "openalex" -ApiKey $openAlexKey -Path $secretPath
  $withElsevier = Import-AcquisitionSecrets -Path $secretPath
  $serialized = Get-Content -Raw -LiteralPath $secretPath
  Assert-True (-not $serialized.Contains("synthetic-elsevier-key")) "Elsevier key must stay encrypted"
  Assert-Equal $withElsevier.Scopes.ieee_institution.Credential.UserName "synthetic-user" "IEEE scope preserved after Elsevier update"
  Assert-Equal (ConvertFrom-AcquisitionSecureString $withElsevier.Scopes.mineru.Token) "synthetic-token" "MinerU scope preserved after Elsevier update"
  Assert-Equal (ConvertFrom-AcquisitionSecureString $withElsevier.Scopes.api_keys.elsevier) "synthetic-elsevier-key" "Elsevier API key"
  Assert-Equal (ConvertFrom-AcquisitionSecureString $withElsevier.Scopes.api_keys.semantic_scholar) "synthetic-semantic-key" "Semantic Scholar API key"
  Assert-Equal (ConvertFrom-AcquisitionSecureString $withElsevier.Scopes.api_keys.openalex) "synthetic-openalex-key" "OpenAlex API key"
  Assert-Equal $withElsevier.Scopes.ieee_institution.Credential.UserName "synthetic-user" "IEEE scope preserved after discovery API updates"

  foreach ($providerHost in @(
    @("semantic_scholar", "api.semanticscholar.org", "synthetic-semantic-key"),
    @("openalex", "api.openalex.org", "synthetic-openalex-key"),
    @("elsevier", "api.elsevier.com", "synthetic-elsevier-key")
  )) {
    $released = & $discoveryBridgePath `
      -Provider $providerHost[0] `
      -ExpectedHost $providerHost[1] `
      -SecretPath $secretPath
    Assert-Equal $released $providerHost[2] "exact-host discovery API key release"
  }
  foreach ($rejected in @(
    @("openalex", "api.openalex.org.evil.example"),
    @("openalex", "API.OPENALEX.ORG."),
    @("openalex", "https://api.openalex.org"),
    @("openalex", "api.openalex.org:443"),
    @("openalex", "api.openalex.org/works"),
    @("openalex", "*.openalex.org"),
    @("openalex", "api.semanticscholar.org")
  )) {
    Assert-Throws {
      & $discoveryBridgePath `
        -Provider $rejected[0] `
        -ExpectedHost $rejected[1] `
        -SecretPath $secretPath | Out-Null
    } "discovery API host boundary: $($rejected[1])"
  }

  $statusJson = & $credentialStatusPath -SecretPath $secretPath
  $status = $statusJson | ConvertFrom-Json
  Assert-True $status.ieee "IEEE capability status"
  Assert-True $status.mineru "MinerU capability status"
  Assert-True $status.elsevier "Elsevier capability status"
  Assert-True $status.semantic_scholar "Semantic Scholar capability status"
  Assert-True $status.openalex "OpenAlex capability status"
  foreach ($secret in @(
    "synthetic-password",
    "synthetic-token",
    "synthetic-elsevier-key",
    "synthetic-semantic-key",
    "synthetic-openalex-key"
  )) {
    Assert-True (-not $statusJson.Contains($secret)) "credential status must not reveal $secret"
  }
  $statusScriptText = Get-Content -Raw -LiteralPath $credentialStatusPath
  Assert-True (-not $statusScriptText.Contains("ConvertFrom-AcquisitionSecureString")) "credential status must not decrypt API keys"

  $emptyStatusPath = Join-Path $tempRoot "missing\secrets.clixml"
  $emptyStatus = (& $credentialStatusPath -SecretPath $emptyStatusPath) | ConvertFrom-Json
  Assert-True (-not $emptyStatus.ieee) "missing IEEE status"
  Assert-True (-not $emptyStatus.openalex) "missing OpenAlex status"
  $missingValue = & $discoveryBridgePath `
    -Provider "openalex" `
    -ExpectedHost "api.openalex.org" `
    -SecretPath $emptyStatusPath `
    -AllowMissing
  Assert-True ($null -eq $missingValue) "optional missing discovery API key"

  Assert-Throws {
    & $bridgePath -ExpectedHost "login.example.edu.evil.example" -SecretPath $secretPath | Out-Null
  } "lookalike host must be rejected"
  Assert-Throws {
    & $bridgePath -ExpectedHost "login.example.edu." -SecretPath $secretPath | Out-Null
  } "trailing-dot host must be rejected"
  $credentialJson = & $bridgePath -ExpectedHost "LOGIN.EXAMPLE.EDU" -SecretPath $secretPath | ConvertFrom-Json
  Assert-Equal $credentialJson.username "synthetic-user" "bridge username"
  Assert-Equal $credentialJson.password "synthetic-password" "bridge password"
  $profileJson = & $profileBridgePath -SecretPath $secretPath | ConvertFrom-Json
  Assert-Equal $profileJson.organization "Example University" "profile organization"
  Assert-Equal $profileJson.carsiEntityId $institution.CarsiEntityId "profile CARSI entity ID"
  Assert-Equal $profileJson.credentialHost "login.example.edu" "profile credential host"
  Assert-Equal $profileJson.usernameLabel "Account" "profile username label"
  Assert-Equal $profileJson.resourceAccessUrl $institution.ResourceAccessUrl "profile resource access URL"
  Assert-Equal $profileJson.attributeReleaseAcceptControlName "_eventId_proceed" "profile exact accept control"
  Assert-Equal $profileJson.attributeReleaseRejectControlName "_eventId_AttributeReleaseRejected" "profile exact reject control"
  Assert-True ($profileJson.PSObject.Properties.Name -notcontains "username") "profile bridge must not release username"
  Assert-True ($profileJson.PSObject.Properties.Name -notcontains "password") "profile bridge must not release password"

  $incompletePath = Join-Path $tempRoot "incomplete-entity\secrets.clixml"
  $incompletePayload = Import-Clixml -LiteralPath $secretPath
  $incompletePayload.Scopes.ieee_institution.Profile.PSObject.Properties.Remove("CarsiEntityId")
  Save-AcquisitionSecretPayload -Payload $incompletePayload -Path $incompletePath
  $incompleteStatus = (& $credentialStatusPath -SecretPath $incompletePath) | ConvertFrom-Json
  Assert-True (-not $incompleteStatus.ieee) "malformed IEEE profile must not report configured"
  $entityUpdate = & $ieeeEntityUpdatePath `
    -Path $incompletePath `
    -CarsiEntityId "https://login.example.edu/idp/shibboleth" | ConvertFrom-Json
  Assert-Equal $entityUpdate.status "updated" "entity update status"
  $upgradedPayload = Import-AcquisitionSecrets -Path $incompletePath
  Assert-Equal $upgradedPayload.Scopes.ieee_institution.Profile.CarsiEntityId "https://login.example.edu/idp/shibboleth" "incomplete profile entity upgrade"
  Assert-Equal $upgradedPayload.Scopes.ieee_institution.Credential.UserName "synthetic-user" "entity upgrade preserves credential"
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
    Organization = "Legacy Example University"
    IeeeCredential = $credential
    MinerUToken = $token
  } | Export-Clixml -LiteralPath $legacyPath
  $migratedPath = Join-Path $tempRoot "migrated\secrets.clixml"
  $migration = & $migrationPath `
    -LegacyPath $legacyPath `
    -DestinationPath $migratedPath `
    -CarsiSchoolPlaceholder $institution.CarsiSchoolPlaceholder `
    -CarsiSearchText $institution.CarsiSearchText `
    -CarsiInstitution $institution.CarsiInstitution `
    -CarsiLoginButtonName $institution.CarsiLoginButtonName `
    -CarsiEntityId $institution.CarsiEntityId `
    -CredentialHost $institution.CredentialHost `
    -UsernameLabel $institution.UsernameLabel `
    -PasswordLabel $institution.PasswordLabel `
    -LoginButtonName $institution.LoginButtonName `
    -ResourceAccessUrl $institution.ResourceAccessUrl `
    -AttributeReleaseTitle $institution.AttributeReleaseTitle `
    -AttributeReleaseAcceptControlName $institution.AttributeReleaseAcceptControlName `
    -AttributeReleaseRejectControlName $institution.AttributeReleaseRejectControlName `
    -Force | ConvertFrom-Json
  Assert-Equal $migration.status "migrated" "migration status"
  $migrated = Import-AcquisitionSecrets -Path $migratedPath
  Assert-Equal $migrated.Scopes.ieee_institution.Profile.Organization "Legacy Example University" "migrated organization"
  Assert-Equal $migrated.Scopes.ieee_institution.Credential.UserName "synthetic-user" "migrated username"

  $legacyScopedPath = Join-Path $tempRoot "legacy-scoped.clixml"
  [pscustomobject]@{
    SchemaVersion = 1
    Scopes = [pscustomobject]@{
      institutional_access = [pscustomobject]@{
        Organization = "Scoped Example University"
        Credential = $credential
      }
      mineru = [pscustomobject]@{ Token = $token }
    }
  } | Export-Clixml -LiteralPath $legacyScopedPath
  $migratedScopedPath = Join-Path $tempRoot "migrated-scoped\secrets.clixml"
  & $migrationPath `
    -LegacyPath $legacyScopedPath `
    -DestinationPath $migratedScopedPath `
    -CarsiSchoolPlaceholder $institution.CarsiSchoolPlaceholder `
    -CarsiSearchText $institution.CarsiSearchText `
    -CarsiInstitution $institution.CarsiInstitution `
    -CarsiLoginButtonName $institution.CarsiLoginButtonName `
    -CarsiEntityId $institution.CarsiEntityId `
    -CredentialHost $institution.CredentialHost `
    -UsernameLabel $institution.UsernameLabel `
    -PasswordLabel $institution.PasswordLabel `
    -LoginButtonName $institution.LoginButtonName `
    -ResourceAccessUrl $institution.ResourceAccessUrl `
    -AttributeReleaseTitle $institution.AttributeReleaseTitle `
    -AttributeReleaseAcceptControlName $institution.AttributeReleaseAcceptControlName `
    -AttributeReleaseRejectControlName $institution.AttributeReleaseRejectControlName `
    -Force | Out-Null
  $migratedScoped = Import-AcquisitionSecrets -Path $migratedScopedPath
  Assert-Equal $migratedScoped.Scopes.ieee_institution.Profile.Organization "Scoped Example University" "migrated scoped organization"
  Assert-Equal $migratedScoped.Scopes.ieee_institution.Credential.UserName "synthetic-user" "migrated scoped username"

  $invalidPath = Join-Path $tempRoot "invalid\secrets.clixml"
  $invalidInstitution = [ordered]@{}
  foreach ($name in $institution.Keys) { $invalidInstitution[$name] = $institution[$name] }
  $invalidInstitution.CredentialHost = "https://login.example.edu/path"
  Assert-Throws {
    Set-IeeeInstitutionCredential -Institution $invalidInstitution -Credential $credential -Path $invalidPath
  } "credential host must be an exact hostname without scheme or path"
  $invalidInstitution.CredentialHost = "localhost"
  Assert-Throws {
    Set-IeeeInstitutionCredential -Institution $invalidInstitution -Credential $credential -Path $invalidPath
  } "credential host must be a fully qualified DNS hostname"

  $setupValues = @{
    "Institution display name" = "Setup Example University"
    "CARSI institution-search placeholder" = "Institution name"
    "CARSI search text" = "Setup Example University"
    "Exact CARSI institution option" = "Setup Example University (Example)"
    "CARSI login button name" = "Continue"
    "Exact CARSI IdP entity ID (HTTPS URL)" = "https://setup.example.edu/idp/shibboleth"
    "Exact institutional IdP hostname (no scheme or path)" = "setup.example.edu"
    "Username field label" = "Account"
    "Password field label" = "Passcode"
    "Institution login button name" = "Sign in"
    "CARSI post-login IEEE resource access URL" = "https://ds.carsi.edu.cn/resource/gotoResource.php?id=resource:setup-ieee"
    "Optional official IEEE WAYF URL" = "https://ieeexplore.ieee.org/servlet/wayf.jsp?entityId=https://setup.example.edu/idp/shibboleth&url=https%3A%2F%2Fieeexplore.ieee.org%2FXplore%2Fhome.jsp"
    "Optional exact attribute-release page title" = ""
    "Optional exact attribute-release accept control name" = ""
    "Optional exact attribute-release reject control name" = ""
  }
  function global:Read-Host {
    param([string]$Prompt, [switch]$AsSecureString)
    if ($AsSecureString) {
      $value = switch ($Prompt) {
        "Institution username" { "setup-user" }
        "Institution password" { "setup-password" }
        "MinerU API token" { "setup-token" }
        "Semantic Scholar API key" { "setup-semantic-key" }
        "OpenAlex API key" { "setup-openalex-key" }
        "Elsevier API key" { "setup-elsevier-key" }
        default { "setup-value" }
      }
      return New-TestSecureString $value
    }
    return $setupValues[$Prompt]
  }
  $setupPath = Join-Path $tempRoot "setup\secrets.clixml"
  & $ieeeSetupPath -Path $setupPath -Force | Out-Null
  $setupPayload = Import-AcquisitionSecrets -Path $setupPath
  Assert-Equal $setupPayload.Scopes.ieee_institution.Profile.Organization "Setup Example University" "interactive IEEE setup"
  Assert-Equal $setupPayload.Scopes.ieee_institution.Profile.CarsiEntityId "https://setup.example.edu/idp/shibboleth" "interactive CARSI entity ID"
  Assert-Equal $setupPayload.Scopes.ieee_institution.Profile.CredentialHost "setup.example.edu" "interactive host setup"
  Assert-Equal $setupPayload.Scopes.ieee_institution.Profile.ResourceAccessUrl "https://ds.carsi.edu.cn/resource/gotoResource.php?id=resource:setup-ieee" "interactive resource route setup"
  Assert-Equal $setupPayload.Scopes.ieee_institution.Profile.IeeeWayfUrl "https://ieeexplore.ieee.org/servlet/wayf.jsp?entityId=https://setup.example.edu/idp/shibboleth&url=https%3A%2F%2Fieeexplore.ieee.org%2FXplore%2Fhome.jsp" "interactive IEEE WAYF setup"

  $routeUpdate = & $ieeeRouteUpdatePath `
    -Path $setupPath `
    -ResourceAccessUrl "https://ds.carsi.edu.cn/resource/gotoResource.php?id=resource:updated-ieee" `
    -AttributeReleaseTitle "Information release" `
    -AttributeReleaseAcceptControlName "_eventId_proceed" `
    -AttributeReleaseRejectControlName "_eventId_reject" | ConvertFrom-Json
  Assert-Equal $routeUpdate.status "updated" "route update status"
  $updatedSetupPayload = Import-AcquisitionSecrets -Path $setupPath
  Assert-Equal $updatedSetupPayload.Scopes.ieee_institution.Profile.ResourceAccessUrl "https://ds.carsi.edu.cn/resource/gotoResource.php?id=resource:updated-ieee" "updated resource route"
  Assert-Equal $updatedSetupPayload.Scopes.ieee_institution.Profile.IeeeWayfUrl "https://ieeexplore.ieee.org/servlet/wayf.jsp?entityId=https://setup.example.edu/idp/shibboleth&url=https%3A%2F%2Fieeexplore.ieee.org%2FXplore%2Fhome.jsp" "route update preserves IEEE WAYF"
  Assert-Equal $updatedSetupPayload.Scopes.ieee_institution.Credential.UserName "setup-user" "route update preserves DPAPI credential"
  Set-IeeeInstitutionEntityId -CarsiEntityId "https://setup.example.edu/idp/shibboleth-v2" -Path $setupPath
  $entityUpdatedSetupPayload = Import-AcquisitionSecrets -Path $setupPath
  Assert-Equal $entityUpdatedSetupPayload.Scopes.ieee_institution.Profile.IeeeWayfUrl "https://ieeexplore.ieee.org/servlet/wayf.jsp?entityId=https://setup.example.edu/idp/shibboleth&url=https%3A%2F%2Fieeexplore.ieee.org%2FXplore%2Fhome.jsp" "entity update preserves IEEE WAYF"
  & $mineruSetupPath -Path $setupPath -Force | Out-Null
  Assert-Equal (ConvertFrom-AcquisitionSecureString (Import-AcquisitionSecrets -Path $setupPath).Scopes.mineru.Token) "setup-token" "interactive MinerU setup"
  $discoverySetupOnlyPath = Join-Path $tempRoot "discovery-setup\secrets.clixml"
  $discoverySetupOutput = & $discoverySetupPath `
    -Provider @("semantic_scholar", "openalex") `
    -Path $discoverySetupOnlyPath `
    -Force
  $discoverySetupPayload = Import-AcquisitionSecrets -Path $discoverySetupOnlyPath
  Assert-Equal (ConvertFrom-AcquisitionSecureString $discoverySetupPayload.Scopes.api_keys.semantic_scholar) "setup-semantic-key" "interactive Semantic Scholar setup"
  Assert-Equal (ConvertFrom-AcquisitionSecureString $discoverySetupPayload.Scopes.api_keys.openalex) "setup-openalex-key" "interactive OpenAlex setup"
  Assert-True (($discoverySetupOutput -join "`n").Contains('"status":"stored"')) "interactive setup reports completion"
  function global:Read-Host {
    param([string]$Prompt, [switch]$AsSecureString)
    if ($AsSecureString) { return New-TestSecureString "" }
    return ""
  }
  $skippedSetupPath = Join-Path $tempRoot "discovery-skipped\secrets.clixml"
  $skippedSetupOutput = & $discoverySetupPath `
    -Provider "openalex" `
    -Path $skippedSetupPath
  Assert-True (($skippedSetupOutput -join "`n").Contains('"status":"skipped"')) "blank optional API key reports skipped"
  Assert-True (-not (Test-Path -LiteralPath $skippedSetupPath)) "skipped optional API key must not create a secret file"
  Remove-Item Function:\global:Read-Host -ErrorAction SilentlyContinue

  Write-Output "PASS scoped DPAPI secret storage"
  Write-Output "PASS user-configured exact-host credential gate"
  Write-Output "PASS independent Elsevier API key scope"
  Write-Output "PASS standalone Elsevier API key setup"
  Write-Output "PASS legacy ciphertext migration"
  Write-Output "PASS independent interactive institution setup"
  Write-Output "PASS provider-neutral discovery API scopes"
  Write-Output "PASS capability-only credential status"
}
finally {
  if (Test-Path -LiteralPath $tempRoot) {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force
  }
}
