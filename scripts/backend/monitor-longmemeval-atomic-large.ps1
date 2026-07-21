param(
  [switch]$Follow,
  [int]$Tail = 40
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$largeRunDir = Join-Path $repoRoot ".tmp\vault-odin-memory-benchmark\atomic-memory-final-holdout-200"
$benchmarkPidPath = Join-Path $largeRunDir "benchmark.pid"
$standardLogPath = Join-Path $largeRunDir "run.stdout.log"
$errorLogPath = Join-Path $largeRunDir "run.stderr.log"
$labelsPath = Join-Path $largeRunDir "evidence-labels.jsonl"
$coveragePath = Join-Path $largeRunDir "coverage.json"
$reportPath = Join-Path $largeRunDir "ablation-report.json"
$readinessPath = Join-Path $repoRoot ".tmp\vault-odin-memory-benchmark\atomic-memory-readiness.json"
$benchmarkProcess = $null

if (Test-Path -LiteralPath $benchmarkPidPath) {
  $benchmarkProcessId = [int](Get-Content -LiteralPath $benchmarkPidPath -Raw)
  $benchmarkProcess = Get-Process -Id $benchmarkProcessId -ErrorAction SilentlyContinue
  if ($benchmarkProcess) {
    Write-Host "Status: RUNNING (PID $benchmarkProcessId)"
  } else {
    Write-Host "Status: NOT RUNNING (last PID $benchmarkProcessId)"
  }
} else {
  Write-Host "Status: NOT STARTED (reader evaluation is gated)"
}

if (Test-Path -LiteralPath $labelsPath) {
  $labelRows = @(
    Get-Content -LiteralPath $labelsPath |
      Where-Object { $_.Trim() } |
      ForEach-Object { $_ | ConvertFrom-Json }
  )
  $uniqueLabels = @($labelRows.question_id | Sort-Object -Unique).Count
  $labelsWithEvidence = @($labelRows | Where-Object { @($_.evidence).Count -gt 0 }).Count
  $labelLastWrite = (Get-Item -LiteralPath $labelsPath).LastWriteTime
  Write-Host "Labels: checkpointed=$uniqueLabels/200 with-evidence=$labelsWithEvidence/200 last-write=$labelLastWrite"
}

if (Test-Path -LiteralPath $coveragePath) {
  $coverage = Get-Content -LiteralPath $coveragePath -Raw | ConvertFrom-Json
  Write-Host "Coverage: stored=$($coverage.evidence_recall) atomic-complete=$($coverage.atomic_routed_question_complete_rate) activation=$($coverage.atomic_activation_rate) false-safe=$($coverage.atomic_false_safe_count) temporal=$($coverage.temporal_anchor_recall) direct=$($coverage.direct_fact_recall) expected-prompt=$($coverage.expected_mean_reader_prompt_tokens) baseline=$($coverage.baseline_mean_reader_prompt_tokens)"
}
if (Test-Path -LiteralPath $readinessPath) {
  $readiness = Get-Content -LiteralPath $readinessPath -Raw | ConvertFrom-Json
  Write-Host "Readiness: $($readiness.decision.ToUpper()) failed-gates=$(@($readiness.failed_gates) -join ',') reader-evaluation-allowed=$($readiness.reader_evaluation_allowed)"
}
if (Test-Path -LiteralPath $reportPath) {
  $report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
  Write-Host "Result:"
  $report.summary | ConvertTo-Json -Depth 8
}

if ($benchmarkProcess -or $Follow) {
if (Test-Path -LiteralPath $errorLogPath) {
  $errorLines = Get-Content -LiteralPath $errorLogPath -Tail $Tail
  if ($errorLines) {
    Write-Host "Recent stderr:"
    $errorLines
  }
}

if (Test-Path -LiteralPath $standardLogPath) {
  Write-Host "Recent stdout:"
  if ($Follow) {
    Get-Content -LiteralPath $standardLogPath -Tail $Tail -Wait
  } else {
    Get-Content -LiteralPath $standardLogPath -Tail $Tail
  }
}
}
