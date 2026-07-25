param(
  [Parameter(Mandatory)][string]$ExpectedHost,
  [string]$SecretPath = ""
)

$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "read-discovery-api-key.ps1") `
  -Provider "elsevier" `
  -ExpectedHost $ExpectedHost `
  -SecretPath $SecretPath
