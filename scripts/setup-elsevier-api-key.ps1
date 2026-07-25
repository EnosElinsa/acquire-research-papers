param([string]$Path = "")

$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "setup-discovery-api-keys.ps1") `
  -Provider "elsevier" `
  -Path $Path `
  -Force
