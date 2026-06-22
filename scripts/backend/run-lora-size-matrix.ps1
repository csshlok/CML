param(
  [Parameter(Mandatory = $true)]
  [string]$BaseModel15B,
  [Parameter(Mandatory = $true)]
  [string]$BaseModel2B,
  [Parameter(Mandatory = $true)]
  [string]$BaseModel3B,
  [string[]]$SourcePaths = @("docs/PROJECT_CONTEXT.md", "docs/OVERALL_CONTEXT.md"),
  [string]$OutputDir = ".tmp/lora-size-matrix",
  [int]$MaxRealSources = 12,
  [int]$BenchmarkCaseLimit = 8,
  [int]$RuntimeMaxNewTokens = 32,
  [int]$BenchmarkMaxNewTokens = 64
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$outputFullPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutputDir))
New-Item -ItemType Directory -Force -Path $outputFullPath | Out-Null

$profiles = @(
  @{ Label = "1p5b"; BaseModel = $BaseModel15B },
  @{ Label = "2b"; BaseModel = $BaseModel2B },
  @{ Label = "3b"; BaseModel = $BaseModel3B }
)

$runs = @()
foreach ($profile in $profiles) {
  $label = $profile.Label
  $baseModel = $profile.BaseModel
  $smokeReport = Join-Path $outputFullPath "smoke-$label.json"
  $benchmarkReport = Join-Path $outputFullPath "benchmark-$label.json"
  $workDir = Join-Path $outputFullPath "work-$label"

  & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoRoot "scripts\backend\smoke-lora-expert.ps1") `
    -ReportPath $smokeReport `
    -BaseModelPath $baseModel `
    -SourcePaths $SourcePaths `
    -MaxRealSources $MaxRealSources `
    -BenchmarkCaseLimit $BenchmarkCaseLimit `
    -RuntimeMaxNewTokens $RuntimeMaxNewTokens `
    -BenchmarkMaxNewTokens $BenchmarkMaxNewTokens `
    -AllowBenchmarkFailure `
    -WorkDir $workDir
  $smokeExit = $LASTEXITCODE

  $adapterPath = ""
  if (Test-Path $smokeReport) {
    $smokePayload = Get-Content -Path $smokeReport -Raw | ConvertFrom-Json
    $activeArtifact = $smokePayload.artifacts | Where-Object { $_.active -eq 1 } | Select-Object -First 1
    if ($activeArtifact) {
      $adapterPath = [string]$activeArtifact.local_path
    }
  }

  $benchmarkExit = $null
  if ($adapterPath) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoRoot "scripts\backend\benchmark-lora-adapter.ps1") `
      -AdapterPath $adapterPath `
      -BaseModel $baseModel `
      -SourcePaths $SourcePaths `
      -ReportPath $benchmarkReport `
      -MaxRealSources $MaxRealSources `
      -BenchmarkCaseLimit $BenchmarkCaseLimit `
      -BenchmarkMaxNewTokens $BenchmarkMaxNewTokens
    $benchmarkExit = $LASTEXITCODE
  }

  $runs += [PSCustomObject]@{
    label = $label
    base_model = $baseModel
    smoke_report = $smokeReport
    smoke_exit_code = $smokeExit
    adapter_path = $adapterPath
    benchmark_report = if ($adapterPath) { $benchmarkReport } else { "" }
    benchmark_exit_code = $benchmarkExit
  }
}

$summaryPath = Join-Path $outputFullPath "summary.json"
$summary = [PSCustomObject]@{
  generated_at = (Get-Date).ToUniversalTime().ToString("o")
  output_dir = $outputFullPath
  runs = $runs
}
$summary | ConvertTo-Json -Depth 6 | Set-Content -Path $summaryPath -Encoding UTF8
Write-Host "LoRA size matrix summary written to $summaryPath"
