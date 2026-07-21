param(
  [int]$Workers = 4,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$pythonPath = (Resolve-Path -LiteralPath (Join-Path $repoRoot ".venv\Scripts\python.exe")).Path
$artifactRoot = Join-Path $repoRoot ".tmp\vault-odin-memory-benchmark"
$largeRunDir = Join-Path $artifactRoot "atomic-memory-final-holdout-200"
$readinessScript = (Resolve-Path -LiteralPath (Join-Path $repoRoot "scripts\backend\check_atomic_memory_readiness.py")).Path

& $pythonPath $readinessScript
$readinessExitCode = $LASTEXITCODE
if ($readinessExitCode -ne 0) {
  throw "Atomic reader evaluation is blocked by the frozen readiness gates. No API calls were started."
}

throw "This wrapper is retired: atomic-memory-final-holdout-200 has already been inspected and is development data. Freeze a genuinely untouched manifest before adding a new reader launch command."
