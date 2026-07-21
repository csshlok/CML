param(
  [switch]$ForceCoverage,
  [switch]$SkipTests,
  [ValidateSet("all", "quantity", "dates", "state", "collections", "routing")]
  [string]$ChangedComponent = "all"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$python = (Resolve-Path -LiteralPath (Join-Path $repoRoot ".venv\Scripts\python.exe")).Path
$runner = (Resolve-Path -LiteralPath (Join-Path $repoRoot "scripts\backend\run_longmemeval_atomic_ablation.py")).Path
$cudaCheck = (Resolve-Path -LiteralPath (Join-Path $repoRoot "scripts\backend\check_cuda_runtime.py")).Path
$compare = (Resolve-Path -LiteralPath (Join-Path $repoRoot "scripts\backend\compare_atomic_coverage.py")).Path
$readiness = (Resolve-Path -LiteralPath (Join-Path $repoRoot "scripts\backend\check_atomic_memory_readiness.py")).Path
$artifactRoot = Join-Path $repoRoot ".tmp\vault-odin-memory-benchmark"
$env:CUDA_VISIBLE_DEVICES = "0"
$env:TOKENIZERS_PARALLELISM = "true"

Push-Location $repoRoot
try {
  # Model-backed stages must never silently fall back to CPU. The coverage
  # replay below is deterministic packet analysis and does not invoke a model.
  & $python $cudaCheck
  if ($LASTEXITCODE -ne 0) {
    throw "CUDA preflight failed."
  }
  if (-not $SkipTests) {
    & $python -m pytest -q backend/tests/test_atomic_memory.py backend/tests/test_atomic_ablation_runner.py
    if ($LASTEXITCODE -ne 0) {
      throw "Atomic regression tests failed."
    }
  }

  $runs = @(
    @{ name = "atomic-memory-representative-200"; seed = "20260720" },
    @{ name = "atomic-memory-final-holdout-200"; seed = "20260721" }
  )
  foreach ($run in $runs) {
    $runDir = Join-Path $artifactRoot $run.name
    $coverage = Join-Path $runDir "coverage.json"
    $before = Join-Path $runDir "coverage-before-cycle.json"
    $diff = Join-Path $runDir "coverage-diff.json"
    if (Test-Path -LiteralPath $coverage) {
      Copy-Item -LiteralPath $coverage -Destination $before -Force
    }
    $arguments = @(
      $runner,
      "--phase", "coverage",
      "--selection-mode", "representative",
      "--sample-size", "200",
      "--selection-seed", $run.seed,
      "--run-dir", $runDir
    )
    if ($ChangedComponent -ne "all" -and (Test-Path -LiteralPath $coverage)) {
      $baseCoverage = Get-Content -LiteralPath $coverage -Raw | ConvertFrom-Json
      $operations = switch ($ChangedComponent) {
        "quantity" { @("numeric_sum", "numeric_average", "numeric_difference") }
        "dates" { @("temporal_difference", "event_order") }
        "state" { @("current_state", "state_comparison") }
        "collections" { @("distinct_count", "aggregate_list") }
        "routing" { @($baseCoverage.rows.query_plan.operation | Sort-Object -Unique) }
      }
      $impactIds = @(
        $baseCoverage.rows |
          Where-Object { $_.query_plan.operation -in $operations } |
          ForEach-Object { $_.question_id }
      )
      $arguments += @("--base-coverage", $coverage)
      foreach ($questionId in $impactIds) {
        $arguments += @("--impact-question-id", $questionId)
      }
      Write-Host "Impact replay: component=$ChangedComponent questions=$($impactIds.Count)"
    }
    if ($ForceCoverage) {
      $arguments += "--force-coverage-recompute"
    }
    & $python @arguments
    if ($LASTEXITCODE -ne 0) {
      throw "Coverage replay failed for $($run.name)."
    }
    if (Test-Path -LiteralPath $before) {
      & $python $compare $before $coverage --output $diff
      if ($LASTEXITCODE -ne 0) {
        throw "Coverage diff failed for $($run.name)."
      }
    }
  }

  & $python $readiness
  if ($LASTEXITCODE -eq 0) {
    Write-Host "Atomic development readiness: GO"
  } elseif ($LASTEXITCODE -eq 2) {
    Write-Host "Atomic development readiness: NO-GO (expected gate decision; no reader calls made)"
  } else {
    throw "Readiness check failed unexpectedly with exit code $LASTEXITCODE."
  }
}
finally {
  Pop-Location
}
