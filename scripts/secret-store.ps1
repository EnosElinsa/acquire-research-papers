$ErrorActionPreference = "Stop"

function Get-AcquisitionSecretPath([string]$LocalAppData = $env:LOCALAPPDATA) {
  if ([string]::IsNullOrWhiteSpace($LocalAppData)) {
    throw "LOCALAPPDATA is unavailable; cannot resolve the DPAPI secret path."
  }
  return (Join-Path $LocalAppData "Codex\secrets\acquire-research-papers\secrets.clixml")
}

function ConvertFrom-AcquisitionSecureString([Security.SecureString]$Value) {
  if ($null -eq $Value) { throw "Secure value is missing." }
  $pointer = [IntPtr]::Zero
  try {
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
  }
  finally {
    if ($pointer -ne [IntPtr]::Zero) {
      [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
  }
}

function Set-AcquisitionSecretAcl([string]$Path) {
  $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
  $icacls = Join-Path $env:SystemRoot "System32\icacls.exe"
  if (-not (Test-Path -LiteralPath $icacls)) {
    throw "icacls.exe is unavailable; cannot restrict the secret file ACL."
  }
  & $icacls $Path "/inheritance:e" "/grant:r" "${identity}:(F)" | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Failed to restrict the secret file ACL." }
}

function Save-AcquisitionSecretPayload(
  [psobject]$Payload,
  [string]$Path = (Get-AcquisitionSecretPath)
) {
  if ($null -eq $Payload) { throw "Secret payload is missing." }
  if ([string]::IsNullOrWhiteSpace($Path)) { throw "Secret path is missing." }

  $parent = Split-Path -Parent $Path
  if ([string]::IsNullOrWhiteSpace($parent)) { throw "Secret path must include a parent directory." }
  New-Item -ItemType Directory -Path $parent -Force | Out-Null
  $temporaryPath = "$Path.$([guid]::NewGuid().ToString('N')).tmp"
  try {
    $Payload | Export-Clixml -LiteralPath $temporaryPath
    Set-AcquisitionSecretAcl -Path $temporaryPath
    Move-Item -LiteralPath $temporaryPath -Destination $Path -Force
    Set-AcquisitionSecretAcl -Path $Path
  }
  finally {
    if (Test-Path -LiteralPath $temporaryPath) {
      Remove-Item -LiteralPath $temporaryPath -Force
    }
  }
}

function New-AcquisitionSecretPayload {
  return [pscustomobject]@{
    SchemaVersion = 1
    Scopes = [pscustomobject]@{}
  }
}

function Get-AcquisitionProfileValue([object]$Profile, [string]$Name) {
  if ($null -eq $Profile) { return "" }
  if ($Profile -is [Collections.IDictionary]) {
    return [string]$Profile[$Name]
  }
  $property = $Profile.PSObject.Properties[$Name]
  if ($null -eq $property) { return "" }
  return [string]$property.Value
}

function ConvertTo-IeeeInstitutionProfile([object]$Institution) {
  $required = @(
    "Organization",
    "CarsiSchoolPlaceholder",
    "CarsiSearchText",
    "CarsiInstitution",
    "CarsiLoginButtonName",
    "CredentialHost",
    "UsernameLabel",
    "PasswordLabel",
    "LoginButtonName"
  )
  $values = @{}
  foreach ($name in $required) {
    $value = (Get-AcquisitionProfileValue -Profile $Institution -Name $name).Trim()
    if ([string]::IsNullOrWhiteSpace($value)) {
      throw "IEEE institution profile field is missing: $name"
    }
    $values[$name] = $value
  }
  $credentialHost = $values.CredentialHost
  if (-not $credentialHost.Contains(".") -or $credentialHost.EndsWith(".") -or
      $credentialHost.Contains(":") -or
      $credentialHost.Contains("/") -or $credentialHost.Contains("*") -or
      [Uri]::CheckHostName($credentialHost) -ne [UriHostNameType]::Dns) {
    throw "IEEE credential host must be one exact DNS hostname without scheme, port, path, wildcard, or trailing dot."
  }
  $values.CredentialHost = $credentialHost.ToLowerInvariant()
  $resourceAccessUrl = (Get-AcquisitionProfileValue -Profile $Institution -Name "ResourceAccessUrl").Trim()
  if (-not [string]::IsNullOrWhiteSpace($resourceAccessUrl)) {
    $resourceUri = $null
    if (-not [Uri]::TryCreate($resourceAccessUrl, [UriKind]::Absolute, [ref]$resourceUri) -or
        $resourceUri.Scheme -ne "https" -or
        $resourceUri.DnsSafeHost -ne "ds.carsi.edu.cn" -or
        -not $resourceUri.IsDefaultPort -or
        -not [string]::IsNullOrWhiteSpace($resourceUri.UserInfo) -or
        -not [string]::IsNullOrWhiteSpace($resourceUri.Fragment)) {
      throw "IEEE resource access URL must use the exact ds.carsi.edu.cn HTTPS host without credentials, a custom port, or a fragment."
    }
    $resourceAccessUrl = $resourceUri.AbsoluteUri
  }
  $attributeReleaseTitle = (
    Get-AcquisitionProfileValue -Profile $Institution -Name "AttributeReleaseTitle"
  ).Trim()
  $attributeReleaseAccept = (
    Get-AcquisitionProfileValue -Profile $Institution -Name "AttributeReleaseAcceptControlName"
  ).Trim()
  $attributeReleaseReject = (
    Get-AcquisitionProfileValue -Profile $Institution -Name "AttributeReleaseRejectControlName"
  ).Trim()
  $configuredReleaseFields = @(
    $attributeReleaseTitle,
    $attributeReleaseAccept,
    $attributeReleaseReject
  ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
  if ($configuredReleaseFields.Count -ne 0 -and $configuredReleaseFields.Count -ne 3) {
    throw "AttributeReleaseTitle, AttributeReleaseAcceptControlName, and AttributeReleaseRejectControlName must all be provided or all be empty."
  }
  foreach ($controlName in @($attributeReleaseAccept, $attributeReleaseReject)) {
    if (-not [string]::IsNullOrWhiteSpace($controlName) -and $controlName -notmatch '^[A-Za-z0-9_-]+$') {
      throw "IEEE attribute-release control names may contain only letters, digits, underscores, and hyphens."
    }
  }
  return [pscustomobject]@{
    Organization = $values.Organization
    CarsiSchoolPlaceholder = $values.CarsiSchoolPlaceholder
    CarsiSearchText = $values.CarsiSearchText
    CarsiInstitution = $values.CarsiInstitution
    CarsiLoginButtonName = $values.CarsiLoginButtonName
    CredentialHost = $values.CredentialHost
    UsernameLabel = $values.UsernameLabel
    PasswordLabel = $values.PasswordLabel
    LoginButtonName = $values.LoginButtonName
    ResourceAccessUrl = $resourceAccessUrl
    AttributeReleaseTitle = $attributeReleaseTitle
    AttributeReleaseAcceptControlName = $attributeReleaseAccept
    AttributeReleaseRejectControlName = $attributeReleaseReject
  }
}

function Get-OrCreateAcquisitionSecretPayload([string]$Path) {
  if (Test-Path -LiteralPath $Path -PathType Leaf) {
    return Import-AcquisitionSecrets -Path $Path
  }
  return New-AcquisitionSecretPayload
}

function Set-IeeeInstitutionCredential(
  [object]$Institution,
  [Management.Automation.PSCredential]$Credential,
  [string]$Path = (Get-AcquisitionSecretPath)
) {
  if ($null -eq $Credential -or [string]::IsNullOrWhiteSpace($Credential.UserName)) {
    throw "IEEE institutional credential is missing."
  }
  $profile = ConvertTo-IeeeInstitutionProfile -Institution $Institution
  $payload = Get-OrCreateAcquisitionSecretPayload -Path $Path
  $scope = [pscustomobject]@{
    Profile = $profile
    Credential = $Credential
  }
  if ($payload.Scopes.PSObject.Properties.Name -contains "ieee_institution") {
    $payload.Scopes.ieee_institution = $scope
  }
  else {
    $payload.Scopes | Add-Member -NotePropertyName ieee_institution -NotePropertyValue $scope
  }
  Save-AcquisitionSecretPayload -Payload $payload -Path $Path
}

function Set-IeeeInstitutionRoute(
  [string]$ResourceAccessUrl,
  [string]$AttributeReleaseTitle = "",
  [string]$AttributeReleaseAcceptControlName = "",
  [string]$AttributeReleaseRejectControlName = "",
  [string]$Path = (Get-AcquisitionSecretPath)
) {
  $payload = Import-AcquisitionSecrets -Path $Path
  if ($payload.Scopes.PSObject.Properties.Name -notcontains "ieee_institution") {
    throw "IEEE institution profile is not configured."
  }
  $existing = $payload.Scopes.ieee_institution.Profile
  $institution = [ordered]@{
    Organization = $existing.Organization
    CarsiSchoolPlaceholder = $existing.CarsiSchoolPlaceholder
    CarsiSearchText = $existing.CarsiSearchText
    CarsiInstitution = $existing.CarsiInstitution
    CarsiLoginButtonName = $existing.CarsiLoginButtonName
    CredentialHost = $existing.CredentialHost
    UsernameLabel = $existing.UsernameLabel
    PasswordLabel = $existing.PasswordLabel
    LoginButtonName = $existing.LoginButtonName
    ResourceAccessUrl = $ResourceAccessUrl
    AttributeReleaseTitle = $AttributeReleaseTitle
    AttributeReleaseAcceptControlName = $AttributeReleaseAcceptControlName
    AttributeReleaseRejectControlName = $AttributeReleaseRejectControlName
  }
  $payload.Scopes.ieee_institution.Profile = ConvertTo-IeeeInstitutionProfile -Institution $institution
  Save-AcquisitionSecretPayload -Payload $payload -Path $Path
}

function Set-MineruToken(
  [Security.SecureString]$Token,
  [string]$Path = (Get-AcquisitionSecretPath)
) {
  if ($null -eq $Token -or $Token.Length -eq 0) {
    throw "MinerU token is missing."
  }
  $payload = Get-OrCreateAcquisitionSecretPayload -Path $Path
  $scope = [pscustomobject]@{ Token = $Token }
  if ($payload.Scopes.PSObject.Properties.Name -contains "mineru") {
    $payload.Scopes.mineru = $scope
  }
  else {
    $payload.Scopes | Add-Member -NotePropertyName mineru -NotePropertyValue $scope
  }
  Save-AcquisitionSecretPayload -Payload $payload -Path $Path
}

function Set-ElsevierApiKey(
  [Security.SecureString]$ApiKey,
  [string]$Path = (Get-AcquisitionSecretPath)
) {
  if ($null -eq $ApiKey -or $ApiKey.Length -eq 0) {
    throw "Elsevier API key is missing."
  }
  if (Test-Path -LiteralPath $Path -PathType Leaf) {
    $payload = Import-AcquisitionSecrets -Path $Path
  }
  else {
    $payload = New-AcquisitionSecretPayload
  }
  if ($payload.Scopes.PSObject.Properties.Name -notcontains "api_keys") {
    $payload.Scopes | Add-Member -NotePropertyName api_keys -NotePropertyValue ([pscustomobject]@{})
  }
  if ($payload.Scopes.api_keys.PSObject.Properties.Name -contains "elsevier") {
    $payload.Scopes.api_keys.elsevier = $ApiKey
  }
  else {
    $payload.Scopes.api_keys |
      Add-Member -NotePropertyName elsevier -NotePropertyValue $ApiKey
  }
  Save-AcquisitionSecretPayload -Payload $payload -Path $Path
}

function Import-AcquisitionSecrets([string]$Path = (Get-AcquisitionSecretPath)) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "DPAPI secret file is missing: $Path"
  }
  $payload = Import-Clixml -LiteralPath $Path
  if ($null -eq $payload -or [int]$payload.SchemaVersion -ne 1 -or $null -eq $payload.Scopes) {
    throw "Unsupported acquisition secret schema."
  }
  if ($payload.Scopes.PSObject.Properties.Name -contains "ieee_institution") {
    $scope = $payload.Scopes.ieee_institution
    if ($scope.Credential -isnot [Management.Automation.PSCredential]) {
      throw "IEEE institution credential scope is invalid."
    }
    $scope.Profile = ConvertTo-IeeeInstitutionProfile -Institution $scope.Profile
  }
  if ($payload.Scopes.PSObject.Properties.Name -contains "mineru") {
    if ($payload.Scopes.mineru.Token -isnot [Security.SecureString] -or
        $payload.Scopes.mineru.Token.Length -eq 0) {
      throw "MinerU token scope is invalid."
    }
  }
  if ($payload.Scopes.PSObject.Properties.Name -contains "api_keys" -and
      $payload.Scopes.api_keys.PSObject.Properties.Name -contains "elsevier") {
    if ($payload.Scopes.api_keys.elsevier -isnot [Security.SecureString] -or
        $payload.Scopes.api_keys.elsevier.Length -eq 0) {
      throw "Elsevier API key scope is invalid."
    }
  }
  return $payload
}
