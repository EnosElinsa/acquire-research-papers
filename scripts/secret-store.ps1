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

function Export-AcquisitionSecrets(
  [Management.Automation.PSCredential]$IeeeCredential,
  [Security.SecureString]$MinerUToken,
  [string]$Path = (Get-AcquisitionSecretPath)
) {
  if ($null -eq $IeeeCredential -or [string]::IsNullOrWhiteSpace($IeeeCredential.UserName)) {
    throw "IEEE institutional credential is missing."
  }
  if ($null -eq $MinerUToken -or $MinerUToken.Length -eq 0) {
    throw "MinerU token is missing."
  }
  $payload = [pscustomobject]@{
    SchemaVersion = 1
    Scopes = [pscustomobject]@{
      ieee_gxu = [pscustomobject]@{
        Organization = "Guangxi University"
        Credential = $IeeeCredential
      }
      mineru = [pscustomobject]@{
        Token = $MinerUToken
      }
      api_keys = [pscustomobject]@{}
    }
  }
  Save-AcquisitionSecretPayload -Payload $payload -Path $Path
}

function Set-ScienceDirectCredential(
  [Management.Automation.PSCredential]$Credential,
  [string]$Path = (Get-AcquisitionSecretPath)
) {
  if ($null -eq $Credential -or [string]::IsNullOrWhiteSpace($Credential.UserName)) {
    throw "ScienceDirect SCAU credential is missing."
  }
  $payload = Import-AcquisitionSecrets -Path $Path
  $scope = [pscustomobject]@{
    Organization = "South China Agricultural University"
    Credential = $Credential
  }
  if ($payload.Scopes.PSObject.Properties.Name -contains "sciencedirect_scau") {
    $payload.Scopes.sciencedirect_scau = $scope
  }
  else {
    $payload.Scopes | Add-Member -NotePropertyName sciencedirect_scau -NotePropertyValue $scope
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
  if ($payload.Scopes.ieee_gxu.Organization -ne "Guangxi University" -or
      $payload.Scopes.ieee_gxu.Credential -isnot [Management.Automation.PSCredential]) {
    throw "IEEE Guangxi University credential scope is missing or invalid."
  }
  if ($payload.Scopes.mineru.Token -isnot [Security.SecureString] -or
      $payload.Scopes.mineru.Token.Length -eq 0) {
    throw "MinerU token scope is missing or invalid."
  }
  if ($payload.Scopes.PSObject.Properties.Name -contains "sciencedirect_scau") {
    if ($payload.Scopes.sciencedirect_scau.Organization -ne "South China Agricultural University" -or
        $payload.Scopes.sciencedirect_scau.Credential -isnot [Management.Automation.PSCredential] -or
        [string]::IsNullOrWhiteSpace($payload.Scopes.sciencedirect_scau.Credential.UserName)) {
      throw "ScienceDirect SCAU credential scope is invalid."
    }
  }
  return $payload
}
