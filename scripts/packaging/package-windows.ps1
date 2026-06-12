param(
  [switch]$Release,
  [switch]$PackagedOnly,
  [switch]$IncludeEmbeddingRuntime,
  [switch]$SkipOcrRuntimeDownload,
  [string]$TesseractExePath = "",
  [string]$GhostscriptExePath = "",
  [switch]$SkipGhostscriptInstaller,
  [switch]$AllowPartialOcrRuntime,
  [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$desktopDir = Join-Path $repoRoot "apps\desktop"
$desktopPackageJsonPath = Join-Path $desktopDir "package.json"
$backendDir = Join-Path $repoRoot "backend"
$stagingDir = Join-Path $desktopDir "packaging\backend"
$runtimeDir = Join-Path $desktopDir "packaging\python-runtime"
$expertRuntimeDir = Join-Path $desktopDir "packaging\expert-python-runtime"
$playwrightBrowserDir = Join-Path $desktopDir "packaging\ms-playwright"
$packagingRoot = Join-Path $desktopDir "packaging"
$releaseDir = Join-Path $desktopDir "release"
$tmpDir = Join-Path $repoRoot ".tmp"
$helperManifestScript = Join-Path $repoRoot "scripts\packaging\generate-helper-manifest.cjs"
$packageAuditScript = Join-Path $repoRoot "scripts\packaging\audit-package-layout.cjs"
$ocrStagingScript = Join-Path $repoRoot "scripts\packaging\stage-ocr-runtime.ps1"
$desktopPackage = Get-Content $desktopPackageJsonPath -Raw | ConvertFrom-Json
$desktopVersion = [string]$desktopPackage.version
if (-not $desktopVersion) {
  throw "Could not resolve desktop version from $desktopPackageJsonPath"
}
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}
$basePythonRoot = (& $python -c "import sys; print(sys.base_prefix)") | Select-Object -First 1
if (-not $basePythonRoot -or -not (Test-Path $basePythonRoot)) {
  throw "Could not resolve a portable base Python runtime from $python"
}

$backendRuntimePackages = @(
  "fastapi==0.136.3",
  "uvicorn[standard]==0.48.0",
  "pydantic-settings==2.14.1",
  "cryptography==47.0.0",
  "numpy==2.4.6",
  "pypdf==6.12.2",
  "python-docx==1.2.0",
  "PyMuPDF==1.26.7",
  "ocrmypdf==17.5.0",
  "playwright==1.60.0"
)
$expertRuntimePackages = @(
  "torch==2.12.0",
  "transformers==5.6.0",
  "peft==0.18.1"
)
$embeddingRuntimePackages = @(
  "sentence-transformers==5.5.1"
)
$effectiveBackendRuntimePackages = @($backendRuntimePackages)
if ($IncludeEmbeddingRuntime) {
  $effectiveBackendRuntimePackages += $embeddingRuntimePackages
}

$script:PackageStartedAt = Get-Date
$script:PackagePhaseStartedAt = $script:PackageStartedAt
$script:PackagePhaseIndex = 0
$script:PackagePhaseCount = 10
if ($Release) {
  $script:PackagePhaseCount += 1
}
if ($IncludeEmbeddingRuntime) {
  $script:PackagePhaseCount += 1
}

function Format-Duration([TimeSpan]$Duration) {
  if ($Duration.TotalHours -ge 1) {
    return "{0:00}:{1:00}:{2:00}" -f [int]$Duration.TotalHours, $Duration.Minutes, $Duration.Seconds
  }
  return "{0:00}:{1:00}" -f $Duration.Minutes, $Duration.Seconds
}

function Format-FileSize([long]$Bytes) {
  if ($Bytes -ge 1GB) {
    return "{0:n2} GB" -f ($Bytes / 1GB)
  }
  if ($Bytes -ge 1MB) {
    return "{0:n1} MB" -f ($Bytes / 1MB)
  }
  if ($Bytes -ge 1KB) {
    return "{0:n1} KB" -f ($Bytes / 1KB)
  }
  return "$Bytes B"
}

function Write-PackageLine([string]$Message, [string]$Level = "INFO") {
  $elapsed = Format-Duration ((Get-Date) - $script:PackageStartedAt)
  Write-Host ("[{0}] [{1}] {2}" -f $elapsed, $Level, $Message)
}

function Start-PackagePhase([string]$Name, [string]$Detail = "") {
  $script:PackagePhaseIndex += 1
  $script:PackagePhaseStartedAt = Get-Date
  $percent = [Math]::Min(99, [Math]::Max(0, [int](($script:PackagePhaseIndex - 1) * 100 / $script:PackagePhaseCount)))
  Write-Progress -Activity "CML Windows package" -Status "$($script:PackagePhaseIndex)/$($script:PackagePhaseCount) $Name" -PercentComplete $percent
  Write-PackageLine "[$($script:PackagePhaseIndex)/$($script:PackagePhaseCount)] $Name"
  if ($Detail) {
    Write-PackageLine "  $Detail" "DETAIL"
  }
}

function Complete-PackagePhase([string]$Detail = "") {
  $duration = Format-Duration ((Get-Date) - $script:PackagePhaseStartedAt)
  $message = "completed in $duration"
  if ($Detail) {
    $message = "$message; $Detail"
  }
  Write-PackageLine $message "DONE"
}

function Write-PackageDetail([string]$Message) {
  Write-PackageLine "  $Message" "DETAIL"
}

function Get-StringFingerprint([string[]]$Parts) {
  $text = [string]::Join("`n", $Parts)
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($text)
  $hashBytes = [System.Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
  return ([System.BitConverter]::ToString($hashBytes)).Replace("-", "").ToLowerInvariant()
}

function Test-StagedRuntime(
  [string]$RuntimeDir,
  [string]$StampPath,
  [string]$ExpectedFingerprint,
  [string[]]$RequiredPaths
) {
  if (-not (Test-Path $RuntimeDir) -or -not (Test-Path $StampPath)) {
    return $false
  }
  $actualFingerprint = (Get-Content $StampPath -Raw).Trim()
  if ($actualFingerprint -ne $ExpectedFingerprint) {
    return $false
  }
  foreach ($requiredPath in $RequiredPaths) {
    if (-not (Test-Path $requiredPath)) {
      return $false
    }
  }
  return $true
}

function Write-StagedRuntimeStamp([string]$StampPath, [string]$Fingerprint) {
  Set-Content -Path $StampPath -Value $Fingerprint -Encoding ascii
}

function Reset-StagedPath([string]$TargetPath) {
  if (Test-Path $TargetPath) {
    Remove-Item -Recurse -Force $TargetPath
  }
}

function Copy-PortablePythonRuntime([string]$SourceRoot, [string]$DestinationRoot) {
  Reset-StagedPath $DestinationRoot
  New-Item -ItemType Directory -Force -Path $DestinationRoot | Out-Null
  $null = robocopy $SourceRoot $DestinationRoot /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NC /NS /NP
  if ($LASTEXITCODE -ge 8) {
    throw "Failed to copy portable Python runtime from $SourceRoot to $DestinationRoot"
  }
}

function Remove-PathIfPresent([string]$TargetPath) {
  if (Test-Path -LiteralPath $TargetPath) {
    Remove-Item -LiteralPath $TargetPath -Recurse -Force -ErrorAction Stop
  }
}

function Remove-ChildByPatterns([string]$ParentPath, [string[]]$Patterns) {
  if (-not (Test-Path -LiteralPath $ParentPath)) {
    return
  }
  foreach ($pattern in $Patterns) {
    Get-ChildItem -LiteralPath $ParentPath -Filter $pattern -Force -ErrorAction SilentlyContinue |
      ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop
      }
  }
}

function Remove-PythonCaches([string]$RootPath) {
  if (-not (Test-Path -LiteralPath $RootPath)) {
    return
  }
  Get-ChildItem -LiteralPath $RootPath -Recurse -Directory -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq "__pycache__" } |
    ForEach-Object {
      Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop
    }

  Get-ChildItem -LiteralPath $RootPath -Recurse -File -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -in @(".pyc", ".pyo") } |
    ForEach-Object {
      Remove-Item -LiteralPath $_.FullName -Force -ErrorAction Stop
    }
}

function Optimize-PortablePythonRuntime([string]$RuntimeRoot) {
  if (-not (Test-Path -LiteralPath $RuntimeRoot)) {
    throw "Cannot optimize missing runtime root: $RuntimeRoot"
  }

  Write-PackageDetail "Pruning non-runtime payload from $RuntimeRoot"

  $rootPrune = @(
    "Doc",
    "Tools",
    "include"
  )
  foreach ($relativePath in $rootPrune) {
    Remove-PathIfPresent (Join-Path $RuntimeRoot $relativePath)
  }

  $libPrune = @(
    "test",
    "tests",
    "ensurepip",
    "idlelib",
    "tkinter",
    "turtledemo",
    "venv"
  )
  foreach ($relativePath in $libPrune) {
    Remove-PathIfPresent (Join-Path $RuntimeRoot "Lib\$relativePath")
  }

  $sitePackagesRoot = Join-Path $RuntimeRoot "Lib\site-packages"
  if (Test-Path -LiteralPath $sitePackagesRoot) {
    $sitePackagesPrune = @(
      "pip",
      "pip-*",
      "setuptools",
      "setuptools-*",
      "wheel",
      "wheel-*"
    )
    Remove-ChildByPatterns $sitePackagesRoot $sitePackagesPrune
  }

  Get-ChildItem -LiteralPath $RuntimeRoot -Recurse -Directory -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq "__pycache__" } |
    ForEach-Object {
      Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop
    }

  Get-ChildItem -LiteralPath $RuntimeRoot -Recurse -File -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -in @(".pyc", ".pyo") } |
    ForEach-Object {
      Remove-Item -LiteralPath $_.FullName -Force -ErrorAction Stop
    }
}

if (-not $OutputDir) {
  throw "OutputDir is required. Pass an explicit package output directory."
}
$outputDirPath = [System.IO.Path]::GetFullPath($OutputDir)

Write-PackageLine "CML Windows package build starting"
Write-PackageDetail "Version: $desktopVersion"
Write-PackageDetail "Mode: $(if ($Release) { "release" } else { "dev/test" })"
Write-PackageDetail "Target: $(if ($PackagedOnly) { "packaged directory only" } else { "NSIS installer + unpacked app" })"
Write-PackageDetail "Output: $outputDirPath"
Write-PackageDetail "Base Python: $basePythonRoot"

Start-PackagePhase "Clear previous output" "Removing old artifacts from output directory."
if (Test-Path $outputDirPath) {
  Remove-Item -Recurse -Force $outputDirPath
}
New-Item -ItemType Directory -Force -Path $outputDirPath | Out-Null
Complete-PackagePhase $outputDirPath

if ($Release) {
  Start-PackagePhase "Clear release caches" "Release builds rebuild helper runtimes from scratch."
  Reset-StagedPath $runtimeDir
  Reset-StagedPath $expertRuntimeDir
  Reset-StagedPath $playwrightBrowserDir
  if (-not $SkipOcrRuntimeDownload) {
    Reset-StagedPath (Join-Path $backendDir "bin\ocr")
  }
  Complete-PackagePhase
}

Start-PackagePhase "Build desktop renderer" "Running npm run build in $desktopDir."
Push-Location $desktopDir
try {
  npm run build
} finally {
  Pop-Location
}
Complete-PackagePhase "dist/client and dist/server refreshed"

Start-PackagePhase "Stage backend source" "Copying backend app, pyproject, and OCR bin payload if present."
if (Test-Path $stagingDir) {
  Remove-Item -Recurse -Force $stagingDir
}
New-Item -ItemType Directory -Force -Path $stagingDir | Out-Null

if (-not $SkipOcrRuntimeDownload) {
  $ocrRuntimeDir = Join-Path $backendDir "bin\ocr"
  $ocrManifestPath = Join-Path $ocrRuntimeDir "manifest.json"
  $ocrRuntimeFingerprint = Get-StringFingerprint @(
    "ocr-runtime-v1",
    "tesseract_path=$TesseractExePath",
    "ghostscript_path=$GhostscriptExePath",
    "skip_ghostscript=$($SkipGhostscriptInstaller.IsPresent)",
    "allow_partial=$($AllowPartialOcrRuntime.IsPresent)"
  )
  $ocrRuntimeStampPath = Join-Path $ocrRuntimeDir ".cml-ocr-stamp"
  $ocrRuntimeReady = $false
  if (-not $Release) {
    $ocrRuntimeReady = Test-StagedRuntime `
      -RuntimeDir $ocrRuntimeDir `
      -StampPath $ocrRuntimeStampPath `
      -ExpectedFingerprint $ocrRuntimeFingerprint `
      -RequiredPaths @(
        $ocrManifestPath,
        (Join-Path $ocrRuntimeDir "tessdata\eng.traineddata")
      )
  }

  if ($ocrRuntimeReady) {
    Write-PackageDetail "OCR runtime cache hit: $ocrRuntimeDir"
  } else {
    Write-PackageLine "Staging OCR runtime" "INFO"
    Write-PackageDetail "OCR runtime cache miss; staging OCR payload."
    $ocrArgs = @()
    if ($TesseractExePath) {
      $ocrArgs += @("-TesseractExePath", $TesseractExePath)
    }
    if ($GhostscriptExePath) {
      $ocrArgs += @("-GhostscriptExePath", $GhostscriptExePath)
    }
    if ($SkipGhostscriptInstaller) {
      $ocrArgs += "-SkipGhostscriptInstaller"
    }
    if ($AllowPartialOcrRuntime) {
      $ocrArgs += "-AllowPartial"
    }
    & $ocrStagingScript @ocrArgs
    Write-StagedRuntimeStamp $ocrRuntimeStampPath $ocrRuntimeFingerprint
  }
} else {
  Write-PackageDetail "OCR runtime staging skipped by flag."
}

Copy-Item -Recurse -Force (Join-Path $backendDir "app") (Join-Path $stagingDir "app")
if (Test-Path (Join-Path $backendDir "bin")) {
  Copy-Item -Recurse -Force (Join-Path $backendDir "bin") (Join-Path $stagingDir "bin")
}
Copy-Item -Force (Join-Path $backendDir "pyproject.toml") (Join-Path $stagingDir "pyproject.toml")
Remove-PythonCaches $stagingDir
Complete-PackagePhase $stagingDir

$runtimePython = Join-Path $runtimeDir "python.exe"
$backendRuntimeStampPath = Join-Path $runtimeDir ".cml-runtime-stamp"
$backendRuntimeFingerprint = Get-StringFingerprint @(
  "python-runtime-v6",
  "base_python_root=$basePythonRoot",
  "prune=docs-tests-pip",
  "dependency_policy=pinned",
  ($effectiveBackendRuntimePackages -join "`n")
)
$backendRuntimeReady = $false
if (-not $Release) {
  $backendRuntimeRequiredPaths = @($runtimePython)
  if ($IncludeEmbeddingRuntime) {
    $backendRuntimeRequiredPaths += (Join-Path $runtimeDir "Lib\site-packages\sentence_transformers")
  }
  $backendRuntimeReady = Test-StagedRuntime `
    -RuntimeDir $runtimeDir `
    -StampPath $backendRuntimeStampPath `
    -ExpectedFingerprint $backendRuntimeFingerprint `
    -RequiredPaths $backendRuntimeRequiredPaths
}

Start-PackagePhase "Backend Python runtime" "Fingerprint: $($backendRuntimeFingerprint.Substring(0, 12)); packages: $($effectiveBackendRuntimePackages.Count)"
if ($backendRuntimeReady) {
  Write-PackageDetail "Cache hit: $runtimeDir"
} else {
  Write-PackageDetail "Cache miss; copying base Python runtime."
  Copy-PortablePythonRuntime $basePythonRoot $runtimeDir
  Write-PackageDetail "Installing backend Python packages."
  & $runtimePython -I -m pip install --upgrade pip
  & $runtimePython -I -m pip install --upgrade @effectiveBackendRuntimePackages
  Optimize-PortablePythonRuntime $runtimeDir
  Write-StagedRuntimeStamp $backendRuntimeStampPath $backendRuntimeFingerprint
}
Complete-PackagePhase $runtimeDir

$playwrightStampPath = Join-Path $playwrightBrowserDir ".cml-playwright-stamp"
$playwrightFingerprint = Get-StringFingerprint @(
  "playwright-runtime-v1",
  "playwright==1.60.0"
)
$playwrightReady = $false
if (-not $Release) {
  $playwrightReady = Test-StagedRuntime `
    -RuntimeDir $playwrightBrowserDir `
    -StampPath $playwrightStampPath `
    -ExpectedFingerprint $playwrightFingerprint `
    -RequiredPaths @(
      (Join-Path $playwrightBrowserDir "chromium-*"),
      (Join-Path $playwrightBrowserDir "ffmpeg-*")
    )
}

$env:PLAYWRIGHT_BROWSERS_PATH = $playwrightBrowserDir
Start-PackagePhase "Playwright Chromium runtime" "Browser cache: $playwrightBrowserDir"
if ($playwrightReady) {
  Write-PackageDetail "Cache hit: $playwrightBrowserDir"
} else {
  Write-PackageDetail "Cache miss; installing Chromium browser payload."
  if (Test-Path $playwrightBrowserDir) {
    Remove-Item -Recurse -Force $playwrightBrowserDir
  }
  New-Item -ItemType Directory -Force -Path $playwrightBrowserDir | Out-Null
  & $runtimePython -m playwright install chromium
  Write-StagedRuntimeStamp $playwrightStampPath $playwrightFingerprint
}
Complete-PackagePhase $playwrightBrowserDir

if ($IncludeEmbeddingRuntime) {
  Start-PackagePhase "Optional embedding runtime" "Embedding runtime is included in the staged backend runtime fingerprint and package set."
  Complete-PackagePhase "sentence-transformers packaged with backend runtime"
}

$expertRuntimePython = Join-Path $expertRuntimeDir "python.exe"
$expertRuntimeStampPath = Join-Path $expertRuntimeDir ".cml-runtime-stamp"
$expertRuntimeFingerprint = Get-StringFingerprint @(
  "expert-runtime-v4",
  "base_python_root=$basePythonRoot",
  "prune=docs-tests-pip",
  "dependency_policy=pinned",
  ($expertRuntimePackages -join "`n")
)
$expertRuntimeReady = $false
if (-not $Release) {
  $expertRuntimeReady = Test-StagedRuntime `
    -RuntimeDir $expertRuntimeDir `
    -StampPath $expertRuntimeStampPath `
    -ExpectedFingerprint $expertRuntimeFingerprint `
    -RequiredPaths @(
      $expertRuntimePython,
      (Join-Path $expertRuntimeDir "Lib\site-packages\torch"),
      (Join-Path $expertRuntimeDir "Lib\site-packages\transformers"),
      (Join-Path $expertRuntimeDir "Lib\site-packages\peft")
    )
}

Start-PackagePhase "Expert Python runtime" "Fingerprint: $($expertRuntimeFingerprint.Substring(0, 12)); packages: $($expertRuntimePackages.Count)"
if ($expertRuntimeReady) {
  Write-PackageDetail "Cache hit: $expertRuntimeDir"
} else {
  Write-PackageDetail "Cache miss; copying base Python runtime."
  Copy-PortablePythonRuntime $basePythonRoot $expertRuntimeDir
  Write-PackageDetail "Installing expert Python packages."
  & $expertRuntimePython -I -m pip install --upgrade pip
  & $expertRuntimePython -I -m pip install --upgrade @expertRuntimePackages
  Optimize-PortablePythonRuntime $expertRuntimeDir
  Write-StagedRuntimeStamp $expertRuntimeStampPath $expertRuntimeFingerprint
}
Complete-PackagePhase $expertRuntimeDir

Start-PackagePhase "Helper integrity manifest" "Generating helper-manifest.json for packaged resources."
node $helperManifestScript
Complete-PackagePhase (Join-Path $packagingRoot "helper-manifest.json")

Start-PackagePhase "Package layout audit" "Checking packaged backend, runtimes, browser payload, and UI assets."
node $packageAuditScript $packagingRoot $packagingRoot
Complete-PackagePhase

$env:CSC_IDENTITY_AUTO_DISCOVERY = "false"
$builderCompression = if ($Release) { "maximum" } else { "store" }
$builderTarget = if ($PackagedOnly) { "dir" } else { "nsis" }
$builderConfigPath = Join-Path $tmpDir "electron-builder.generated.json"
Start-PackagePhase "Package Windows app" "electron-builder target=$builderTarget; compression=$builderCompression"
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
@"
{
  "appId": "local.cml.desktop",
  "productName": "CML",
  "electronVersion": "39.8.10",
  "compression": "$builderCompression",
  "directories": {
    "output": "$($outputDirPath.Replace("\", "\\"))"
  },
  "files": [
    "dist/**/*",
    "electron/**/*",
    "package.json"
  ],
  "extraResources": [
    {
      "from": "packaging/backend",
      "to": "backend",
      "filter": ["app/**/*", "bin/**/*", "pyproject.toml"]
    },
    {
      "from": "packaging/python-runtime",
      "to": "python-runtime",
      "filter": ["**/*"]
    },
    {
      "from": "packaging/expert-python-runtime",
      "to": "expert-python-runtime",
      "filter": ["**/*"]
    },
    {
      "from": "packaging/ms-playwright",
      "to": "ms-playwright",
      "filter": ["**/*"]
    },
    {
      "from": "packaging/helper-manifest.json",
      "to": "helper-manifest.json"
    }
  ],
  "win": {
    "target": "$builderTarget",
    "signAndEditExecutable": false,
    "forceCodeSigning": false,
    "requestedExecutionLevel": "asInvoker"
  },
  "nsis": {
    "oneClick": false,
    "perMachine": false,
    "allowElevation": false,
    "allowToChangeInstallationDirectory": true,
    "createDesktopShortcut": true,
    "createStartMenuShortcut": true,
    "shortcutName": "CML",
    "runAfterFinish": true,
    "deleteAppDataOnUninstall": false,
    "artifactName": "test-$desktopVersion-Setup.`${ext}"
  }
}
"@ | Set-Content -Path $builderConfigPath -Encoding ascii
Write-PackageDetail "Builder config: $builderConfigPath"
Push-Location $desktopDir
try {
  $builderArgs = @("--win", "--x64", "--config", $builderConfigPath)
  if ($PackagedOnly) {
    $builderArgs += "--dir"
  }
  npx electron-builder @builderArgs
} finally {
  Pop-Location
}
Complete-PackagePhase $outputDirPath

Start-PackagePhase "Verify package artifacts" "Checking expected unpacked executable and installer outputs."
$expectedUnpackedExe = Join-Path $outputDirPath "win-unpacked\CML.exe"
if (-not (Test-Path -LiteralPath $expectedUnpackedExe)) {
  throw "electron-builder completed but did not produce expected unpacked executable: $expectedUnpackedExe"
}
$expectedUnpackedExeItem = Get-Item -LiteralPath $expectedUnpackedExe
Write-PackageDetail "Unpacked executable: $expectedUnpackedExe ($(Format-FileSize $expectedUnpackedExeItem.Length))"

if (-not $PackagedOnly) {
  $expectedInstaller = Join-Path $outputDirPath "test-$desktopVersion-Setup.exe"
  if (-not (Test-Path -LiteralPath $expectedInstaller)) {
    throw "electron-builder completed but did not produce expected installer: $expectedInstaller"
  }
  $expectedInstallerItem = Get-Item -LiteralPath $expectedInstaller
  Write-PackageDetail "Installer: $expectedInstaller ($(Format-FileSize $expectedInstallerItem.Length))"
}
Complete-PackagePhase
Write-Progress -Activity "CML Windows package" -Completed
$totalDuration = Format-Duration ((Get-Date) - $script:PackageStartedAt)
Write-PackageLine "Package build finished in $totalDuration" "DONE"
Write-PackageLine "Output directory: $outputDirPath" "DONE"
