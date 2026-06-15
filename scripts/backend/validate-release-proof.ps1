param(
  [string]$ContextVaultId = "",
  [string]$ReportRoot = ".tmp\release-proof"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  throw "Missing .venv python at $python"
}

New-Item -ItemType Directory -Force -Path $ReportRoot | Out-Null

$commands = @(
  @{ name = "compileall"; command = "$python -m compileall -q backend/app" },
  @{ name = "pdf-tests"; command = "$python -m pytest -q backend/tests/test_pdf_pipeline.py" },
  @{ name = "context-tests"; command = "$python -m pytest -q backend/tests/test_context_reduction.py" },
  @{ name = "extension-tests"; command = "node --test apps/browser-extension/tests/popup-core.test.cjs apps/browser-extension/tests/background-core.test.cjs apps/desktop/electron/extension-presentation.test.cjs" }
)

$results = @()
foreach ($entry in $commands) {
  try {
    Invoke-Expression $entry.command | Out-Null
    $results += @{ name = $entry.name; status = "passed"; command = $entry.command }
  } catch {
    $results += @{ name = $entry.name; status = "failed"; command = $entry.command; error = $_.Exception.Message }
  }
}

if ($ContextVaultId) {
  try {
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backend\benchmark-context-strategies.ps1 -VaultId $ContextVaultId -ReportPath (Join-Path $ReportRoot "context-strategies.json") | Out-Null
    $results += @{ name = "context-strategy-benchmark"; status = "passed" }
  } catch {
    $results += @{ name = "context-strategy-benchmark"; status = "failed"; error = $_.Exception.Message }
  }
}

$report = @{
  generated_at = (Get-Date).ToString("o")
  results = $results
  passed = @($results | Where-Object { $_.status -eq "passed" }).Count
  failed = @($results | Where-Object { $_.status -eq "failed" }).Count
}

$target = Join-Path $ReportRoot "release-proof-report.json"
$report | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 $target
$report | ConvertTo-Json -Depth 8
if ($report.failed -gt 0) {
  exit 1
}
