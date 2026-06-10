param(
  [string]$InstallerPath = "",
  [string]$InstallDir = "",
  [int]$TimeoutSeconds = 45
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
if (-not $InstallerPath) {
  throw "InstallerPath is required. Pass the explicit NSIS installer path to smoke-installed-app.ps1."
}
if (-not $InstallDir) {
  $InstallDir = Join-Path $env:TEMP ("cml-installed-smoke-" + [guid]::NewGuid().ToString("n"))
}

$installer = [System.IO.Path]::GetFullPath($InstallerPath)
$installRoot = [System.IO.Path]::GetFullPath($InstallDir)
if (-not (Test-Path -LiteralPath $installer)) {
  throw "Installer not found: $installer"
}

function Get-FileSnapshot([string]$PathValue) {
  if (-not (Test-Path -LiteralPath $PathValue)) {
    return @{ exists = $false; length = 0 }
  }
  $item = Get-Item -LiteralPath $PathValue
  return @{
    exists = $true
    length = $item.Length
  }
}

function Get-AppendedLogText([string]$PathValue, $Snapshot) {
  if (-not (Test-Path -LiteralPath $PathValue)) {
    return ""
  }
  $text = Get-Content -LiteralPath $PathValue -Raw -ErrorAction SilentlyContinue
  if (-not $Snapshot -or -not $Snapshot.exists) {
    return $text
  }
  if ($Snapshot.length -ge $text.Length) {
    return ""
  }
  return $text.Substring([int]$Snapshot.length)
}

if (Test-Path -LiteralPath $installRoot) {
  Remove-Item -Recurse -Force $installRoot
}

$installArgs = @("/S", "/D=$installRoot")
Start-Process -FilePath $installer -ArgumentList $installArgs -Wait

$exe = Join-Path $installRoot "CML.exe"
if (-not (Test-Path -LiteralPath $exe)) {
  throw "Installed executable not found after NSIS install: $exe"
}

$candidateStatusPaths = @(
  (Join-Path $env:APPDATA "@cml\desktop\startup-status.json")
)
$candidateStdoutLogs = @(
  (Join-Path $env:APPDATA "@cml\desktop\backend-stdout.log")
)
$candidateStderrLogs = @(
  (Join-Path $env:APPDATA "@cml\desktop\backend-stderr.log")
)
$candidateRuntimeLogs = @(
  (Join-Path $env:APPDATA "@cml\desktop\desktop-runtime.log")
)

$statusBefore = @{}
$fileSnapshots = @{}
foreach ($candidate in ($candidateStatusPaths + $candidateStdoutLogs + $candidateStderrLogs + $candidateRuntimeLogs)) {
  if (Test-Path -LiteralPath $candidate) {
    $statusBefore[$candidate] = (Get-Item -LiteralPath $candidate).LastWriteTimeUtc
  }
  $fileSnapshots[$candidate] = Get-FileSnapshot $candidate
}

$process = Start-Process -FilePath $exe -PassThru
try {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  $status = $null
  $statusPath = $null
  while ((Get-Date) -lt $deadline) {
    foreach ($candidate in $candidateStatusPaths) {
      if (-not (Test-Path -LiteralPath $candidate)) {
        continue
      }
      $item = Get-Item -LiteralPath $candidate
      if (-not $statusBefore.ContainsKey($candidate) -or $item.LastWriteTimeUtc -gt $statusBefore[$candidate]) {
        $statusPath = $candidate
        $status = Get-Content -LiteralPath $candidate -Raw | ConvertFrom-Json
        if ($status.status -eq "ready" -or $status.status -eq "failed") {
          break
        }
      }
    }
    if ($status -and ($status.status -eq "ready" -or $status.status -eq "failed")) {
      break
    }
    Start-Sleep -Milliseconds 500
  }

  $stdoutLog = $candidateStdoutLogs | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
  $stderrLog = $candidateStderrLogs | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
  $runtimeLog = $candidateRuntimeLogs | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
  $runtimeLogText = if ($runtimeLog) { Get-AppendedLogText $runtimeLog $fileSnapshots[$runtimeLog] } else { "" }

  if (-not $status) {
    throw "Installed app did not write fresh startup status. stderr=$stderrLog runtime=$runtimeLog"
  }
  if ($status.status -ne "ready") {
    throw "Installed app startup did not reach ready: $($status | ConvertTo-Json -Compress)"
  }
  $rendererReadyDetected = $false
  $rendererFailureDetected = $false
  $rendererDeadline = (Get-Date).AddSeconds([Math]::Max(5, [Math]::Min($TimeoutSeconds, 15)))
  while ((Get-Date) -lt $rendererDeadline) {
    $runtimeLogText = if ($runtimeLog) { Get-AppendedLogText $runtimeLog $fileSnapshots[$runtimeLog] } else { "" }
    $rendererReadyDetected = $runtimeLogText -match "renderer ready signal received"
    $rendererFailureDetected = (
      $runtimeLogText -match "packaged renderer failed" -or
      $runtimeLogText -match "Renderer did not become available" -or
      $runtimeLogText -match "renderer did-fail-load" -or
      $runtimeLogText -match "renderer process gone"
    )
    if ($rendererReadyDetected -or $rendererFailureDetected) {
      break
    }
    Start-Sleep -Milliseconds 250
  }
  if ($rendererFailureDetected) {
    throw "Installed app reached backend ready but renderer failed. runtime=$runtimeLog"
  }
  if (-not $rendererReadyDetected) {
    throw "Installed app reached backend ready but renderer never signaled readiness. runtime=$runtimeLog"
  }

  [ordered]@{
    installer = $installer
    install_dir = $installRoot
    launched_exe = $exe
    startup_status_path = $statusPath
    startup_status = $status.status
    startup_phase = $status.phase
    backend_mode = $status.backend_mode
    backend_stdout_log = $stdoutLog
    backend_stderr_log = $stderrLog
    desktop_runtime_log = $runtimeLog
    renderer_ready_detected = $rendererReadyDetected
    renderer_failure_detected = $rendererFailureDetected
  } | ConvertTo-Json -Depth 5
} finally {
  Get-Process -Name "CML" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  Get-Process -Name "python" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "*$installRoot*python-runtime*" } |
    Stop-Process -Force -ErrorAction SilentlyContinue
  if ($process -and -not $process.HasExited) {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
  }
}
