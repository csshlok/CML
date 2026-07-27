param(
  [string]$PackageRoot = "",
  [int]$TimeoutSeconds = 30,
  [string]$UserDataRoot = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
if (-not $PackageRoot) {
  throw "PackageRoot is required. Pass the explicit win-unpacked root to smoke-packaged-app-launch.ps1."
}

$packagePath = [System.IO.Path]::GetFullPath($PackageRoot)
$exe = Join-Path $packagePath "CML.exe"
if (-not (Test-Path -LiteralPath $exe)) {
  throw "Packaged app executable not found: $exe"
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

function Get-DiagnosticExcerpt([string]$Text, [int]$MaxLines = 12, [int]$LineLimit = 300) {
  if (-not $Text) {
    return ""
  }
  $lines = @($Text -split "\r?\n" | Where-Object { $_ })
  $start = [Math]::Max(0, $lines.Count - $MaxLines)
  $bounded = for ($index = $start; $index -lt $lines.Count; $index += 1) {
    $line = [string]$lines[$index]
    if ($line.Length -le $LineLimit) {
      $line
    } else {
      $line.Substring(0, $LineLimit) + "... [line truncated]"
    }
  }
  return $bounded -join [Environment]::NewLine
}

$userDataPath = if ($UserDataRoot) {
  [System.IO.Path]::GetFullPath($UserDataRoot)
} else {
  Join-Path $env:APPDATA "@cml\desktop"
}
New-Item -ItemType Directory -Force -Path $userDataPath | Out-Null
$candidateStatusPaths = @((Join-Path $userDataPath "startup-status.json"))
$candidateStdoutLogs = @((Join-Path $userDataPath "backend-stdout.log"))
$candidateStderrLogs = @((Join-Path $userDataPath "backend-stderr.log"))
$candidateRuntimeLogs = @((Join-Path $userDataPath "desktop-runtime.log"))
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
$launchArguments = if ($UserDataRoot) { @("--user-data-dir=$userDataPath") } else { @() }
$launchStarted = Get-Date
$process = if ($launchArguments.Count -gt 0) {
  Start-Process -FilePath $exe -ArgumentList $launchArguments -PassThru
} else {
  Start-Process -FilePath $exe -PassThru
}
try {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  $status = $null
  $statusPath = $null
  $backendReadyAt = $null
  while ((Get-Date) -lt $deadline) {
    if ($process.HasExited) {
      break
    }
    foreach ($candidate in $candidateStatusPaths) {
      if (-not (Test-Path -LiteralPath $candidate)) {
        continue
      }
      $item = Get-Item -LiteralPath $candidate
      if (-not $statusBefore.ContainsKey($candidate) -or $item.LastWriteTimeUtc -gt $statusBefore[$candidate]) {
        $statusPath = $candidate
        $status = Get-Content -LiteralPath $candidate -Raw | ConvertFrom-Json
        if ($status.status -eq "ready" -or $status.status -eq "failed") {
          $backendReadyAt = Get-Date
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
    $known = $candidateStatusPaths -join ", "
    $exitDetail = if ($process.HasExited) { "exit_code=$($process.ExitCode)" } else { "process_still_running=true" }
    $runtimeExcerpt = Get-DiagnosticExcerpt $runtimeLogText
    throw "Packaged app did not write fresh startup status. $exitDetail Checked: $known stderr=$stderrLog runtime=$runtimeLog runtime_tail=$runtimeExcerpt"
  }
  if ($status.status -ne "ready") {
    throw "Packaged app startup did not reach ready: $($status | ConvertTo-Json -Compress)"
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
    throw "Packaged app reached backend ready but renderer failed. runtime=$runtimeLog"
  }
  if (-not $rendererReadyDetected) {
    throw "Packaged app reached backend ready but renderer never signaled readiness. runtime=$runtimeLog"
  }
  $visibleMatch = [regex]::Matches($runtimeLogText, "startup window visible elapsed_ms=(\d+)") |
    Select-Object -Last 1
  $windowVisibleElapsedMs = if ($visibleMatch) { [int]$visibleMatch.Groups[1].Value } else { $null }

  [ordered]@{
    package_root = $packagePath
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
    window_visible_elapsed_ms = $windowVisibleElapsedMs
    backend_ready_elapsed_ms = if ($backendReadyAt) {
      [math]::Round(($backendReadyAt - $launchStarted).TotalMilliseconds, 2)
    } else {
      $null
    }
    backend_process_elapsed_ms = $status.total_elapsed_ms
    launch_to_renderer_ready_ms = [math]::Round(((Get-Date) - $launchStarted).TotalMilliseconds, 2)
  } | ConvertTo-Json -Depth 5
} finally {
  if ($electronRunAsNode -ne $null) {
    $env:ELECTRON_RUN_AS_NODE = $electronRunAsNode
  }
  Get-Process -Name "CML" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  Get-Process -Name "python" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "*\win-unpacked\resources\python-runtime\*" } |
    Stop-Process -Force -ErrorAction SilentlyContinue
  if ($process -and -not $process.HasExited) {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
  }
}
