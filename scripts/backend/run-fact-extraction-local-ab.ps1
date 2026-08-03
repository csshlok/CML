param(
  [Parameter(Mandatory = $true)]
  [string]$ModelPath,
  [string]$RuntimePath = "T:\LLM\runtimes\llama.cpp\b9374-cuda-12.4\llama-server.exe",
  [string]$EmbeddingModel = "T:\test\all-MiniLM-L6-v2",
  [string]$DatasetPath = ".tmp\rag-fact-extraction\longmemeval_s_cleaned.json",
  [string]$OutputDirectory = ".tmp\rag-fact-extraction",
  [int]$Port = 8084,
  [int]$PerStratum = 2,
  [int]$ContextSize = 8192,
  [switch]$Force
)

$ErrorActionPreference = "Stop"

# DEAD EXPERIMENT (2026-08-03): raw=0.40, facts-only=0.00, hybrid=0.20.
# The implementation remains below for audit history, but execution is blocked.
throw "DEAD EXPERIMENT: Qwen fact extraction reduced accuracy versus raw RAG."

$resolvedModel = (Resolve-Path -LiteralPath $ModelPath).Path
$resolvedRuntime = (Resolve-Path -LiteralPath $RuntimePath).Path
$resolvedEmbedding = (Resolve-Path -LiteralPath $EmbeddingModel).Path
$resolvedOutput = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $OutputDirectory))
$resolvedDataset = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $DatasetPath))
New-Item -ItemType Directory -Force -Path $resolvedOutput | Out-Null

if (-not (Test-Path -LiteralPath $resolvedDataset)) {
  Write-Host "Downloading the official LongMemEval-S cleaned dataset..."
  Invoke-WebRequest `
    -Uri "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json" `
    -OutFile $resolvedDataset `
    -TimeoutSec 600
}

$selectedDataset = Join-Path $resolvedOutput "fact-ab-selection.json"
$selectionManifest = Join-Path $resolvedOutput "fact-ab-selection-manifest.json"
$retrievalReport = Join-Path $resolvedOutput "fact-ab-retrieval.json"
$report = Join-Path $resolvedOutput "fact-ab-report.json"

$selectionArgs = @(
  "scripts/backend/prepare_longmemeval_fact_ab.py",
  "--dataset", $resolvedDataset,
  "--output", $selectedDataset,
  "--manifest", $selectionManifest,
  "--per-stratum", "$PerStratum",
  "--exclude-report", ".tmp/rag-reader-accuracy/reader-evidence-local-ab.json",
  "--exclude-report", ".tmp/rag-reader-accuracy/reader-evidence-local-ab-v2.json"
)
& .\.venv\Scripts\python.exe @selectionArgs
if ($LASTEXITCODE -ne 0) { throw "Selection failed with exit code $LASTEXITCODE." }

if ($Force -or -not (Test-Path -LiteralPath $retrievalReport)) {
  & .\.venv\Scripts\python.exe scripts/backend/benchmark_vault_longmemeval.py `
    --dataset $selectedDataset `
    --selection all `
    --top-k 10 `
    --model $resolvedEmbedding `
    --work-dir (Join-Path $resolvedOutput "retrieval-index") `
    --output $retrievalReport
  if ($LASTEXITCODE -ne 0) { throw "Retrieval benchmark failed with exit code $LASTEXITCODE." }
}

if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
  throw "Port $Port is already in use. Stop that runtime or choose another -Port."
}

$logPrefix = Join-Path $resolvedOutput "fact-ab-llama-$Port"
$runtime = $null
try {
  $runtime = Start-Process `
    -FilePath $resolvedRuntime `
    -ArgumentList @(
      "-m", $resolvedModel,
      "--host", "127.0.0.1",
      "--port", "$Port",
      "--ctx-size", "$ContextSize",
      "--threads", "8",
      "--alias", "cml-local",
      "--api-prefix", "/v1",
      "--n-gpu-layers", "999"
    ) `
    -WindowStyle Hidden `
    -RedirectStandardOutput "$logPrefix.out.log" `
    -RedirectStandardError "$logPrefix.err.log" `
    -PassThru

  $ready = $false
  for ($attempt = 0; $attempt -lt 120; $attempt++) {
    if ($runtime.HasExited) { throw "llama-server exited during startup. Check $logPrefix.err.log" }
    try {
      $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/health" -TimeoutSec 2
      if ($health.status -eq "ok") { $ready = $true; break }
    } catch { Start-Sleep -Seconds 1 }
  }
  if (-not $ready) { throw "llama-server did not become ready within 120 seconds." }

  $benchmarkArgs = @(
    "scripts/backend/benchmark_fact_extraction_local.py",
    "--dataset", $selectedDataset,
    "--retrieval", $retrievalReport,
    "--output", $report,
    "--base-url", "http://127.0.0.1:$Port/v1",
    "--model", "cml-local"
  )
  if ($Force) { $benchmarkArgs += "--force" }
  & .\.venv\Scripts\python.exe @benchmarkArgs
  if ($LASTEXITCODE -ne 0) { throw "Fact-extraction A/B failed with exit code $LASTEXITCODE." }
  Write-Host "Report: $report"
} finally {
  if ($runtime -and -not $runtime.HasExited) {
    Stop-Process -Id $runtime.Id
    $runtime.WaitForExit(5000) | Out-Null
    if (-not $runtime.HasExited) {
      Stop-Process -Id $runtime.Id -Force
      $runtime.WaitForExit(5000) | Out-Null
    }
  }
}
