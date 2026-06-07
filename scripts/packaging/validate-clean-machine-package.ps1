param(
  [string]$PackageRoot = "",
  [string]$ReportPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $PackageRoot) {
  $PackageRoot = Join-Path $repoRoot "apps\desktop\dist\win-unpacked"
}
if (-not $ReportPath) {
  $ReportPath = Join-Path $repoRoot "tmp\clean-machine-package-validation.json"
}

function Test-PathPresent([string]$PathValue) {
  return [bool](Test-Path $PathValue)
}

$packageRootPath = [System.IO.Path]::GetFullPath($PackageRoot)
$resources = Join-Path $packageRootPath "resources"
$runtimePython = Join-Path $resources "python-runtime\Scripts\python.exe"
$expertRuntimePython = Join-Path $resources "expert-python-runtime\Scripts\python.exe"
$backend = Join-Path $resources "backend"
$ocrManifest = Join-Path $backend "bin\ocr\manifest.json"
$playwrightRuntime = Join-Path $resources "ms-playwright"
$helperManifest = Join-Path $resources "helper-manifest.json"
$checks = @(
  @{ name = "package_root_exists"; ok = Test-PathPresent $packageRootPath; path = $packageRootPath },
  @{ name = "resources_exists"; ok = Test-PathPresent $resources; path = $resources },
  @{ name = "backend_exists"; ok = Test-PathPresent $backend; path = $backend },
  @{ name = "python_runtime_exists"; ok = Test-PathPresent $runtimePython; path = $runtimePython },
  @{ name = "expert_python_runtime_exists"; ok = Test-PathPresent $expertRuntimePython; path = $expertRuntimePython },
  @{ name = "playwright_runtime_exists"; ok = Test-PathPresent $playwrightRuntime; path = $playwrightRuntime },
  @{ name = "ocr_manifest_exists"; ok = Test-PathPresent $ocrManifest; path = $ocrManifest },
  @{ name = "helper_manifest_exists"; ok = Test-PathPresent $helperManifest; path = $helperManifest },
  @{ name = "app_launch_smoke_exists"; ok = Test-PathPresent (Join-Path $repoRoot "scripts\packaging\smoke-packaged-app-launch.ps1"); path = "scripts/packaging/smoke-packaged-app-launch.ps1" },
  @{ name = "runtime_smoke_exists"; ok = Test-PathPresent (Join-Path $repoRoot "scripts\packaging\smoke-packaged-runtime.ps1"); path = "scripts/packaging/smoke-packaged-runtime.ps1" },
  @{ name = "full_vault_smoke_exists"; ok = Test-PathPresent (Join-Path $repoRoot "scripts\packaging\smoke-packaged-full-vault.ps1"); path = "scripts/packaging/smoke-packaged-full-vault.ps1" },
  @{ name = "dynamic_link_smoke_exists"; ok = Test-PathPresent (Join-Path $repoRoot "scripts\packaging\smoke-packaged-dynamic-link.ps1"); path = "scripts/packaging/smoke-packaged-dynamic-link.ps1" },
  @{ name = "migration_drill_exists"; ok = Test-PathPresent (Join-Path $repoRoot "scripts\packaging\smoke-packaged-migration-drill.ps1"); path = "scripts/packaging/smoke-packaged-migration-drill.ps1" },
  @{ name = "package_layout_audit_exists"; ok = Test-PathPresent (Join-Path $repoRoot "scripts\packaging\audit-package-layout.cjs"); path = "scripts/packaging/audit-package-layout.cjs" }
)

$hostTools = @(
  @{ name = "python_on_path"; detected = [bool](Get-Command python -ErrorAction SilentlyContinue) },
  @{ name = "node_on_path"; detected = [bool](Get-Command node -ErrorAction SilentlyContinue) },
  @{ name = "tesseract_on_path"; detected = [bool](Get-Command tesseract -ErrorAction SilentlyContinue) },
  @{ name = "gs_on_path"; detected = [bool](Get-Command gswin64c -ErrorAction SilentlyContinue) }
)

$report = [ordered]@{
  generated_at = (Get-Date).ToUniversalTime().ToString("o")
  package_root = $packageRootPath
  intent = "Contributor clean-machine validation plan. Run this before handing a package to another tester."
  pass = ($checks | Where-Object { -not $_.ok }).Count -eq 0
  checks = $checks
  host_tool_findings = $hostTools
  clean_vm_rule = "For public-quality validation, rerun on a Windows VM where python_on_path, node_on_path, tesseract_on_path, and gs_on_path are false."
  manual_validation_order = @(
    "Run scripts/packaging/smoke-packaged-runtime.ps1 against the package root.",
    "Run scripts/packaging/smoke-packaged-full-vault.ps1 against the package root.",
    "Run scripts/packaging/smoke-packaged-dynamic-link.ps1 against the package root.",
    "Run scripts/packaging/smoke-packaged-migration-drill.ps1 against the package root.",
    "Run node scripts/packaging/audit-package-layout.cjs against the packaged resources root.",
    "Run scripts/packaging/smoke-packaged-app-launch.ps1 against the package root.",
    "Run scripts/security/audit-app.ps1 against the installed app and generated diagnostics."
  )
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ReportPath) | Out-Null
$report | ConvertTo-Json -Depth 6 | Set-Content -Path $ReportPath -Encoding UTF8
$report | ConvertTo-Json -Depth 6
