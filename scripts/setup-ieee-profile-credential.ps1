param(
  [Parameter(Mandatory)][string]$ProfileId,
  [Parameter(Mandatory)][string]$CredentialHost,
  [string]$Path = ''
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'secret-store.ps1')
if ([string]::IsNullOrWhiteSpace($Path)) { $Path = Get-AcquisitionSecretPath }
Write-Host "Save credentials only for exact host: $CredentialHost"
$accountSecure = Read-Host 'Institution username' -AsSecureString
$passwordSecure = Read-Host 'Institution password' -AsSecureString
$account = $null
try {
  $account = ConvertFrom-AcquisitionSecureString $accountSecure
  $credential = [Management.Automation.PSCredential]::new($account, $passwordSecure)
  Set-IeeeNamedCredential -ProfileId $ProfileId -CredentialHost $CredentialHost -Credential $credential -Path $Path
}
finally { $account = $null; $credential = $null; $passwordSecure = $null; $accountSecure = $null }
