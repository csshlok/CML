param(
  [string]$Destination = "",
  [string]$CacheDir = "",
  [string]$TesseractExePath = "",
  [switch]$SkipTesseractInstaller,
  [switch]$SkipGhostscriptInstaller,
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
  if ($TesseractExePath) {
    if (-not (Test-Path -LiteralPath $TesseractExePath)) {
      throw "TesseractExePath does not exist: $TesseractExePath"
    }
    $tesseractDir = Split-Path -Parent ([System.IO.Path]::GetFullPath($TesseractExePath))
    Copy-Item -Path (Join-Path $tesseractDir "*") -Destination $destinationPath -Recurse -Force
  } elseif (-not $SkipTesseractInstaller) {
    $installer = Join-Path $cachePath "tesseract-ocr-w64-setup-5.5.0.20241111.exe"
    Invoke-Download `
      -Uri "https://github.com/tesseract-ocr/tesseract/releases/download/5.5.0/tesseract-ocr-w64-setup-5.5.0.20241111.exe" `
      -OutFile $installer
    Copy-Item -LiteralPath $installer -Destination (Join-Path $destinationPath "tesseract-installer.exe") -Force
    $errors.Add("Downloaded Tesseract installer, but no portable tesseract.exe was staged. Pass -TesseractExePath after installing/extracting it, or provide a portable Tesseract source.")
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
  if ($SkipGhostscriptInstaller) {
    throw "Ghostscript staging skipped by -SkipGhostscriptInstaller."
  }
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
} catch {
  $errors.Add("Could not stage Ghostscript: $($_.Exception.Message)")
}

$manifest = [ordered]@{
  generated_at = (Get-Date).ToUniversalTime().ToString("o")
  destination = $destinationPath
  tesseract = Test-Path -LiteralPath (Join-Path $destinationPath "tesseract.exe")
  eng_traineddata = Test-Path -LiteralPath (Join-Path $destinationPath "tessdata\eng.traineddata")
  qpdf = (Get-ChildItem -LiteralPath (Join-Path $destinationPath "qpdf") -Recurse -Filter "qpdf.exe" -File -ErrorAction SilentlyContinue | Select-Object -First 1) -ne $null
  ghostscript = (Get-ChildItem -LiteralPath (Join-Path $destinationPath "ghostscript") -Recurse -Filter "gswin64c.exe" -File -ErrorAction SilentlyContinue | Select-Object -First 1) -ne $null
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
