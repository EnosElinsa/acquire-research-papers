param(
  [string]$Path = "",
  [switch]$Force
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "secret-store.ps1")

if ([string]::IsNullOrWhiteSpace($Path)) { $Path = Get-AcquisitionSecretPath }
if ((Test-Path -LiteralPath $Path) -and -not $Force) {
  throw "Secret file already exists. Re-run with -Force to replace it: $Path"
}

$usernameSecure = Read-Host "Guangxi University username" -AsSecureString
$password = Read-Host "Guangxi University password" -AsSecureString
$mineruToken = Read-Host "MinerU API token" -AsSecureString
$username = $null
try {
  $username = ConvertFrom-AcquisitionSecureString $usernameSecure
  if ([string]::IsNullOrWhiteSpace($username)) { throw "Username cannot be empty." }
  $credential = [Management.Automation.PSCredential]::new($username.Trim(), $password)
  Export-AcquisitionSecrets -IeeeCredential $credential -MinerUToken $mineruToken -Path $Path
  [ordered]@{ status = "stored"; path = $Path } | ConvertTo-Json -Compress
}
finally {
  $username = $null
  $credential = $null
}
