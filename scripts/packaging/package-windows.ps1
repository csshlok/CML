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

function Optimize-PortablePythonRuntime([string]$RuntimeRoot) {
  if (-not (Test-Path -LiteralPath $RuntimeRoot)) {
    throw "Cannot optimize missing runtime root: $RuntimeRoot"
  }

  Write-Host "Removing non-runtime payload from $RuntimeRoot..."

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

Write-Host "Clearing previous package output..."
if (Test-Path $outputDirPath) {
  Remove-Item -Recurse -Force $outputDirPath
}
New-Item -ItemType Directory -Force -Path $outputDirPath | Out-Null

if ($Release) {
  Write-Host "Release mode: clearing cached staged runtimes..."
  Reset-StagedPath $runtimeDir
  Reset-StagedPath $expertRuntimeDir
  Reset-StagedPath $playwrightBrowserDir
  if (-not $SkipOcrRuntimeDownload) {
    Reset-StagedPath (Join-Path $backendDir "bin\ocr")
  }
}

Write-Host "Building desktop app..."
Push-Location $desktopDir
try {
  npm run build
} finally {
  Pop-Location
}

Write-Host "Staging backend source..."
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
    Write-Host "Reusing staged OCR runtime..."
  } else {
    Write-Host "Staging OCR runtime..."
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
}

Copy-Item -Recurse -Force (Join-Path $backendDir "app") (Join-Path $stagingDir "app")
if (Test-Path (Join-Path $backendDir "bin")) {
  Copy-Item -Recurse -Force (Join-Path $backendDir "bin") (Join-Path $stagingDir "bin")
}
Copy-Item -Force (Join-Path $backendDir "pyproject.toml") (Join-Path $stagingDir "pyproject.toml")

$runtimePython = Join-Path $runtimeDir "python.exe"
$backendRuntimeStampPath = Join-Path $runtimeDir ".cml-runtime-stamp"
$backendRuntimeFingerprint = Get-StringFingerprint @(
  "python-runtime-v5",
  "base_python_root=$basePythonRoot",
  "prune=docs-tests-pip",
  "dependency_policy=pinned",
  ($backendRuntimePackages -join "`n")
)
$backendRuntimeReady = $false
if (-not $Release) {
  $backendRuntimeReady = Test-StagedRuntime `
    -RuntimeDir $runtimeDir `
    -StampPath $backendRuntimeStampPath `
    -ExpectedFingerprint $backendRuntimeFingerprint `
    -RequiredPaths @($runtimePython)
}

if ($backendRuntimeReady) {
  Write-Host "Reusing packaged backend Python runtime..."
} else {
  Write-Host "Building packaged backend Python runtime..."
  Copy-PortablePythonRuntime $basePythonRoot $runtimeDir
  & $runtimePython -I -m pip install --upgrade pip
  & $runtimePython -I -m pip install --upgrade @backendRuntimePackages
  Optimize-PortablePythonRuntime $runtimeDir
  Write-StagedRuntimeStamp $backendRuntimeStampPath $backendRuntimeFingerprint
}

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
if ($playwrightReady) {
  Write-Host "Reusing staged Playwright Chromium runtime..."
} else {
  Write-Host "Staging Playwright Chromium runtime..."
  if (Test-Path $playwrightBrowserDir) {
    Remove-Item -Recurse -Force $playwrightBrowserDir
  }
  New-Item -ItemType Directory -Force -Path $playwrightBrowserDir | Out-Null
  & $runtimePython -m playwright install chromium
  Write-StagedRuntimeStamp $playwrightStampPath $playwrightFingerprint
}

if ($IncludeEmbeddingRuntime) {
  Write-Host "Installing optional embedding runtime dependencies..."
  & $runtimePython -m pip install "sentence-transformers==5.5.1"
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

if ($expertRuntimeReady) {
  Write-Host "Reusing packaged expert Python runtime..."
} else {
  Write-Host "Building packaged expert Python runtime..."
  Copy-PortablePythonRuntime $basePythonRoot $expertRuntimeDir
  & $expertRuntimePython -I -m pip install --upgrade pip
  & $expertRuntimePython -I -m pip install --upgrade @expertRuntimePackages
  Optimize-PortablePythonRuntime $expertRuntimeDir
  Write-StagedRuntimeStamp $expertRuntimeStampPath $expertRuntimeFingerprint
}

Write-Host "Generating helper integrity manifest..."
node $helperManifestScript

Write-Host "Auditing staged package layout..."
node $packageAuditScript $packagingRoot $packagingRoot

Write-Host "Packaging Windows app with electron-builder..."
$env:CSC_IDENTITY_AUTO_DISCOVERY = "false"
$builderCompression = if ($Release) { "maximum" } else { "store" }
$builderTarget = if ($PackagedOnly) { "dir" } else { "nsis" }
$builderConfigPath = Join-Path $tmpDir "electron-builder.generated.json"
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
