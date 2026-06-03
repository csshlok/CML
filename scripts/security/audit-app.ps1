param(
  [switch]$InstallPipAudit
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  $python = "python"
}

Push-Location $repoRoot
try {
  Write-Host "Running npm production dependency audit..."
  npm audit --omit=dev --audit-level=moderate

  Write-Host "Checking Python dependency consistency..."
  & $python -m pip check

  $pipAuditAvailable = $false
  & $python -m pip_audit --version *> $null
  if ($LASTEXITCODE -eq 0) {
    $pipAuditAvailable = $true
  } elseif ($InstallPipAudit) {
    Write-Host "Installing pip-audit into the contributor virtualenv..."
    & $python -m pip install pip-audit
    $pipAuditAvailable = $true
  }

  if ($pipAuditAvailable) {
    Write-Host "Running Python vulnerability audit..."
    & $python -m pip_audit
  } else {
    Write-Warning "pip-audit is not installed. Re-run with -InstallPipAudit for Python vulnerability auditing."
  }

  Write-Host "Running Electron security behavior tests..."
  node apps\desktop\electron\main.behavior.test.cjs
  node apps\desktop\electron\token-store.test.cjs

  Write-Host "Running focused backend security tests..."
  & $python -m unittest `
    backend.tests.test_system_vault_lock_and_embeddings `
    backend.tests.test_bridge_mcp
} finally {
  Pop-Location
}
