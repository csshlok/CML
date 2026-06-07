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

Write-Host "Running renderer hostile-output audit..."
Push-Location $repoRoot
try {
  npm run security:renderer | Out-Host
  $packageAudit = node scripts\packaging\audit-package-layout.cjs apps\desktop\packaging apps\desktop\packaging
  $packageAuditReport = $packageAudit | ConvertFrom-Json
  Write-Host "Running clean-vault security smoke..."
  $clean = & (Join-Path $PSScriptRoot "security-smoke-clean-vault.ps1") -ReportPath (Join-Path $ReportRoot "clean-vault.json") | ConvertFrom-Json
  Write-Host "Running large-vault security smoke..."
  $large = & (Join-Path $PSScriptRoot "security-smoke-large-vault.ps1") -Sources $LargeVaultSources -ReportPath (Join-Path $ReportRoot "large-vault.json") | ConvertFrom-Json
  Write-Host "Running interrupted-flow drill..."
  $drill = & (Join-Path $PSScriptRoot "security-drill-interrupted-flows.ps1") -ReportPath (Join-Path $ReportRoot "interrupted-flows.json") | ConvertFrom-Json
  Write-Host "Running offline at-rest inspection..."
  $offline = & (Join-Path $PSScriptRoot "inspect-offline-vault-at-rest.ps1") -ReportPath (Join-Path $ReportRoot "offline-at-rest.json") | ConvertFrom-Json
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
$report | ConvertTo-Json -Depth 8 | Set-Content -Path $reportPath -Encoding UTF8
$report | ConvertTo-Json -Depth 8
