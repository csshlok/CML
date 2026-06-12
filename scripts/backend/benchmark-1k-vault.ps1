param(
  [string]$ReportRoot = "",
  [int]$Sources = 1000
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$benchmark = Join-Path $repoRoot "scripts\backend\benchmark-retrieval.ps1"

if (-not (Test-Path -LiteralPath $benchmark)) {
  throw "Retrieval benchmark script not found: $benchmark"
}

if (-not $ReportRoot) {
  $ReportRoot = Join-Path $env:TEMP "cml-build-smoke\retrieval-1k"
}

New-Item -ItemType Directory -Force -Path $ReportRoot | Out-Null
& $benchmark -Sources $Sources -ReportPath $ReportRoot
