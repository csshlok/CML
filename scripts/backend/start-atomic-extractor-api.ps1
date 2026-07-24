param(
  [Parameter(Mandatory = $true)]
  [ValidateSet(
    "qwen2.5-1.5b-transformers",
    "qwen2.5-3b-transformers",
    "qwen2.5-1.5b-gguf",
    "qwen2.5-3b-gguf",
    "qwen3-4b-gguf"
  )]
  [string]$Candidate,

  [int]$Port = 8091,
  [int]$ContextSize = 8192,
  [int]$StartupTimeoutSeconds = 240,
  [string]$TransformersPython = "T:\cml-lora-venv\Scripts\python.exe",
  [string]$HfModelRoot = "T:\hf-models",
  [string]$GgufModelRoot = "T:\LLM",
  [string]$LlamaRuntimeRoot = "T:\LLM\runtimes\llama.cpp",
  [string]$LogRoot = ".tmp\atomic-memory-v2-extractor-servers"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$resolvedLogRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $LogRoot))
New-Item -ItemType Directory -Force -Path $resolvedLogRoot | Out-Null

$existingListener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($existingListener) {
  throw "Port $Port is already in use by PID $($existingListener[0].OwningProcess)."
}

$alias = $Candidate
$stdout = Join-Path $resolvedLogRoot "$Candidate-$Port.stdout.log"
$stderr = Join-Path $resolvedLogRoot "$Candidate-$Port.stderr.log"

if ($Candidate -in @("qwen2.5-1.5b-transformers", "qwen2.5-3b-transformers")) {
  if (-not (Test-Path -LiteralPath $TransformersPython -PathType Leaf)) {
    throw "Transformers benchmark Python was not found: $TransformersPython"
  }
  $modelDirectory = if ($Candidate -eq "qwen2.5-1.5b-transformers") {
    "Qwen2.5-1.5B-Instruct"
  } else {
    "Qwen2.5-3B-Instruct"
  }
  $modelPath = Join-Path $HfModelRoot $modelDirectory
  if (-not (Test-Path -LiteralPath $modelPath -PathType Container)) {
    throw "Transformers checkpoint was not found: $modelPath"
  }
  $env:LOCAL_QWEN_MODEL_PATH = $modelPath
  $env:LOCAL_QWEN_MODEL_ALIAS = $alias
  $env:LOCAL_QWEN_MAX_INPUT_TOKENS = "$ContextSize"
  $env:LOCAL_QWEN_MAX_GENERATION_SECONDS = "180"
  $env:LOCAL_QWEN_GPU_MEMORY = "5500MiB"
  $env:LOCAL_QWEN_CPU_MEMORY = "24GiB"
  $process = Start-Process `
    -FilePath $TransformersPython `
    -ArgumentList @(
      "-m", "uvicorn", "scripts.backend.serve_local_qwen_openai:app",
      "--host", "127.0.0.1", "--port", "$Port"
    ) `
    -WorkingDirectory $repoRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -PassThru
} else {
  $server = Get-ChildItem -LiteralPath $LlamaRuntimeRoot -Recurse -Filter "llama-server.exe" |
    Where-Object { $_.FullName -match "cuda" } |
    Sort-Object FullName |
    Select-Object -First 1
  if (-not $server) {
    throw "CUDA llama-server.exe was not found below $LlamaRuntimeRoot"
  }
  $ggufDirectory = switch ($Candidate) {
    "qwen2.5-1.5b-gguf" { "qwen2.5-1.5b-instruct-q4_k_m" }
    "qwen2.5-3b-gguf" { "qwen2.5-3b-instruct-q4_k_m" }
    default { "qwen3-4b-q4_k_m" }
  }
  $model = Get-ChildItem -LiteralPath (Join-Path $GgufModelRoot $ggufDirectory) -Filter "*.gguf" |
    Select-Object -First 1
  if (-not $model) {
    throw "$Candidate GGUF was not found below $GgufModelRoot"
  }
  $process = Start-Process `
    -FilePath $server.FullName `
    -ArgumentList @(
      "-m", $model.FullName,
      "--host", "127.0.0.1",
      "--port", "$Port",
      "--ctx-size", "$ContextSize",
      "--parallel", "1",
      "--no-cache-prompt",
      "--cache-ram", "0",
      "--no-cache-idle-slots",
      "--slot-prompt-similarity", "0",
      "--threads", "8",
      "--n-gpu-layers", "999",
      "--alias", $alias,
      "--api-prefix", "/v1",
      "--jinja"
    ) `
    -WorkingDirectory $repoRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -PassThru
}

$healthUrl = if ($Candidate -like "*-gguf") {
  "http://127.0.0.1:$Port/v1/health"
} else {
  "http://127.0.0.1:$Port/health"
}
$deadline = [DateTimeOffset]::UtcNow.AddSeconds($StartupTimeoutSeconds)
$ready = $false
while ([DateTimeOffset]::UtcNow -lt $deadline) {
  if ($process.HasExited) {
    $tail = if (Test-Path -LiteralPath $stderr) {
      (Get-Content -LiteralPath $stderr -Tail 20) -join [Environment]::NewLine
    } else { "" }
    throw "Extractor server exited during startup with code $($process.ExitCode). $tail"
  }
  try {
    $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
    if ($health.status -in @("ok", "ready")) {
      $ready = $true
      break
    }
  } catch {
    Start-Sleep -Milliseconds 500
  }
}
if (-not $ready) {
  Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
  throw "Extractor server did not become ready within $StartupTimeoutSeconds seconds."
}
$listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop |
  Select-Object -First 1
$serverPid = [int]$listener.OwningProcess
$serverProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$serverPid"
if (-not $serverProcess -or $serverProcess.CommandLine -notmatch "127.0.0.1" -or $serverProcess.CommandLine -notmatch "$Port") {
  throw "Ready endpoint is not owned by the expected loopback extractor process."
}

@{
  candidate = $Candidate
  server_pid = $serverPid
  launcher_pid = $process.Id
  model = $alias
  base_url = "http://127.0.0.1:$Port/v1"
  health_url = $healthUrl
  runtime = if ($Candidate -like "*-gguf") { "llama.cpp-cuda" } else { "transformers-nf4-cuda" }
  stdout = $stdout
  stderr = $stderr
} | ConvertTo-Json
