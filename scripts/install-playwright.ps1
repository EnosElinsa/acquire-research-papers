[CmdletBinding()]
param(
  [string]$DependencyRoot = "",
  [string]$LocalAppData = $env:LOCALAPPDATA,
  [string]$NpmPath = "",
  [switch]$TestMode
)

$ErrorActionPreference = "Stop"
$version = "1.61.1"
$registry = "https://registry.npmjs.org"
$tarball = "https://registry.npmjs.org/playwright-core/-/playwright-core-1.61.1.tgz"
$integrity = "sha512-h7Qlt6m4REp25qvIdvbDtVmD4LqVXfpRxhORv9L0jzETM05p4fuPJ3dKyuSXQxDSbXnmS79HAgi9589lGSpLkg=="

if ([string]::IsNullOrWhiteSpace($LocalAppData)) {
  throw "LOCALAPPDATA is unavailable; cannot resolve the dependency root."
}
$expectedRoot = [IO.Path]::GetFullPath((Join-Path $LocalAppData "Codex\deps\acquire-research-papers"))
if ([string]::IsNullOrWhiteSpace($DependencyRoot)) { $DependencyRoot = $expectedRoot }
$resolvedRoot = [IO.Path]::GetFullPath($DependencyRoot)
if (-not $resolvedRoot.Equals($expectedRoot, [StringComparison]::OrdinalIgnoreCase)) {
  throw "DependencyRoot must be the dedicated LocalAppData path: $expectedRoot"
}
New-Item -ItemType Directory -Path $resolvedRoot -Force | Out-Null

$packageManifest = [ordered]@{
  name = "acquire-research-papers-runtime"
  private = $true
  dependencies = [ordered]@{ "playwright-core" = $version }
} | ConvertTo-Json -Depth 4
$lockManifest = [ordered]@{
  name = "acquire-research-papers-runtime"
  lockfileVersion = 3
  requires = $true
  packages = [ordered]@{
    "" = [ordered]@{ dependencies = [ordered]@{ "playwright-core" = $version } }
    "node_modules/playwright-core" = [ordered]@{
      version = $version
      resolved = $tarball
      integrity = $integrity
    }
  }
} | ConvertTo-Json -Depth 8
Set-Content -LiteralPath (Join-Path $resolvedRoot "package.json") -Value $packageManifest -Encoding UTF8
Set-Content -LiteralPath (Join-Path $resolvedRoot "package-lock.json") -Value $lockManifest -Encoding UTF8

if ($TestMode) {
  [ordered]@{ status = "planned"; version = $version; dependencyRoot = $resolvedRoot } |
    ConvertTo-Json -Compress
  exit 0
}

if ([string]::IsNullOrWhiteSpace($NpmPath)) {
  $NpmPath = (Get-Command npm -ErrorAction Stop).Source
}
$arguments = @(
  "ci",
  "--prefix", $resolvedRoot,
  "--registry", $registry,
  "--ignore-scripts",
  "--no-audit",
  "--no-fund"
)
$output = & $NpmPath @arguments 2>&1
if ($LASTEXITCODE -ne 0) {
  $log = Join-Path $resolvedRoot "install-error.log"
  Set-Content -LiteralPath $log -Value ($output | Out-String) -Encoding UTF8
  throw "Could not install integrity-pinned playwright-core $version. See: $log"
}
$installedPackage = Get-Content -Raw -LiteralPath (Join-Path $resolvedRoot "node_modules\playwright-core\package.json") | ConvertFrom-Json
if ([string]$installedPackage.version -ne $version) {
  throw "Installed playwright-core version does not match the pinned version."
}
[ordered]@{ status = "installed"; version = $version; dependencyRoot = $resolvedRoot } |
  ConvertTo-Json -Compress
