param(
  [Parameter(Mandatory = $true)]
  [int]$ServerPid,
  [int]$LauncherPid = 0,
  [Parameter(Mandatory = $true)]
  [int]$Port
)

$ErrorActionPreference = "Stop"
$listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop |
  Select-Object -First 1
if ([int]$listener.OwningProcess -ne $ServerPid) {
  throw "Refusing to stop PID ${ServerPid}: port $Port belongs to PID $($listener.OwningProcess)."
}
$server = Get-CimInstance Win32_Process -Filter "ProcessId=$ServerPid"
if (-not $server -or $server.CommandLine -notmatch "127.0.0.1" -or $server.CommandLine -notmatch "$Port") {
  throw "Refusing to stop an unverified extractor process."
}
if ($server.CommandLine -notmatch "serve_local_qwen_openai|llama-server") {
  throw "PID $ServerPid is not a recognized extractor runtime."
}

Stop-Process -Id $ServerPid -Force
if ($LauncherPid -and $LauncherPid -ne $ServerPid) {
  $launcher = Get-CimInstance Win32_Process -Filter "ProcessId=$LauncherPid"
  if ($launcher -and [int]$server.ParentProcessId -eq $LauncherPid) {
    Stop-Process -Id $LauncherPid -Force -ErrorAction SilentlyContinue
  }
}
Start-Sleep -Milliseconds 750
if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
  throw "Extractor endpoint on port $Port is still listening."
}
@{ stopped = $true; server_pid = $ServerPid; launcher_pid = $LauncherPid; port = $Port } |
  ConvertTo-Json
