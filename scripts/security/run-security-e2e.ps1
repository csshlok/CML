param(
  [string]$ReportRoot = "",
  [int]$LargeVaultSources = 1200
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
if (-not $ReportRoot) {
  $ReportRoot = Join-Path $env:TEMP ("cml-security-e2e-" + [guid]::NewGuid().ToString("n"))
}
New-Item -ItemType Directory -Force -Path $ReportRoot | Out-Null

function Invoke-SmokeJson([string]$ScriptPath, [string[]]$Arguments) {
  $output = & powershell -NoProfile -ExecutionPolicy Bypass -File $ScriptPath @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "Smoke script failed: $ScriptPath"
  }
  return (($output -join "`n") | ConvertFrom-Json)
}

Write-Host "Running renderer hostile-output audit..."
Push-Location $repoRoot
try {
  npm run security:renderer | Out-Host
  $packageAudit = node scripts\packaging\audit-package-layout.cjs apps\desktop\packaging apps\desktop\packaging
  $packageAuditReport = $packageAudit | ConvertFrom-Json
  Write-Host "Running clean-vault security smoke..."
  $clean = Invoke-SmokeJson (Join-Path $PSScriptRoot "security-smoke-clean-vault.ps1") @(
    "-ReportPath",
    (Join-Path $ReportRoot "clean-vault.json")
  )
  Write-Host "Running large-vault security smoke..."
  $large = Invoke-SmokeJson (Join-Path $PSScriptRoot "security-smoke-large-vault.ps1") @(
    "-Sources",
    "$LargeVaultSources",
    "-ReportPath",
    (Join-Path $ReportRoot "large-vault.json")
  )
  Write-Host "Running interrupted-flow drill..."
  $drill = Invoke-SmokeJson (Join-Path $PSScriptRoot "security-drill-interrupted-flows.ps1") @(
    "-ReportPath",
    (Join-Path $ReportRoot "interrupted-flows.json")
  )
  Write-Host "Running offline at-rest inspection..."
  $offline = Invoke-SmokeJson (Join-Path $PSScriptRoot "inspect-offline-vault-at-rest.ps1") @(
    "-ReportPath",
    (Join-Path $ReportRoot "offline-at-rest.json")
  )
} finally {
  Pop-Location
}

$report = [ordered]@{
  generated_at = (Get-Date).ToUniversalTime().ToString("o")
  report_root = $ReportRoot
  package_audit = $packageAuditReport
  clean_vault = $clean
  large_vault = $large
  interrupted_flows = $drill
  offline_at_rest = $offline
  pass = (
    $clean.pass -and
    $large.pass -and
    $drill.pass -and
    $offline.pass -and
    $packageAuditReport.layout_ok -and
    $packageAuditReport.manifest_ok
  )
}

$reportPath = Join-Path $ReportRoot "security-e2e-summary.json"
$reportJson = $report | ConvertTo-Json -Depth 8
$reportJson | Set-Content -Path $reportPath -Encoding UTF8
$reportJson
if (-not $report.pass) {
  exit 1
}
