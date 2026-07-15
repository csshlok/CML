param(
  [ValidateSet("quick", "integration", "system", "benchmark", "full", "scale")]
  [string]$Tier = "quick",
  [string]$Python = ".\.venv\Scripts\python.exe",
  [string]$JunitPath = "",
  [int]$Slowest = 20
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
if (-not [System.IO.Path]::IsPathRooted($Python)) {
  $Python = Join-Path $repoRoot $Python
}
if (-not (Test-Path -LiteralPath $Python)) {
  $command = Get-Command python -ErrorAction SilentlyContinue
  if (-not $command) {
    throw "Python was not found. Create .venv or pass -Python explicitly."
  }
  $Python = $command.Source
}

$marker = switch ($Tier) {
  "quick" { "not integration and not system and not benchmark and not scale" }
  "integration" { "integration" }
  "system" { "system" }
  "benchmark" { "benchmark and not scale" }
  "scale" { "scale" }
  default { "" }
}

$arguments = @(
  "-m", "pytest",
  "-ra",
  "--strict-markers",
  "--durations=$Slowest"
)
if ($marker) {
  $arguments += @("-m", $marker)
}
if ($Tier -eq "scale") {
  # The 50k-file fixture can take several minutes to materialize on Windows
  # before the measured discovery phase begins.
  $arguments += @("--timeout=900", "-o", "faulthandler_timeout=0", "-s")
}
if ($JunitPath) {
  $junitFullPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $JunitPath))
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $junitFullPath) | Out-Null
  $arguments += "--junitxml=$junitFullPath"
}

$previousHashSeed = $env:PYTHONHASHSEED
$previousScaleGate = $env:ODIN_RUN_SCALE_TESTS
try {
  $env:PYTHONHASHSEED = "0"
  if ($Tier -eq "scale") {
    $env:ODIN_RUN_SCALE_TESTS = "1"
  }
  Push-Location $repoRoot
  try {
    Write-Host "Running backend test tier '$Tier' with $Python"
    & $Python @arguments
    if ($LASTEXITCODE -ne 0) {
      throw "Backend test tier '$Tier' failed with exit code $LASTEXITCODE."
    }
  }
  finally {
    Pop-Location
  }
}
finally {
  $env:PYTHONHASHSEED = $previousHashSeed
  $env:ODIN_RUN_SCALE_TESTS = $previousScaleGate
}
