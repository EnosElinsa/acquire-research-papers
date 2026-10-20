$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../../scripts/secret-store.ps1')
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('arp-profiles-' + [guid]::NewGuid().ToString('N'))
$testPath = Join-Path $testRoot 'secrets.clixml'
try {
  $credential = [Management.Automation.PSCredential]::new('test-user', (ConvertTo-SecureString 'synthetic-password' -AsPlainText -Force))
  Set-IeeeNamedCredential -ProfileId 'first' -CredentialHost 'login.example.edu' -Credential $credential -Path $testPath
  Set-IeeeNamedCredential -ProfileId 'second' -CredentialHost 'sso.other.example.edu' -Credential $credential -Path $testPath
  $payload = Import-AcquisitionSecrets -Path $testPath
  if (@($payload.Scopes.ieee_profiles.PSObject.Properties.Name).Count -ne 2) { throw 'Expected both named credentials.' }
  $first = Get-IeeeNamedCredential -ProfileId 'first' -ExpectedHost 'login.example.edu' -Payload $payload
  if ($first.UserName -ne 'test-user') { throw 'Wrong named credential.' }
  $rejected = $false
  try { Get-IeeeNamedCredential -ProfileId 'first' -ExpectedHost 'login.example.edu.evil.test' -Payload $payload | Out-Null } catch { $rejected = $true }
  if (-not $rejected) { throw 'Lookalike host was accepted.' }
  Write-Output 'Named IEEE credential isolation tests passed.'
}
finally {
  if (Test-Path -LiteralPath $testRoot) {
    $resolvedTestRoot = [IO.Path]::GetFullPath($testRoot)
    if (-not $resolvedTestRoot.StartsWith([IO.Path]::GetTempPath(), [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe test cleanup path.' }
    Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
  }
}
