param(
  [string]$StateDir = ".tmp\remediation-soak",
  [string]$Report = ".tmp\remediation-soak-report.json",
  [int]$LogTail = 20
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$statePath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $StateDir))
$pidPath = Join-Path $statePath "runner.pid"
$statusPath = Join-Path $statePath "live-status.json"
$stderrPath = Join-Path $statePath "runner.stderr.log"
$reportPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $Report))

if (Test-Path -LiteralPath $pidPath) {
  $soakPid = [int](Get-Content -LiteralPath $pidPath -Raw)
  $process = Get-Process -Id $soakPid -ErrorAction SilentlyContinue
  if ($process) {
    Write-Host "Runner: ACTIVE (PID $soakPid, CPU $([math]::Round($process.CPU, 1))s, RAM $([math]::Round($process.WorkingSet64 / 1MB, 1)) MiB)"
  }
  else {
    Write-Host "Runner: STOPPED (last PID $soakPid)"
  }
}
else {
  Write-Host "Runner: no PID file"
}

if (Test-Path -LiteralPath $statusPath) {
  $status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
  Write-Host "Status: cycle=$($status.cycle), sources=$($status.source_count), chats=$($status.chat_count), restarts=$($status.restart_count), locks=$($status.lock_cycle_count), errors=$($status.operation_error_count), invariants=$($status.invariant_failure_count)"
  Write-Host "Elapsed: $([math]::Round([double]$status.run_elapsed_seconds / 3600, 2)) / $([math]::Round([double]$status.requested_duration_seconds / 3600, 2)) hours"
  if ($null -ne $status.latest_resource_sample.rss_bytes) {
    Write-Host "Backend: RAM $([math]::Round([double]$status.latest_resource_sample.rss_bytes / 1MB, 1)) MiB, DB $([math]::Round([double]$status.latest_resource_sample.database_bytes / 1MB, 1)) MiB, handles $($status.latest_resource_sample.handles), threads $($status.latest_resource_sample.threads)"
  }
  Write-Host "Updated: $([DateTimeOffset]::FromUnixTimeSeconds([long]$status.updated_at).ToLocalTime())"
}
else {
  Write-Host "Status: waiting for the first completed cycle"
}

if (Test-Path -LiteralPath $reportPath) {
  $reportData = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
  Write-Host "Final report: pass=$($reportData.pass), completed=$($reportData.completed_requested_duration), elapsed=$($reportData.elapsed_seconds)s"
}

if (Test-Path -LiteralPath $stderrPath) {
  $errorLines = @(Get-Content -LiteralPath $stderrPath -Tail $LogTail)
  if ($errorLines.Count -gt 0) {
    Write-Host "Recent runner stderr:"
    $errorLines | ForEach-Object { Write-Host "  $_" }
  }
}
