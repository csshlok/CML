param(
  [string]$BaseModelPath = "T:\hf-models\Qwen2.5-1.5B-Instruct",
  [string]$VaultRoot = "sample_new\vault2",
  [string]$WorkDir = "T:\cml-lora-sample-new-vault-1p5b-evalsmoke",
  [string]$ReportPath = ".tmp/lora-sample-new-vault-evalsmoke.json",
  [int]$Epochs = 2,
  [int]$ExpectedSourceCount = 205,
  [int]$BenchmarkCaseLimit = 12
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repoRoot

$resolvedVaultRoot = Join-Path $repoRoot $VaultRoot
if (-not (Test-Path $resolvedVaultRoot)) {
  throw "Vault root not found: $VaultRoot"
}

$sources = Get-ChildItem -LiteralPath $resolvedVaultRoot -File -Recurse |
  Where-Object { $_.Extension.ToLowerInvariant() -in @('.pdf', '.md', '.txt') } |
  Sort-Object FullName |
  ForEach-Object { $_.FullName }

if ($sources.Count -ne $ExpectedSourceCount) {
  throw "Expected $ExpectedSourceCount explicit source files, but found $($sources.Count)."
}

$env:CML_LORA_TRAINER_COMMAND = "T:\cml-lora-venv\Scripts\llamafactory-cli.exe train {config_path}"
$env:CML_LORA_RUNTIME_PYTHON = "T:\cml-lora-venv\Scripts\python.exe"
$env:CML_LORA_TRAINING_DEVICE = "cuda"
$env:CML_LORA_TRAINING_DTYPE = "fp16"
$env:CML_LORA_TRAINING_NUM_TRAIN_EPOCHS = [string]$Epochs
$env:CML_LORA_TRAINER_TIMEOUT_SECONDS = "14400"

& ".\scripts\backend\smoke-lora-expert.ps1" `
  -ReportPath $ReportPath `
  -BaseModelPath $BaseModelPath `
  -SourcePaths $sources `
  -ExpectedSourceCount $ExpectedSourceCount `
  -MaxRealSources $ExpectedSourceCount `
  -BenchmarkCaseLimit $BenchmarkCaseLimit `
  -RuntimeMaxNewTokens 48 `
  -BenchmarkMaxNewTokens 0 `
  -AllowBenchmarkFailure `
  -WorkDir $WorkDir
