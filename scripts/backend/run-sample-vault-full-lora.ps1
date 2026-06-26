param(
  [string]$BaseModelPath = "T:\hf-models\Qwen2.5-1.5B-Instruct",
  [string]$WorkDir = "T:\cml-lora-sample-vault-1p5b-full105",
  [string]$ReportPath = ".tmp/lora-sample-vault-full105.json",
  [int]$Epochs = 10,
  [int]$ExpectedSourceCount = 105,
  [int]$BenchmarkCaseLimit = 24
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repoRoot

$sourceRoots = @(
  "sample_lora_vault\vault\articles_and_research"
  "sample_lora_vault\vault\personal_notes"
  "sample_lora_vault\vault\chat_transcripts"
  "sample_lora_vault\vault\saved_links"
)

$sources = @()
foreach ($root in $sourceRoots) {
  $resolvedRoot = Join-Path $repoRoot $root
  if (-not (Test-Path $resolvedRoot)) {
    throw "Source root not found: $root"
  }
  $sources += Get-ChildItem -LiteralPath $resolvedRoot -File -Recurse |
    Where-Object { $_.Extension.ToLowerInvariant() -in @('.pdf', '.md', '.txt') } |
    Sort-Object FullName |
    ForEach-Object { $_.FullName }
}

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
