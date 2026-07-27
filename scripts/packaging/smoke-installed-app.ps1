param(
  [string]$InstallerPath = "",
  [string]$InstallDir = "",
  [int]$InstallerTimeoutSeconds = 1200,
  [int]$TimeoutSeconds = 120,
  [string]$UserDataRoot = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
if (-not $InstallerPath) {
  throw "InstallerPath is required. Pass the explicit NSIS installer path to smoke-installed-app.ps1."
}
if (-not $InstallDir) {
  $InstallDir = Join-Path $env:TEMP ("cml-installed-smoke-" + [guid]::NewGuid().ToString("n"))
}
if (-not $UserDataRoot) {
  $UserDataRoot = Join-Path $env:TEMP ("cml-installed-user-data-" + [guid]::NewGuid().ToString("n"))
}

$installer = [System.IO.Path]::GetFullPath($InstallerPath)
$installRoot = [System.IO.Path]::GetFullPath($InstallDir)
$userDataPath = [System.IO.Path]::GetFullPath($UserDataRoot)
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

function Get-ProcessPathSafe($Process) {
  try {
    return [string]$Process.Path
  } catch {
    return ""
  }
}

function Test-ProcessUnderRoot($Process, [string]$RootPath) {
  $processPath = Get-ProcessPathSafe $Process
  return $processPath -and $processPath.StartsWith($RootPath, [System.StringComparison]::OrdinalIgnoreCase)
}

function Stop-InstalledRuntimeProcesses([string]$RootPath) {
  $stopped = @()
  $candidateProcesses = @()
  $candidateProcesses += Get-Process -Name "CML" -ErrorAction SilentlyContinue
  $candidateProcesses += Get-Process -Name "python" -ErrorAction SilentlyContinue
  foreach ($candidate in $candidateProcesses) {
    if (-not $candidate) {
      continue
    }
    if (-not (Test-ProcessUnderRoot $candidate $RootPath)) {
      continue
    }
    $processPath = Get-ProcessPathSafe $candidate
    $stopped += [ordered]@{
      id = $candidate.Id
      name = $candidate.ProcessName
      path = $processPath
    }
    Stop-Process -Id $candidate.Id -Force -ErrorAction SilentlyContinue
  }
  foreach ($entry in $stopped) {
    Wait-Process -Id $entry.id -Timeout 5 -ErrorAction SilentlyContinue
  }
  return $stopped
}

function Invoke-SilentInstaller {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string[]]$Arguments,
    [Parameter(Mandatory = $true)][int]$Timeout
  )
  $process = Start-Process -FilePath $Path -ArgumentList $Arguments -PassThru
  if (-not $process.WaitForExit($Timeout * 1000)) {
    try {
      $process.Kill()
    } catch {
      Write-Warning "Could not terminate timed-out installer $Path`: $($_.Exception.Message)"
    }
    throw "Timed out waiting for installer after $Timeout second(s): $Path"
  }
  if ($process.ExitCode -ne 0) {
    throw "Installer exited with $($process.ExitCode): $Path"
  }
}

if (Test-Path -LiteralPath $installRoot) {
  Remove-Item -Recurse -Force $installRoot
}

$installArgs = @("/S", "/D=$installRoot")
Invoke-SilentInstaller -Path $installer -Arguments $installArgs -Timeout $InstallerTimeoutSeconds

$exe = Join-Path $installRoot "CML.exe"
if (-not (Test-Path -LiteralPath $exe)) {
  throw "Installed executable not found after NSIS install: $exe"
}

$installerAutostartProcesses = Stop-InstalledRuntimeProcesses $installRoot
New-Item -ItemType Directory -Force -Path $userDataPath | Out-Null

$candidateStatusPaths = @(
  (Join-Path $userDataPath "startup-status.json")
)
$candidateStdoutLogs = @(
  (Join-Path $userDataPath "backend-stdout.log")
)
$candidateStderrLogs = @(
  (Join-Path $userDataPath "backend-stderr.log")
)
$candidateRuntimeLogs = @(
  (Join-Path $userDataPath "desktop-runtime.log")
)

$statusBefore = @{}
$fileSnapshots = @{}
foreach ($candidate in ($candidateStatusPaths + $candidateStdoutLogs + $candidateStderrLogs + $candidateRuntimeLogs)) {
  if (Test-Path -LiteralPath $candidate) {
    $statusBefore[$candidate] = (Get-Item -LiteralPath $candidate).LastWriteTimeUtc
  }
  $fileSnapshots[$candidate] = Get-FileSnapshot $candidate
}

$electronRunAsNode = $env:ELECTRON_RUN_AS_NODE
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
$process = Start-Process -FilePath $exe -ArgumentList @("--user-data-dir=$userDataPath") -PassThru
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
    user_data_dir = $userDataPath
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
    installer_autostart_processes_stopped = $installerAutostartProcesses
  } | ConvertTo-Json -Depth 5
} finally {
  if ($electronRunAsNode -ne $null) {
    $env:ELECTRON_RUN_AS_NODE = $electronRunAsNode
  }
  Stop-InstalledRuntimeProcesses $installRoot | Out-Null
  if ($process -and -not $process.HasExited) {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
  }
  $uninstaller = Join-Path $installRoot "Uninstall CML.exe"
  if (Test-Path -LiteralPath $uninstaller) {
    Invoke-SilentInstaller -Path $uninstaller -Arguments @("/S", "/currentuser") -Timeout $InstallerTimeoutSeconds
    $cleanupDeadline = (Get-Date).AddSeconds(60)
    while ((Test-Path -LiteralPath $installRoot) -and (Get-Date) -lt $cleanupDeadline) {
      Start-Sleep -Seconds 1
    }
    if (Test-Path -LiteralPath $installRoot) {
      $remainingFiles = @(Get-ChildItem -LiteralPath $installRoot -Recurse -File -ErrorAction SilentlyContinue).Count
      throw "Installed-app smoke cleanup left $remainingFiles file(s) in $installRoot"
    }
  }
}
