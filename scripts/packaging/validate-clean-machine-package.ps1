param(
  [string]$PackageRoot = "",
  [string]$InstallerPath = "",
  [string]$ReportPath = "",
  [switch]$RunExecutableSmokes
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $PackageRoot) {
  throw "PackageRoot is required. Pass the explicit win-unpacked root to validate-clean-machine-package.ps1."
}
if (-not $ReportPath) {
  $ReportPath = Join-Path $repoRoot "tmp\clean-machine-package-validation.json"
}

function Test-PathPresent([string]$PathValue) {
  return [bool](Test-Path $PathValue)
}

$packageRootPath = [System.IO.Path]::GetFullPath($PackageRoot)
$resources = Join-Path $packageRootPath "resources"
$runtimePython = Join-Path $resources "python-runtime\python.exe"
$psutilRuntime = Join-Path $resources "python-runtime\Lib\site-packages\psutil"
$sentenceTransformersRuntime = Join-Path $resources "python-runtime\Lib\site-packages\sentence_transformers"
$turbovecRuntime = Join-Path $resources "python-runtime\Lib\site-packages\turbovec"
$backend = Join-Path $resources "backend"
$ocrManifest = Join-Path $backend "bin\ocr\manifest.json"
$playwrightRuntime = Join-Path $resources "ms-playwright"
$llmRuntime = Join-Path $resources "llm-runtime\llama-server.exe"
$llmCudaRuntime = Join-Path $resources "llm-runtime\cuda\llama-server.exe"
$llmCudaBackend = Join-Path $resources "llm-runtime\cuda\ggml-cuda.dll"
$tunnelRuntime = Join-Path $resources "tunnel-client\tunnel-client.exe"
$helperManifest = Join-Path $resources "helper-manifest.json"
$modelIntegrityManifest = Join-Path $resources "docs\model-integrity-manifest.json"
$packagedLaunchSmoke = Join-Path $repoRoot "scripts\packaging\smoke-packaged-app-launch.ps1"
$installedAppSmoke = Join-Path $repoRoot "scripts\packaging\smoke-installed-app.ps1"
$installerLifecycleSmoke = Join-Path $repoRoot "scripts\packaging\smoke-windows-installer.ps1"
$checks = @(
  @{ name = "package_root_exists"; ok = Test-PathPresent $packageRootPath; path = $packageRootPath },
  @{ name = "resources_exists"; ok = Test-PathPresent $resources; path = $resources },
  @{ name = "backend_exists"; ok = Test-PathPresent $backend; path = $backend },
  @{ name = "python_runtime_exists"; ok = Test-PathPresent $runtimePython; path = $runtimePython },
  @{ name = "psutil_runtime_exists"; ok = Test-PathPresent $psutilRuntime; path = $psutilRuntime },
  @{ name = "sentence_transformers_runtime_exists"; ok = Test-PathPresent $sentenceTransformersRuntime; path = $sentenceTransformersRuntime },
  @{ name = "turbovec_runtime_exists"; ok = Test-PathPresent $turbovecRuntime; path = $turbovecRuntime },
  @{ name = "playwright_runtime_exists"; ok = Test-PathPresent $playwrightRuntime; path = $playwrightRuntime },
  @{ name = "llm_runtime_exists"; ok = Test-PathPresent $llmRuntime; path = $llmRuntime },
  @{ name = "llm_cuda_runtime_exists"; ok = Test-PathPresent $llmCudaRuntime; path = $llmCudaRuntime },
  @{ name = "llm_cuda_backend_exists"; ok = Test-PathPresent $llmCudaBackend; path = $llmCudaBackend },
  @{ name = "tunnel_client_exists"; ok = Test-PathPresent $tunnelRuntime; path = $tunnelRuntime },
  @{ name = "ocr_manifest_exists"; ok = Test-PathPresent $ocrManifest; path = $ocrManifest },
  @{ name = "helper_manifest_exists"; ok = Test-PathPresent $helperManifest; path = $helperManifest },
  @{ name = "model_integrity_manifest_exists"; ok = Test-PathPresent $modelIntegrityManifest; path = $modelIntegrityManifest },
  @{ name = "app_launch_smoke_exists"; ok = Test-PathPresent $packagedLaunchSmoke; path = "scripts/packaging/smoke-packaged-app-launch.ps1" },
  @{ name = "runtime_smoke_exists"; ok = Test-PathPresent (Join-Path $repoRoot "scripts\packaging\smoke-packaged-runtime.ps1"); path = "scripts/packaging/smoke-packaged-runtime.ps1" },
  @{ name = "full_vault_smoke_exists"; ok = Test-PathPresent (Join-Path $repoRoot "scripts\packaging\smoke-packaged-full-vault.ps1"); path = "scripts/packaging/smoke-packaged-full-vault.ps1" },
  @{ name = "dynamic_link_smoke_exists"; ok = Test-PathPresent (Join-Path $repoRoot "scripts\packaging\smoke-packaged-dynamic-link.ps1"); path = "scripts/packaging/smoke-packaged-dynamic-link.ps1" },
  @{ name = "migration_drill_exists"; ok = Test-PathPresent (Join-Path $repoRoot "scripts\packaging\smoke-packaged-migration-drill.ps1"); path = "scripts/packaging/smoke-packaged-migration-drill.ps1" },
  @{ name = "defender_policy_smoke_exists"; ok = Test-PathPresent (Join-Path $repoRoot "scripts\packaging\smoke-packaged-defender.ps1"); path = "scripts/packaging/smoke-packaged-defender.ps1" },
  @{ name = "installed_app_smoke_exists"; ok = Test-PathPresent $installedAppSmoke; path = "scripts/packaging/smoke-installed-app.ps1" },
  @{ name = "odin_launcher_smoke_exists"; ok = Test-PathPresent (Join-Path $repoRoot "scripts\packaging\smoke-odin-launcher.ps1"); path = "scripts/packaging/smoke-odin-launcher.ps1" },
  @{ name = "startup_benchmark_exists"; ok = Test-PathPresent (Join-Path $repoRoot "scripts\packaging\benchmark-packaged-startup.ps1"); path = "scripts/packaging/benchmark-packaged-startup.ps1" },
  @{ name = "rendered_ui_smoke_exists"; ok = Test-PathPresent (Join-Path $repoRoot "scripts\packaging\smoke-packaged-ui.py"); path = "scripts/packaging/smoke-packaged-ui.py" },
  @{ name = "installer_lifecycle_smoke_exists"; ok = Test-PathPresent $installerLifecycleSmoke; path = "scripts/packaging/smoke-windows-installer.ps1" },
  @{ name = "package_layout_audit_exists"; ok = Test-PathPresent (Join-Path $repoRoot "scripts\packaging\audit-package-layout.cjs"); path = "scripts/packaging/audit-package-layout.cjs" }
)

$hostTools = @(
  @{ name = "python_on_path"; detected = [bool](Get-Command python -ErrorAction SilentlyContinue) },
  @{ name = "node_on_path"; detected = [bool](Get-Command node -ErrorAction SilentlyContinue) },
  @{ name = "tesseract_on_path"; detected = [bool](Get-Command tesseract -ErrorAction SilentlyContinue) },
  @{ name = "gs_on_path"; detected = [bool](Get-Command gswin64c -ErrorAction SilentlyContinue) }
)

$executableSmokeResults = @()
if ($RunExecutableSmokes) {
  try {
    $packagedResult = & $packagedLaunchSmoke -PackageRoot $packageRootPath | ConvertFrom-Json
    $executableSmokeResults += [ordered]@{
      name = "packaged_app_launch"
      ok = $true
      detail = $packagedResult
    }
  } catch {
    $executableSmokeResults += [ordered]@{
      name = "packaged_app_launch"
      ok = $false
      detail = $_.Exception.Message
    }
  }

  if ($InstallerPath) {
    $installerFullPath = [System.IO.Path]::GetFullPath($InstallerPath)
    try {
      $installedResult = & $installedAppSmoke -InstallerPath $installerFullPath | ConvertFrom-Json
      $executableSmokeResults += [ordered]@{
        name = "installed_app_launch"
        ok = $true
        detail = $installedResult
      }
    } catch {
      $executableSmokeResults += [ordered]@{
        name = "installed_app_launch"
        ok = $false
        detail = $_.Exception.Message
      }
    }

    try {
      $lifecycleResult = & $installerLifecycleSmoke -InstallerPath $installerFullPath | ConvertFrom-Json
      $executableSmokeResults += [ordered]@{
        name = "installer_lifecycle"
        ok = $true
        detail = $lifecycleResult
      }
    } catch {
      $executableSmokeResults += [ordered]@{
        name = "installer_lifecycle"
        ok = $false
        detail = $_.Exception.Message
      }
    }
  }
}

$report = [ordered]@{
  generated_at = (Get-Date).ToUniversalTime().ToString("o")
  package_root = $packageRootPath
  installer_path = if ($InstallerPath) { [System.IO.Path]::GetFullPath($InstallerPath) } else { "" }
  intent = "Contributor clean-machine validation plan. Run this before handing a package to another tester."
  pass = (($checks | Where-Object { -not $_.ok }).Count -eq 0) -and (($executableSmokeResults | Where-Object { -not $_.ok }).Count -eq 0)
  checks = $checks
  host_tool_findings = $hostTools
  executable_smoke_results = $executableSmokeResults
  clean_vm_rule = "For public-quality validation, rerun on a Windows VM where python_on_path, node_on_path, tesseract_on_path, and gs_on_path are false."
  manual_validation_order = @(
    "Run scripts/packaging/smoke-packaged-runtime.ps1 against the package root.",
    "Run scripts/packaging/smoke-packaged-full-vault.ps1 against the package root.",
    "Run scripts/packaging/smoke-packaged-dynamic-link.ps1 against the package root.",
    "Run scripts/packaging/smoke-packaged-migration-drill.ps1 against the package root.",
    "Run scripts/packaging/smoke-packaged-defender.ps1 against the package root.",
    "Run node scripts/packaging/audit-package-layout.cjs against the packaged resources root.",
    "Run scripts/packaging/smoke-packaged-app-launch.ps1 against the package root and require renderer ready signal.",
    "Run scripts/packaging/smoke-odin-launcher.ps1 from a clean shell and require packaged Odin help plus the actionable desktop-offline response.",
    "Run scripts/packaging/benchmark-packaged-startup.ps1 and enforce the recorded p95 budgets.",
    "Run the packaged Python interpreter with scripts/packaging/smoke-packaged-ui.py to render the minimum supported viewport and reject console or horizontal-overflow regressions.",
    "Run scripts/packaging/smoke-installed-app.ps1 against the final NSIS installer and require renderer ready signal.",
    "Run scripts/packaging/smoke-windows-installer.ps1 to verify install and uninstall lifecycle.",
    "Run scripts/security/audit-app.ps1 against the installed app and generated diagnostics."
  )
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ReportPath) | Out-Null
$report | ConvertTo-Json -Depth 6 | Set-Content -Path $ReportPath -Encoding UTF8
$report | ConvertTo-Json -Depth 6
if (-not $report.pass) {
  exit 1
}
