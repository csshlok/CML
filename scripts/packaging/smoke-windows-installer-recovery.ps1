param(
  [Parameter(Mandatory = $true)][string]$InstallerPath,
  [string]$InstallDirectory = ".tmp\remediation-installer-recovery\installed",
  [int]$TimeoutSeconds = 1200
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$installer = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $InstallerPath))
$installRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $InstallDirectory))
$allowedRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot ".tmp"))
$reportPath = Join-Path (Split-Path -Parent $installRoot) "installer-recovery-report.json"

if (-not (Test-Path -LiteralPath $installer)) {
  throw "Installer not found: $installer"
}
if (-not $installRoot.StartsWith($allowedRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "InstallDirectory must resolve beneath the repository .tmp directory."
}

function Get-CmlUninstallEntry {
  foreach ($root in @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
    "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
  )) {
    if (-not (Test-Path -LiteralPath $root)) { continue }
    $entry = Get-ChildItem -LiteralPath $root -ErrorAction SilentlyContinue |
      ForEach-Object { try { Get-ItemProperty -LiteralPath $_.PsPath } catch { $null } } |
      Where-Object { $_.DisplayName -eq "CML" -or $_.DisplayName -like "CML *" -or $_.Publisher -eq "CML" } |
      Select-Object -First 1
    if ($entry) { return $entry }
  }
  return $null
}

function Stop-ProcessTree([int]$RootPid) {
  $children = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.ParentProcessId -eq $RootPid })
  foreach ($child in $children) { Stop-ProcessTree -RootPid ([int]$child.ProcessId) }
  Stop-Process -Id $RootPid -Force -ErrorAction SilentlyContinue
}

function Invoke-Installer([int]$Timeout = $TimeoutSeconds) {
  $process = Start-Process -FilePath $installer -ArgumentList @("/S", "/D=$installRoot") -PassThru -WindowStyle Hidden
  if (-not $process.WaitForExit($Timeout * 1000)) {
    Stop-ProcessTree -RootPid $process.Id
    throw "Installer timed out after $Timeout seconds."
  }
  if ($process.ExitCode -ne 0) {
    throw "Installer exited with $($process.ExitCode)."
  }
}

if (Get-CmlUninstallEntry) {
  throw "An existing CML installation is registered. Uninstall it explicitly before running this isolated recovery smoke."
}
if (Get-Process -Name CML -ErrorAction SilentlyContinue) {
  throw "A CML process is running. Close it before running installer recovery smoke."
}

$parent = Split-Path -Parent $installRoot
New-Item -ItemType Directory -Force -Path $parent | Out-Null
if (Test-Path -LiteralPath $installRoot) {
  Remove-Item -LiteralPath $installRoot -Recurse -Force
}

$results = [ordered]@{
  installer = $installer
  install_directory = $installRoot
  interrupted_install_recovered = $false
  same_version_repair = $false
  locked_payload_preserved = $false
  post_lock_repair = $false
  uninstall_completed = $false
}

try {
  Write-Host "Starting and interrupting an isolated install..."
  $interrupted = Start-Process -FilePath $installer -ArgumentList @("/S", "/D=$installRoot") -PassThru -WindowStyle Hidden
  $interruptDeadline = (Get-Date).AddSeconds(30)
  while (-not $interrupted.HasExited -and (Get-Date) -lt $interruptDeadline) {
    $fileCount = if (Test-Path -LiteralPath $installRoot) {
      @(Get-ChildItem -LiteralPath $installRoot -File -Recurse -ErrorAction SilentlyContinue).Count
    } else { 0 }
    if ($fileCount -ge 10) { break }
    Start-Sleep -Milliseconds 250
  }
  if (-not $interrupted.HasExited) {
    Stop-ProcessTree -RootPid $interrupted.Id
  }
  Start-Sleep -Seconds 2

  Write-Host "Recovering from the interrupted install..."
  Invoke-Installer
  $installedExe = Join-Path $installRoot "CML.exe"
  if (-not (Test-Path -LiteralPath $installedExe)) { throw "Recovery install did not produce CML.exe." }
  $results.interrupted_install_recovered = $true
  $originalExeHash = (Get-FileHash -LiteralPath $installedExe -Algorithm SHA256).Hash

  Write-Host "Running same-version reinstall/repair..."
  Invoke-Installer
  if ((Get-FileHash -LiteralPath $installedExe -Algorithm SHA256).Hash -ne $originalExeHash) {
    throw "Same-version repair changed the packaged executable unexpectedly."
  }
  $results.same_version_repair = $true

  $lockedPayload = Join-Path $installRoot "resources\app.asar"
  if (-not (Test-Path -LiteralPath $lockedPayload)) { throw "Installed app.asar was not found." }
  $payloadHash = (Get-FileHash -LiteralPath $lockedPayload -Algorithm SHA256).Hash
  Write-Host "Exercising reinstall while app.asar is exclusively locked..."
  $lock = [System.IO.File]::Open($lockedPayload, "Open", "Read", "None")
  try {
    $lockedInstaller = Start-Process -FilePath $installer -ArgumentList @("/S", "/D=$installRoot") -PassThru -WindowStyle Hidden
    if (-not $lockedInstaller.WaitForExit(120 * 1000)) {
      Stop-ProcessTree -RootPid $lockedInstaller.Id
      $results.locked_installer_outcome = "bounded_timeout"
    }
    else {
      $results.locked_installer_outcome = "exit_$($lockedInstaller.ExitCode)"
    }
  }
  finally {
    $lock.Dispose()
  }
  if (-not (Test-Path -LiteralPath $installedExe) -or -not (Test-Path -LiteralPath $lockedPayload)) {
    throw "Locked-file reinstall removed a required installed payload."
  }
  if ((Get-FileHash -LiteralPath $lockedPayload -Algorithm SHA256).Hash -ne $payloadHash) {
    throw "Locked-file reinstall corrupted app.asar."
  }
  $results.locked_payload_preserved = $true

  Write-Host "Repairing after releasing the locked payload..."
  Invoke-Installer
  if (-not (Test-Path -LiteralPath $installedExe)) { throw "Post-lock repair did not restore CML.exe." }
  $results.post_lock_repair = $true
}
finally {
  Get-Process -Name CML -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  $entry = Get-CmlUninstallEntry
  if ($entry) {
    $uninstallCommand = [string]$(if ($entry.QuietUninstallString) { $entry.QuietUninstallString } else { $entry.UninstallString })
    $uninstaller = if ($uninstallCommand -match '^"([^"]+\.exe)"') { $Matches[1] } elseif ($uninstallCommand -match '^(.+?\.exe)') { $Matches[1] } else { "" }
    if ($uninstaller -and (Test-Path -LiteralPath $uninstaller)) {
      $uninstall = Start-Process -FilePath $uninstaller -ArgumentList @("/S", "/currentuser") -PassThru -WindowStyle Hidden
      if ($uninstall.WaitForExit($TimeoutSeconds * 1000) -and $uninstall.ExitCode -eq 0) {
        $results.uninstall_completed = $true
      }
      else { Stop-ProcessTree -RootPid $uninstall.Id }
    }
  }
  $results.completed_at = (Get-Date).ToUniversalTime().ToString("o")
  $results | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding utf8
}

if (-not $results.uninstall_completed) { throw "Recovery smoke could not verify final uninstall." }
$results | ConvertTo-Json -Depth 5

