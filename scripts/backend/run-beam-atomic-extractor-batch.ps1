param(
  [string]$Windows = ".tmp\beam-ingestion-eval\scored-pilot-v1\extraction-windows.jsonl",
  [ValidateSet("qwen3-4b-gguf")]
  [string]$Candidate = "qwen3-4b-gguf",
  [int]$SampleSize = 20,
  [int]$MaxBatches = 0,
  [int]$Port = 8091,
  [int]$ContextSize = 8192,
  [int]$MaxTokens = 4096,
  [int]$LargeWindowMaxTokens = 6144,
  [int]$CitationMaxChars = 200,
  [switch]$RetryFailedCache,
  [string]$Output = ".tmp\beam-ingestion-eval\scored-pilot-v1\full-compiler-grounded-v1.json",
  [string]$CacheDir = ".tmp\beam-ingestion-eval\scored-pilot-v1\full-compiler-cache-v1",
  [string]$Python = ".venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$startScript = Join-Path $PSScriptRoot "start-atomic-extractor-api.ps1"
$stopScript = Join-Path $PSScriptRoot "stop-atomic-extractor-api.ps1"
$runner = Join-Path $PSScriptRoot "run_beam_ingestion_smoke.py"
$resolvedOutput = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $Output))
$resolvedWindows = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $Windows))
$resolvedCache = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $CacheDir))
$resolvedPython = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $Python))

if (-not (Test-Path -LiteralPath $resolvedWindows -PathType Leaf)) {
  throw "Extraction windows were not found: $resolvedWindows"
}
if (-not (Test-Path -LiteralPath $resolvedPython -PathType Leaf)) {
  throw "Python runtime was not found: $resolvedPython"
}

$batchLimit = if ($MaxBatches -gt 0) { $MaxBatches } else { $SampleSize + 1 }
for ($iteration = 1; $iteration -le $batchLimit; $iteration++) {
  $server = $null
  try {
    $serverJson = & $startScript `
      -Candidate $Candidate `
      -Port $Port `
      -ContextSize $ContextSize | Out-String
    $server = $serverJson | ConvertFrom-Json
    $candidateSpec = "$Candidate|$($server.model)|$($server.base_url)"
    $runnerArguments = @(
      $runner,
      "--windows", $resolvedWindows,
      "--candidate", $candidateSpec,
      "--sample-size", "$SampleSize",
      "--max-uncached-windows", "1",
      "--quiet-cache-hits",
      "--output", $resolvedOutput,
      "--cache-dir", $resolvedCache,
      "--max-tokens", "$MaxTokens",
      "--large-window-max-tokens", "$LargeWindowMaxTokens",
      "--evidence-citation-max-chars", "$CitationMaxChars"
    )
    if ($RetryFailedCache) {
      $runnerArguments += "--retry-failed-cache"
    }
    & $resolvedPython @runnerArguments
    $runnerExit = $LASTEXITCODE
    if (-not (Test-Path -LiteralPath $resolvedOutput -PathType Leaf)) {
      throw "Extractor runner produced no report (exit $runnerExit)."
    }
  } finally {
    if ($server) {
      & $stopScript `
        -ServerPid ([int]$server.server_pid) `
        -LauncherPid ([int]$server.launcher_pid) `
        -Port $Port | Out-Null
    }
  }

  $report = Get-Content -LiteralPath $resolvedOutput -Raw | ConvertFrom-Json
  $complete = [bool]$report.selection.complete
  Write-Host (
    "batch {0}: windows={1}/{2}, uncached={3}, complete={4}" -f `
      $iteration,
      $report.summary.window_count,
      $SampleSize,
      $report.selection.uncached_window_count,
      $complete
  )
  if ($complete) {
    $summary = @{
      report = $resolvedOutput
      cache_dir = $resolvedCache
      window_count = $report.summary.window_count
      schema_compliant_count = $report.summary.schema_compliant_count
      structural_pass_count = $report.summary.structural_pass_count
      normalized_citation_issues = $report.summary.total_normalized_citation_issues
      compiler_replay_checked_count = $report.summary.compiler_replay_checked_count
      compiler_replay_idempotent_count = $report.summary.compiler_replay_idempotent_count
      peak_gpu_memory_mib = $report.summary.peak_gpu_memory_mib
    }
    $summary | ConvertTo-Json
    exit 0
  }
}

throw "Extractor batch did not finish after $batchLimit bounded iterations."
