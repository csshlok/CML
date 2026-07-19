param(
  [string]$Python = "T:\cml-lora-venv\Scripts\python.exe",
  [string]$ModelPath = "T:\hf-models\Qwen2.5-3B-Instruct",
  [string]$Alias = "qwen2.5-3b-instruct-4bit",
  [int]$Port = 8084,
  [int]$MaxInputTokens = 16384,
  [int]$MaxGenerationSeconds = 60,
  [string]$LogRoot = ".tmp\local-qwen-api"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$resolvedLogRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $LogRoot))
New-Item -ItemType Directory -Force -Path $resolvedLogRoot | Out-Null

$env:LOCAL_QWEN_MODEL_PATH = $ModelPath
$env:LOCAL_QWEN_MODEL_ALIAS = $Alias
$env:LOCAL_QWEN_MAX_INPUT_TOKENS = "$MaxInputTokens"
$env:LOCAL_QWEN_MAX_GENERATION_SECONDS = "$MaxGenerationSeconds"

$stdout = Join-Path $resolvedLogRoot "server.stdout.log"
$stderr = Join-Path $resolvedLogRoot "server.stderr.log"
$process = Start-Process `
  -FilePath $Python `
  -ArgumentList @(
    "-m", "uvicorn", "scripts.backend.serve_local_qwen_openai:app",
    "--host", "127.0.0.1", "--port", "$Port"
  ) `
  -WorkingDirectory $repoRoot `
  -WindowStyle Hidden `
  -RedirectStandardOutput $stdout `
  -RedirectStandardError $stderr `
  -PassThru

@{
  pid = $process.Id
  base_url = "http://127.0.0.1:$Port/v1"
  health_url = "http://127.0.0.1:$Port/health"
  model = $Alias
  stdout = $stdout
  stderr = $stderr
} | ConvertTo-Json
