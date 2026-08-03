param(
  [Parameter(Mandatory = $true)]
  [string]$InstallRoot
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$resolvedInstallRoot = [System.IO.Path]::GetFullPath($InstallRoot).TrimEnd(
  [System.IO.Path]::DirectorySeparatorChar,
  [System.IO.Path]::AltDirectorySeparatorChar
)
$resolvedDriveRoot = [System.IO.Path]::GetPathRoot($resolvedInstallRoot).TrimEnd(
  [System.IO.Path]::DirectorySeparatorChar,
  [System.IO.Path]::AltDirectorySeparatorChar
)
if (-not $resolvedInstallRoot -or $resolvedInstallRoot.Equals(
  $resolvedDriveRoot,
  [System.StringComparison]::OrdinalIgnoreCase
)) {
  throw "Refusing to stop processes for a drive-root installation path."
}
$ownedProcessNames = @(
  "CML.exe",
  "llama-server.exe",
  "python.exe",
  "tunnel-client.exe"
)

function Test-PathInsideInstallRoot([string]$Candidate) {
  if (-not $Candidate) {
    return $false
  }
  try {
    $resolvedCandidate = [System.IO.Path]::GetFullPath($Candidate)
  } catch {
    return $false
  }
  return $resolvedCandidate.Equals(
    $resolvedInstallRoot,
    [System.StringComparison]::OrdinalIgnoreCase
  ) -or $resolvedCandidate.StartsWith(
    "$resolvedInstallRoot$([System.IO.Path]::DirectorySeparatorChar)",
    [System.StringComparison]::OrdinalIgnoreCase
  )
}

$ownedProcesses = @(
  Get-CimInstance Win32_Process -ErrorAction Stop |
    Where-Object {
      $ownedProcessNames -contains [string]$_.Name -and
      (Test-PathInsideInstallRoot ([string]$_.ExecutablePath))
    }
)

foreach ($ownedProcess in $ownedProcesses) {
  Stop-Process -Id ([int]$ownedProcess.ProcessId) -Force -ErrorAction SilentlyContinue
}
foreach ($ownedProcess in $ownedProcesses) {
  Wait-Process -Id ([int]$ownedProcess.ProcessId) -Timeout 5 -ErrorAction SilentlyContinue
}
