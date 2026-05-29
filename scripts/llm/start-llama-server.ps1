param(
  [Parameter(Mandatory = $true)]
  [ValidateSet(
    "qwen3-4b-q4_k_m",
    "phi-4-mini-instruct-q4_k_m",
    "qwen3-8b-q4_k_m",
    "gemma-3-4b-it-q4_k_m",
    "gemma-3-12b-it-q4_k_m"
  )]
  [string]$ModelId,

  [string]$ModelRoot = "T:\LLM",
  [string]$RuntimeRoot = "T:\LLM\runtimes\llama.cpp",
  [ValidateSet("auto", "cpu", "cuda")]
  [string]$Runtime = "auto",
  [int]$Port = 8084,
  [int]$Threads = 8,
  [int]$ContextSize = 4096,
  [int]$GpuLayers = 999,
  [string]$Alias = "cml-local"
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

$model = Get-ChildItem -Path (Join-Path $ModelRoot $ModelId) -Filter "*.gguf" |
  Select-Object -First 1

if (-not $model) {
  throw "No GGUF model found for $ModelId under $ModelRoot"
}

$logDir = Join-Path $RuntimeRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$outLog = Join-Path $logDir "$ModelId-$Port.out.log"
$errLog = Join-Path $logDir "$ModelId-$Port.err.log"

Write-Host "Starting llama-server..." -ForegroundColor Cyan
Write-Host "Runtime:$($server.FullName)"
Write-Host "Model:  $($model.FullName)"
Write-Host "URL:    http://127.0.0.1:$Port/v1"
Write-Host "Alias:  $Alias"
Write-Host "Logs:   $outLog"
Write-Host "        $errLog"

$arguments = @(
    "-m", $model.FullName,
    "--host", "127.0.0.1",
    "--port", "$Port",
    "--ctx-size", "$ContextSize",
    "--threads", "$Threads",
    "--alias", $Alias,
    "--api-prefix", "/v1"
  )

if ($server.FullName -match "cuda") {
  $arguments += @("--n-gpu-layers", "$GpuLayers")
}

Start-Process `
  -FilePath $server.FullName `
  -ArgumentList $arguments `
  -WindowStyle Hidden `
  -RedirectStandardOutput $outLog `
  -RedirectStandardError $errLog

Write-Host ""
Write-Host "Set these in .env while this server is running:" -ForegroundColor Green
Write-Host "CML_LLM_PROVIDER=openai-compatible"
Write-Host "CML_LLM_BASE_URL=http://127.0.0.1:$Port/v1"
Write-Host "CML_LLM_MODEL=$Alias"
