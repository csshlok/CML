param(
  [string]$PackageRoot = "",
  [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
if (-not $PackageRoot) {
  $PackageRoot = Join-Path $repoRoot "apps\desktop\release\win-unpacked"
}

$packagePath = [System.IO.Path]::GetFullPath($PackageRoot)
$exe = Join-Path $packagePath "CML.exe"
if (-not (Test-Path -LiteralPath $exe)) {
  throw "Packaged app executable not found: $exe"
}

$candidateStatusPaths = @(
  (Join-Path $env:APPDATA "@cml\desktop\startup-status.json"),
  (Join-Path $env:APPDATA "CML\startup-status.json"),
  (Join-Path $env:APPDATA "Vault\startup-status.json")
)
$statusBefore = @{}
foreach ($candidate in $candidateStatusPaths) {
  if (Test-Path -LiteralPath $candidate) {
    $statusBefore[$candidate] = (Get-Item -LiteralPath $candidate).LastWriteTimeUtc
  }
}

$electronRunAsNode = $env:ELECTRON_RUN_AS_NODE
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
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

  if (-not $status) {
    $known = $candidateStatusPaths -join ", "
    throw "Packaged app did not write fresh startup status. Checked: $known"
  }
  if ($status.status -ne "ready") {
    throw "Packaged app startup did not reach ready: $($status | ConvertTo-Json -Compress)"
  }

  [ordered]@{
    package_root = $packagePath
    launched_exe = $exe
    startup_status_path = $statusPath
    startup_status = $status.status
    startup_phase = $status.phase
    backend_mode = $status.backend_mode
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
