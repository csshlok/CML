param(
  [string]$BaseModelPath = "T:\hf-models\Qwen2.5-1.5B-Instruct",
  [string]$VaultRoot = "sample_new\vault2",
  [string]$WorkDir = "T:\cml-lora-sample-new-vault-1p5b-full205",
  [string]$ReportPath = ".tmp/lora-sample-new-vault-full205.json",
  [int]$Epochs = 3,
  [int]$ExpectedSourceCount = 205,
  [int]$BenchmarkCaseLimit = 24,
  [int]$EvalSteps = 200,
  [int]$EarlyStoppingSteps = 2,
  [switch]$SkipQualityGate
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repoRoot

$resolvedVaultRoot = Join-Path $repoRoot $VaultRoot
if (-not (Test-Path $resolvedVaultRoot)) {
  throw "Vault root not found: $VaultRoot"
}

$sources = Get-ChildItem -LiteralPath $resolvedVaultRoot -File -Recurse |
  Where-Object {
    $_.Name.ToLowerInvariant() -ne 'manifest.json' -and
    $_.Extension.ToLowerInvariant() -in @('.pdf', '.md', '.txt')
  } |
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
$env:CML_LORA_TRAINING_EVAL_STEPS = [string]$EvalSteps
$env:CML_LORA_TRAINING_EARLY_STOPPING_STEPS = [string]$EarlyStoppingSteps
$env:CML_LORA_TRAINER_TIMEOUT_SECONDS = "21600"
$env:CML_LORA_SKIP_QUALITY_GATE = if ($SkipQualityGate) { "1" } else { "0" }

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
