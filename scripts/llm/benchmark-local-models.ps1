param(
  [string[]]$ModelIds = @(
    "qwen3-4b-q4_k_m",
    "phi-4-mini-instruct-q4_k_m",
    "qwen3-8b-q4_k_m",
    "gemma-3-4b-it-q4_k_m",
    "gemma-3-12b-it-q4_k_m"
  ),
  [string]$ModelRoot = "T:\LLM",
  [string]$RuntimeRoot = "T:\LLM\runtimes\llama.cpp",
  [ValidateSet("auto", "cpu", "cuda")]
  [string]$Runtime = "auto",
  [int]$Port = 8094,
  [int]$Threads = 8,
  [int]$ContextSize = 4096,
  [int]$GpuLayers = 999,
  [int]$MaxTokens = 96
)

$ErrorActionPreference = "Stop"

$servers = Get-ChildItem -Path $RuntimeRoot -Recurse -Filter "llama-server.exe"
if ($Runtime -eq "cuda") {
  $servers = $servers | Where-Object { $_.FullName -match "cuda" }
} elseif ($Runtime -eq "cpu") {
  $servers = $servers | Where-Object { $_.FullName -match "cpu" -or $_.FullName -notmatch "cuda" }
}

$server = $servers |
  Sort-Object @{ Expression = { if ($_.FullName -match "cuda") { 0 } else { 1 } } }, FullName |
  Select-Object -First 1

if (-not $server) {
  throw "llama-server.exe was not found. Run scripts\llm\download-llama-cpp.ps1 first."
}

$results = @()

foreach ($modelId in $ModelIds) {
  $model = Get-ChildItem -Path (Join-Path $ModelRoot $modelId) -Filter "*.gguf" |
    Select-Object -First 1

  if (-not $model) {
    Write-Warning "Skipping $modelId because no GGUF file was found."
    continue
  }

  $alias = "cml-bench"
  $logDir = Join-Path $RuntimeRoot "logs"
  New-Item -ItemType Directory -Force -Path $logDir | Out-Null
  $outLog = Join-Path $logDir "$modelId-benchmark.out.log"
  $errLog = Join-Path $logDir "$modelId-benchmark.err.log"

  Write-Host ""
  Write-Host "Benchmarking $modelId" -ForegroundColor Cyan

  $arguments = @(
      "-m", $model.FullName,
      "--host", "127.0.0.1",
      "--port", "$Port",
      "--ctx-size", "$ContextSize",
      "--threads", "$Threads",
      "--alias", $alias,
      "--api-prefix", "/v1"
    )

  if ($server.FullName -match "cuda") {
    $arguments += @("--n-gpu-layers", "$GpuLayers")
  }

  $proc = Start-Process `
    -FilePath $server.FullName `
    -ArgumentList $arguments `
    -WindowStyle Hidden `
    -PassThru `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog

  try {
    $ready = $false
    for ($i = 0; $i -lt 180; $i++) {
      Start-Sleep -Seconds 1
      try {
        Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 2 | Out-Null
        $ready = $true
        break
      } catch {}
    }

    if (-not $ready) {
      throw "llama-server did not become ready for $modelId"
    }

    $body = @{
      model = $alias
      messages = @(
        @{
          role = "system"
          content = "CML means Context Management Layer, a local second-brain app that organizes user-controlled context."
        },
        @{
          role = "user"
          content = "In one sentence, explain what CML does. /no_think"
        }
      )
      temperature = 0.2
      max_tokens = $MaxTokens
      stream = $false
    } | ConvertTo-Json -Depth 8

    $response = Invoke-RestMethod `
      -Uri "http://127.0.0.1:$Port/v1/chat/completions" `
      -Method Post `
      -Body $body `
      -ContentType "application/json" `
      -TimeoutSec 240

    $timings = $response.timings
    $answer = $response.choices[0].message.content
    $results += [pscustomobject]@{
      model_id = $modelId
      prompt_tokens_per_second = $timings.prompt_per_second
      generated_tokens_per_second = $timings.predicted_per_second
      prompt_tokens = $timings.prompt_n
      generated_tokens = $timings.predicted_n
      answer = $answer
    }
  } finally {
    if ($proc -and -not $proc.HasExited) {
      Stop-Process -Id $proc.Id -Force
    }
  }
}

Write-Host ""
Write-Host "Benchmark results" -ForegroundColor Green
$results | Format-Table -AutoSize
