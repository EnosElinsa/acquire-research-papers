$ErrorActionPreference = "Stop"

function Assert-True([bool]$Condition, [string]$Message) {
  if (-not $Condition) { throw "ASSERT TRUE FAILED: $Message" }
}

function Assert-Equal($Actual, $Expected, [string]$Message) {
  if ($Actual -ne $Expected) {
    throw "ASSERT EQUAL FAILED: $Message expected=[$Expected] actual=[$Actual]"
  }
}

$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$script = Join-Path $root "scripts\install-playwright.ps1"
if (-not (Test-Path -LiteralPath $script -PathType Leaf)) {
  throw "Expected implementation file is missing: $script"
}

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("arp-playwright-test-" + [guid]::NewGuid().ToString("N"))
try {
  $localAppData = Join-Path $tempRoot "LocalAppData"
  $dependencyRoot = Join-Path $localAppData "Codex\deps\acquire-research-papers"
  $result = & $script -DependencyRoot $dependencyRoot -LocalAppData $localAppData -TestMode | ConvertFrom-Json
  Assert-Equal $result.status "planned" "test mode status"
  $package = Get-Content -Raw -LiteralPath (Join-Path $dependencyRoot "package.json") | ConvertFrom-Json
  Add-Type -AssemblyName System.Web.Extensions
  $serializer = [Web.Script.Serialization.JavaScriptSerializer]::new()
  $lock = $serializer.DeserializeObject((Get-Content -Raw -LiteralPath (Join-Path $dependencyRoot "package-lock.json")))
  $lockedPackage = $lock["packages"]["node_modules/playwright-core"]
  Assert-Equal $package.dependencies."playwright-core" "1.61.1" "pinned version"
  Assert-Equal $lockedPackage["version"] "1.61.1" "lock version"
  Assert-Equal $lockedPackage["resolved"] "https://registry.npmjs.org/playwright-core/-/playwright-core-1.61.1.tgz" "official tarball"
  Assert-Equal $lockedPackage["integrity"] "sha512-h7Qlt6m4REp25qvIdvbDtVmD4LqVXfpRxhORv9L0jzETM05p4fuPJ3dKyuSXQxDSbXnmS79HAgi9589lGSpLkg==" "pinned integrity"

  # New installations and ARP_DATA_ROOT use the runtime's own data root, not LocalAppData\Codex.
  $dataRoot = Join-Path $tempRoot "AppData\acquire-research-papers"
  $dataDependencies = Join-Path $dataRoot "deps\acquire-research-papers"
  $dataResult = & $script -DependencyRoot $dataDependencies -DataRoot $dataRoot -LocalAppData $localAppData -TestMode | ConvertFrom-Json
  Assert-Equal $dataResult.status "planned" "data-root test mode status"
  Assert-Equal $dataResult.dependencyRoot ([IO.Path]::GetFullPath($dataDependencies)) "data-root dependency path"
  $rejected = $false
  try { & $script -DependencyRoot $dependencyRoot -DataRoot $dataRoot -LocalAppData $localAppData -TestMode | Out-Null }
  catch { $rejected = $true }
  Assert-True $rejected "a dependency root outside the selected data root must be rejected"

  $text = Get-Content -Raw -LiteralPath $script
  Assert-True ($text.Contains("--ignore-scripts")) "npm lifecycle scripts must be disabled"
  Assert-True ($text.Contains("--no-audit")) "npm audit network call must be disabled"
  Write-Output "PASS integrity-pinned Playwright installer"
}
finally {
  if (Test-Path -LiteralPath $tempRoot) {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force
  }
}
