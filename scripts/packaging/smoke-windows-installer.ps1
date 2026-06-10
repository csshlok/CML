param(
  [string]$InstallerPath = "",
  [int]$TimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
if (-not $InstallerPath) {
  throw "InstallerPath is required. Pass the explicit NSIS installer path to smoke-windows-installer.ps1."
}
$installer = [System.IO.Path]::GetFullPath($InstallerPath)
if (-not (Test-Path -LiteralPath $installer)) {
  throw "Installer not found: $installer"
}

function Stop-CmlProcess {
  Get-Process -Name "CML" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}

function Get-CmlUninstallEntry {
  $roots = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
    "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
  )
  foreach ($root in $roots) {
    if (-not (Test-Path $root)) {
      continue
    }
    $entry = Get-ChildItem $root -ErrorAction SilentlyContinue |
      ForEach-Object {
        try {
          Get-ItemProperty -LiteralPath $_.PsPath
        } catch {
          $null
        }
      } |
      Where-Object {
        $_.DisplayName -eq "CML" -or
          $_.DisplayName -like "CML *" -or
          $_.Publisher -eq "CML"
      } |
      Select-Object -First 1
    if ($entry) {
      return $entry
    }
  }
  return $null
}

function Invoke-SilentExecutable {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string[]]$Arguments,
    [Parameter(Mandatory = $true)][int]$Timeout
  )
  $process = Start-Process -FilePath $Path -ArgumentList $Arguments -PassThru -WindowStyle Hidden
  if (-not $process.WaitForExit($Timeout * 1000)) {
    try {
      $process.Kill()
    } catch {
      Write-Warning "Could not terminate timed-out process $Path`: $($_.Exception.Message)"
    }
    throw "Timed out waiting for $Path"
  }
  if ($process.ExitCode -ne 0) {
    throw "$Path exited with $($process.ExitCode)"
  }
}

Stop-CmlProcess

Write-Host "Installing CML silently from $installer"
$electronRunAsNode = $env:ELECTRON_RUN_AS_NODE
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
try {
  Invoke-SilentExecutable -Path $installer -Arguments @("/S") -Timeout $TimeoutSeconds
} finally {
  if ($electronRunAsNode -ne $null) {
    $env:ELECTRON_RUN_AS_NODE = $electronRunAsNode
  }
}
Start-Sleep -Seconds 3
Stop-CmlProcess

$entry = Get-CmlUninstallEntry
if (-not $entry) {
  throw "CML uninstall registry entry was not created."
}

$installLocation = $entry.InstallLocation
if (-not $installLocation) {
  $displayIcon = [string]$entry.DisplayIcon
  if ($displayIcon -match '^(.+?\.exe)') {
    $installLocation = Split-Path -Parent $Matches[1].Trim('"')
  }
}
if (-not $installLocation) {
  $quietUninstall = [string]$entry.QuietUninstallString
  if ($quietUninstall -match '^"([^"]+)"') {
    $installLocation = Split-Path -Parent $Matches[1]
  }
}
if (-not $installLocation) {
  throw "CML install location was not present in the uninstall registry entry."
}
$installedExe = Join-Path $installLocation "CML.exe"
if (-not (Test-Path -LiteralPath $installedExe)) {
  throw "Installed CML.exe not found: $installedExe"
}

$uninstallString = [string]$entry.QuietUninstallString
if (-not $uninstallString) {
  $uninstallString = [string]$entry.UninstallString
}
if (-not $uninstallString) {
  throw "CML uninstall command is missing from registry."
}

$uninstaller = $uninstallString.Trim('"')
if ($uninstaller -match '^"([^"]+)"') {
  $uninstaller = $Matches[1]
} elseif ($uninstaller -match '^(.+?\.exe)') {
  $uninstaller = $Matches[1]
}
if (-not (Test-Path -LiteralPath $uninstaller)) {
  throw "Uninstaller not found: $uninstaller"
}

Write-Host "Uninstalling CML silently from $uninstaller"
Invoke-SilentExecutable -Path $uninstaller -Arguments @("/S", "/currentuser") -Timeout $TimeoutSeconds
for ($i = 0; $i -lt $TimeoutSeconds; $i++) {
  Stop-CmlProcess
  if (-not (Test-Path -LiteralPath $installedExe)) {
    break
  }
  Start-Sleep -Seconds 1
}

if (Test-Path -LiteralPath $installedExe) {
  throw "Installed executable still exists after uninstall: $installedExe"
}

[ordered]@{
  installer = $installer
  install_location = $installLocation
  installed_exe_created = $true
  uninstall_entry_created = $true
  uninstall_completed = $true
  appdata_preserved_policy = "deleteAppDataOnUninstall=false"
} | ConvertTo-Json -Depth 5
