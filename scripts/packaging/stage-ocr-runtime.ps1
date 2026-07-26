param(
  [string]$Destination = "",
  [string]$CacheDir = "",
  [string]$TesseractExePath = "",
  [string]$GhostscriptExePath = "",
  [switch]$SkipTesseractInstaller,
  [switch]$SkipGhostscriptInstaller,
  [int]$TesseractInstallTimeoutSeconds = 120,
  [int]$GhostscriptInstallTimeoutSeconds = 120,
  [switch]$AllowPartial
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
if (-not $Destination) {
  $Destination = Join-Path $repoRoot "backend\bin\ocr"
}
if (-not $CacheDir) {
  $CacheDir = Join-Path $repoRoot ".tmp\ocr-download-cache"
}

$destinationPath = [System.IO.Path]::GetFullPath($Destination)
$cachePath = [System.IO.Path]::GetFullPath($CacheDir)
New-Item -ItemType Directory -Force -Path $destinationPath | Out-Null
New-Item -ItemType Directory -Force -Path $cachePath | Out-Null

function Invoke-Download {
  param(
    [Parameter(Mandatory = $true)][string]$Uri,
    [Parameter(Mandatory = $true)][string]$OutFile
  )
  if (Test-Path -LiteralPath $OutFile) {
    return
  }
  Write-Host "Downloading $Uri"
  Invoke-WebRequest -Uri $Uri -OutFile $OutFile -UseBasicParsing
}

function Expand-Zip {
  param(
    [Parameter(Mandatory = $true)][string]$Archive,
    [Parameter(Mandatory = $true)][string]$Target
  )
  if (Test-Path -LiteralPath $Target) {
    Remove-Item -LiteralPath $Target -Recurse -Force
  }
  New-Item -ItemType Directory -Force -Path $Target | Out-Null
  Expand-Archive -LiteralPath $Archive -DestinationPath $Target -Force
}

function Copy-FirstMatch {
  param(
    [Parameter(Mandatory = $true)][string]$Root,
    [Parameter(Mandatory = $true)][string]$Filter,
    [Parameter(Mandatory = $true)][string]$Target
  )
  $match = Get-ChildItem -LiteralPath $Root -Recurse -Filter $Filter -File -ErrorAction SilentlyContinue |
    Select-Object -First 1
  if (-not $match) {
    return $false
  }
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Target) | Out-Null
  Copy-Item -LiteralPath $match.FullName -Destination $Target -Force
  return $true
}

function Copy-TreeContaining {
  param(
    [Parameter(Mandatory = $true)][string]$Root,
    [Parameter(Mandatory = $true)][string]$Filter,
    [Parameter(Mandatory = $true)][string]$TargetDir
  )
  $match = Get-ChildItem -LiteralPath $Root -Recurse -Filter $Filter -File -ErrorAction SilentlyContinue |
    Select-Object -First 1
  if (-not $match) {
    return $false
  }
  $sourceDir = Split-Path -Parent $match.FullName
  if (Test-Path -LiteralPath $TargetDir) {
    Remove-Item -LiteralPath $TargetDir -Recurse -Force
  }
  New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
  Copy-Item -Path (Join-Path $sourceDir "*") -Destination $TargetDir -Recurse -Force
  return $true
}

function Copy-GhostscriptRuntime {
  param(
    [Parameter(Mandatory = $true)][string]$ExePath,
    [Parameter(Mandatory = $true)][string]$TargetDir
  )
  $resolvedExe = [System.IO.Path]::GetFullPath($ExePath)
  $binDir = Split-Path -Parent $resolvedExe
  $runtimeRoot = Split-Path -Parent $binDir
  if ((Split-Path -Leaf $binDir) -ne "bin") {
    $runtimeRoot = $binDir
  }
  if (Test-Path -LiteralPath $TargetDir) {
    Remove-Item -LiteralPath $TargetDir -Recurse -Force
  }
  New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
  Copy-Item -Path (Join-Path $runtimeRoot "*") -Destination $TargetDir -Recurse -Force
}

function Find-InstalledTesseract {
  $command = Get-Command tesseract -ErrorAction SilentlyContinue
  if ($command -and $command.Source -and (Test-Path -LiteralPath $command.Source)) {
    return $command.Source
  }
  $candidates = @(
    "$env:LOCALAPPDATA\Programs\Tesseract-OCR\tesseract.exe",
    "$env:ProgramFiles\Tesseract-OCR\tesseract.exe",
    "${env:ProgramFiles(x86)}\Tesseract-OCR\tesseract.exe"
  )
  foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path -LiteralPath $candidate)) {
      return $candidate
    }
  }
  return ""
}

function Find-InstalledGhostscript {
  $command = Get-Command gswin64c -ErrorAction SilentlyContinue
  if ($command -and $command.Source -and (Test-Path -LiteralPath $command.Source)) {
    return $command.Source
  }
  $roots = @(
    "$env:ProgramFiles\gs",
    "${env:ProgramFiles(x86)}\gs"
  )
  foreach ($root in $roots) {
    if (-not $root -or -not (Test-Path -LiteralPath $root)) {
      continue
    }
    $candidate = Get-ChildItem -LiteralPath $root -Recurse -Filter "gswin64c.exe" -File -ErrorAction SilentlyContinue |
      Sort-Object FullName -Descending |
      Select-Object -First 1
    if ($candidate) {
      return $candidate.FullName
    }
  }
  return ""
}

function Test-TesseractExecutable {
  param([Parameter(Mandatory = $true)][string]$Path)
  try {
    $process = Start-Process -FilePath $Path -ArgumentList @("--version") -Wait -PassThru -WindowStyle Hidden
    return $process.ExitCode -eq 0
  } catch {
    return $false
  }
}

function Test-GhostscriptExecutable {
  param([Parameter(Mandatory = $true)][string]$Path)
  try {
    $process = Start-Process -FilePath $Path -ArgumentList @("--version") -Wait -PassThru -WindowStyle Hidden
    return $process.ExitCode -eq 0
  } catch {
    return $false
  }
}

$errors = New-Object System.Collections.Generic.List[string]

try {
  $engPath = Join-Path $destinationPath "tessdata\eng.traineddata"
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $engPath) | Out-Null
  Invoke-Download `
    -Uri "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/eng.traineddata" `
    -OutFile $engPath
} catch {
  $errors.Add("Could not stage eng.traineddata: $($_.Exception.Message)")
}

try {
  if (-not $TesseractExePath) {
    $TesseractExePath = Find-InstalledTesseract
    if ($TesseractExePath) {
      Write-Host "Using installed Tesseract at $TesseractExePath"
    }
  }
  if ($TesseractExePath) {
    if (-not (Test-Path -LiteralPath $TesseractExePath)) {
      throw "TesseractExePath does not exist: $TesseractExePath"
    }
    if (-not (Test-TesseractExecutable -Path $TesseractExePath)) {
      throw "TesseractExePath is not executable: $TesseractExePath"
    }
    $tesseractDir = Split-Path -Parent ([System.IO.Path]::GetFullPath($TesseractExePath))
    Copy-Item -Path (Join-Path $tesseractDir "*") -Destination $destinationPath -Recurse -Force
  } elseif (-not $SkipTesseractInstaller) {
    $installer = Join-Path $cachePath "tesseract-ocr-w64-setup-5.5.0.20241111.exe"
    Invoke-Download `
      -Uri "https://github.com/tesseract-ocr/tesseract/releases/download/5.5.0/tesseract-ocr-w64-setup-5.5.0.20241111.exe" `
      -OutFile $installer
    $tesseractTarget = Join-Path $cachePath "tesseract-local"
    if (Test-Path -LiteralPath $tesseractTarget) {
      Remove-Item -LiteralPath $tesseractTarget -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $tesseractTarget | Out-Null
    $process = Start-Process `
      -FilePath $installer `
      -ArgumentList @("/S", "/D=$tesseractTarget") `
      -PassThru `
      -WindowStyle Hidden
    if (-not $process.WaitForExit($TesseractInstallTimeoutSeconds * 1000)) {
      try {
        $process.Kill()
      } catch {
        Write-Warning "Could not terminate timed-out Tesseract installer: $($_.Exception.Message)"
      }
      throw "Tesseract installer timed out after $TesseractInstallTimeoutSeconds second(s)."
    }
    if ($process.ExitCode -ne 0) {
      throw "Tesseract installer exited with $($process.ExitCode)."
    }
    $stagedTesseract = Join-Path $tesseractTarget "tesseract.exe"
    if (-not (Test-Path -LiteralPath $stagedTesseract)) {
      throw "tesseract.exe was not found after local install."
    }
    Copy-Item -Path (Join-Path $tesseractTarget "*") -Destination $destinationPath -Recurse -Force
  }
} catch {
  $errors.Add("Could not stage tesseract.exe: $($_.Exception.Message)")
}

try {
  $qpdfRelease = Invoke-RestMethod -Uri "https://api.github.com/repos/qpdf/qpdf/releases/latest"
  $qpdfAsset = $qpdfRelease.assets |
    Where-Object { $_.name -match "msvc64\.zip$" } |
    Select-Object -First 1
  if (-not $qpdfAsset) {
    throw "No qpdf msvc64 zip asset found."
  }
  $qpdfZip = Join-Path $cachePath $qpdfAsset.name
  $qpdfExtract = Join-Path $cachePath "qpdf"
  Invoke-Download -Uri $qpdfAsset.browser_download_url -OutFile $qpdfZip
  Expand-Zip -Archive $qpdfZip -Target $qpdfExtract
  if (-not (Copy-TreeContaining -Root $qpdfExtract -Filter "qpdf.exe" -TargetDir (Join-Path $destinationPath "qpdf"))) {
    throw "qpdf.exe was not found after extraction."
  }
} catch {
  $errors.Add("Could not stage qpdf: $($_.Exception.Message)")
}

try {
  if (-not $GhostscriptExePath) {
    $GhostscriptExePath = Find-InstalledGhostscript
    if ($GhostscriptExePath) {
      Write-Host "Using installed Ghostscript at $GhostscriptExePath"
    }
  }
  if ($GhostscriptExePath) {
    if (-not (Test-Path -LiteralPath $GhostscriptExePath)) {
      throw "GhostscriptExePath does not exist: $GhostscriptExePath"
    }
    if (-not (Test-GhostscriptExecutable -Path $GhostscriptExePath)) {
      throw "GhostscriptExePath is not executable: $GhostscriptExePath"
    }
    Copy-GhostscriptRuntime -ExePath $GhostscriptExePath -TargetDir (Join-Path $destinationPath "ghostscript")
  } elseif ($SkipGhostscriptInstaller) {
    throw "Ghostscript staging skipped by -SkipGhostscriptInstaller."
  } else {
    $gsRelease = Invoke-RestMethod -Uri "https://api.github.com/repos/ArtifexSoftware/ghostpdl-downloads/releases/latest"
    $gsAsset = $gsRelease.assets |
      Where-Object { $_.name -match "w64\.exe$" } |
      Select-Object -First 1
    if (-not $gsAsset) {
      throw "No Ghostscript win64 installer asset found."
    }
    $gsInstaller = Join-Path $cachePath $gsAsset.name
    Invoke-Download -Uri $gsAsset.browser_download_url -OutFile $gsInstaller
    Copy-Item -LiteralPath $gsInstaller -Destination (Join-Path $destinationPath "ghostscript-installer.exe") -Force

    $gsTarget = Join-Path $destinationPath "ghostscript"
    $process = Start-Process -FilePath $gsInstaller -ArgumentList @("/S", "/D=$gsTarget") -PassThru -WindowStyle Hidden
    if (-not $process.WaitForExit($GhostscriptInstallTimeoutSeconds * 1000)) {
      try {
        $process.Kill()
      } catch {
        Write-Warning "Could not terminate timed-out Ghostscript installer: $($_.Exception.Message)"
      }
      throw "Ghostscript installer timed out after $GhostscriptInstallTimeoutSeconds second(s)."
    }
    if ($process.ExitCode -ne 0) {
      throw "Ghostscript installer exited with $($process.ExitCode)."
    }
    $gsExe = Get-ChildItem -LiteralPath $gsTarget -Recurse -Filter "gswin64c.exe" -File -ErrorAction SilentlyContinue |
      Select-Object -First 1
    if (-not $gsExe) {
      throw "gswin64c.exe was not found after local install."
    }
  }
} catch {
  $errors.Add("Could not stage Ghostscript: $($_.Exception.Message)")
}

$bundledGhostscript = Get-ChildItem -LiteralPath (Join-Path $destinationPath "ghostscript") -Recurse -Filter "gswin64c.exe" -File -ErrorAction SilentlyContinue |
  Select-Object -First 1

$manifest = [ordered]@{
  generated_at = (Get-Date).ToUniversalTime().ToString("o")
  layout = "self-contained-ocr-runtime-v1"
  tesseract = (Test-Path -LiteralPath (Join-Path $destinationPath "tesseract.exe")) -and (Test-TesseractExecutable -Path (Join-Path $destinationPath "tesseract.exe"))
  eng_traineddata = Test-Path -LiteralPath (Join-Path $destinationPath "tessdata\eng.traineddata")
  qpdf = (Get-ChildItem -LiteralPath (Join-Path $destinationPath "qpdf") -Recurse -Filter "qpdf.exe" -File -ErrorAction SilentlyContinue | Select-Object -First 1) -ne $null
  ghostscript = $bundledGhostscript -ne $null -and (Test-GhostscriptExecutable -Path $bundledGhostscript.FullName)
  errors = @($errors)
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $destinationPath "manifest.json") -Encoding UTF8

if ($errors.Count -gt 0) {
  $errors | ForEach-Object { Write-Warning $_ }
  if (-not $AllowPartial) {
    throw "OCR runtime staging incomplete. Re-run with -AllowPartial to keep partial downloads, or fix the missing component(s)."
  }
}

Write-Host "OCR runtime staging complete at $destinationPath"
