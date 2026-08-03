param(
  [Parameter(Mandatory = $true)]
  [string]$ModelPath,
  [string]$RuntimePath = "T:\LLM\runtimes\llama.cpp\b9374-cuda-12.4\llama-server.exe",
  [string]$DatasetPath = ".tmp\rag-reader-accuracy\longmemeval_oracle.json",
  [string]$OutputPath = ".tmp\rag-reader-accuracy\reader-evidence-local-ab-v2.json",
  [int]$Port = 8084,
  [int]$PerStratum = 10,
  [int]$ContextSize = 4096,
  [string]$Seed = "vault-reader-evidence-2026-08-02-validation-2",
  [string]$SelectionManifest = "backend\tests\fixtures\reader_evidence_local_ab_v2_selection.json",
  [string]$ExcludeReport = ".tmp\rag-reader-accuracy\reader-evidence-local-ab.json",
  [switch]$Force
)

$ErrorActionPreference = "Stop"

# DEAD EXPERIMENT (2026-08-03): the reader-evidence candidate regressed both
# frozen A/B selections. The implementation remains for audit; execution is blocked.
throw "DEAD EXPERIMENT: reader-evidence packing failed its frozen accuracy gates."

$resolvedModel = (Resolve-Path -LiteralPath $ModelPath).Path
$resolvedRuntime = (Resolve-Path -LiteralPath $RuntimePath).Path
$resolvedDataset = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $DatasetPath))
$resolvedOutput = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $OutputPath))
$datasetDirectory = Split-Path -Parent $resolvedDataset
$outputDirectory = Split-Path -Parent $resolvedOutput
New-Item -ItemType Directory -Force -Path $datasetDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null

if (-not (Test-Path -LiteralPath $resolvedDataset)) {
  Write-Host "Downloading the official cleaned LongMemEval oracle dataset..."
  Invoke-WebRequest `
    -Uri "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_oracle.json" `
    -OutFile $resolvedDataset `
    -TimeoutSec 180
}

$existingListener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existingListener) {
  throw "Port $Port is already in use. Stop that runtime or choose another -Port."
}

$logPrefix = Join-Path $outputDirectory "reader-evidence-llama-$Port"
$arguments = @(
  "-m", $resolvedModel,
  "--host", "127.0.0.1",
  "--port", "$Port",
  "--ctx-size", "$ContextSize",
  "--threads", "8",
  "--alias", "cml-local",
  "--api-prefix", "/v1",
  "--n-gpu-layers", "999"
)
$runtime = $null
try {
  $runtime = Start-Process `
    -FilePath $resolvedRuntime `
    -ArgumentList $arguments `
    -WindowStyle Hidden `
    -RedirectStandardOutput "$logPrefix.out.log" `
    -RedirectStandardError "$logPrefix.err.log" `
    -PassThru

  $ready = $false
  for ($attempt = 0; $attempt -lt 90; $attempt++) {
    if ($runtime.HasExited) {
      throw "llama-server exited during startup. Check $logPrefix.err.log"
    }
    try {
      $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/health" -TimeoutSec 2
      if ($health.status -eq "ok") {
        $ready = $true
        break
      }
    } catch {
      Start-Sleep -Seconds 1
    }
  }
  if (-not $ready) {
    throw "llama-server did not become ready within 90 seconds. Check $logPrefix.err.log"
  }

  $benchmarkArgs = @(
    "scripts/backend/benchmark_reader_evidence_local.py",
    "--dataset", $resolvedDataset,
    "--output", $resolvedOutput,
    "--base-url", "http://127.0.0.1:$Port/v1",
    "--model", "cml-local",
    "--per-stratum", "$PerStratum",
    "--seed", $Seed
  )
  if ($SelectionManifest) {
    $resolvedSelectionManifest = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $SelectionManifest))
    $benchmarkArgs += @("--selection-manifest", $resolvedSelectionManifest)
  }
  if ($ExcludeReport) {
    $resolvedExcludeReport = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $ExcludeReport))
    if (Test-Path -LiteralPath $resolvedExcludeReport) {
      $benchmarkArgs += @("--exclude-report", $resolvedExcludeReport)
    }
  }
  if ($Force) {
    $benchmarkArgs += "--force"
  }
  & .\.venv\Scripts\python.exe @benchmarkArgs
  if ($LASTEXITCODE -ne 0) {
    throw "Reader evidence benchmark failed with exit code $LASTEXITCODE."
  }
  Write-Host "Report: $resolvedOutput"
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
