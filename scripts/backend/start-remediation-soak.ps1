param(
  [double]$DurationHours = 72,
  [double]$DurationSeconds = 0,
  [double]$CycleSeconds = 10,
  [int]$RestartEveryCycles = 180,
  [int]$LockEveryCycles = 60,
  [string]$StateDir = ".tmp\remediation-soak",
  [string]$Report = ".tmp\remediation-soak-report.json"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$runner = Join-Path $repoRoot "scripts\backend\soak-remediation.py"
$statePath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $StateDir))
$pidPath = Join-Path $statePath "runner.pid"

function Get-SoakRunnerProcess([int]$ProcessId) {
  $candidate = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
  if (-not $candidate) {
    return $null
  }
  $commandLine = [string]$candidate.CommandLine
  if ($commandLine -notlike "*soak-remediation.py*") {
    return $null
  }
  return $candidate
}

if (-not (Test-Path -LiteralPath $python)) {
  throw "Repository Python was not found at $python"
}

New-Item -ItemType Directory -Force -Path $statePath | Out-Null
if (Test-Path -LiteralPath $pidPath) {
  $existingPid = [int](Get-Content -LiteralPath $pidPath -Raw)
  if (Get-SoakRunnerProcess $existingPid) {
    throw "A remediation soak runner is already active with PID $existingPid."
  }
}

$arguments = @(
  $runner,
  "--cycle-seconds", [string]$CycleSeconds,
  "--restart-every-cycles", [string]$RestartEveryCycles,
  "--lock-every-cycles", [string]$LockEveryCycles,
  "--state-dir", $StateDir,
  "--report", $Report
)
if ($DurationSeconds -gt 0) {
  $arguments += @("--duration-seconds", [string]$DurationSeconds)
}
else {
  $arguments += @("--duration-hours", [string]$DurationHours)
}

$process = Start-Process `
  -FilePath $python `
  -ArgumentList $arguments `
  -WorkingDirectory $repoRoot `
  -WindowStyle Hidden `
  -PassThru `
  -RedirectStandardOutput (Join-Path $statePath "runner.stdout.log") `
  -RedirectStandardError (Join-Path $statePath "runner.stderr.log")

[System.IO.File]::WriteAllText($pidPath, [string]$process.Id, [System.Text.UTF8Encoding]::new($false))
Write-Host "Vault remediation soak started."
Write-Host "  Runner PID: $($process.Id)"
Write-Host "  State:      $statePath"
Write-Host "  Report:     $([System.IO.Path]::GetFullPath((Join-Path $repoRoot $Report)))"
Write-Host "Monitor with: .\scripts\backend\monitor-remediation-soak.ps1 -StateDir '$StateDir'"
