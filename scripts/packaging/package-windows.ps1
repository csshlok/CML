param(
  [switch]$IncludeEmbeddingRuntime,
  [switch]$SkipOcrRuntimeDownload,
  [string]$TesseractExePath = "",
  [string]$GhostscriptExePath = "",
  [switch]$SkipGhostscriptInstaller,
  [switch]$AllowPartialOcrRuntime
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$desktopDir = Join-Path $repoRoot "apps\desktop"
$backendDir = Join-Path $repoRoot "backend"
$stagingDir = Join-Path $desktopDir "packaging\backend"
$runtimeDir = Join-Path $desktopDir "packaging\python-runtime"
$expertRuntimeDir = Join-Path $desktopDir "packaging\expert-python-runtime"
$playwrightBrowserDir = Join-Path $desktopDir "packaging\ms-playwright"
$packagingRoot = Join-Path $desktopDir "packaging"
$helperManifestScript = Join-Path $repoRoot "scripts\packaging\generate-helper-manifest.cjs"
$packageAuditScript = Join-Path $repoRoot "scripts\packaging\audit-package-layout.cjs"
$ocrStagingScript = Join-Path $repoRoot "scripts\packaging\stage-ocr-runtime.ps1"
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
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
}

Copy-Item -Recurse -Force (Join-Path $backendDir "app") (Join-Path $stagingDir "app")
if (Test-Path (Join-Path $backendDir "bin")) {
  Copy-Item -Recurse -Force (Join-Path $backendDir "bin") (Join-Path $stagingDir "bin")
}
Copy-Item -Force (Join-Path $backendDir "pyproject.toml") (Join-Path $stagingDir "pyproject.toml")

Write-Host "Building packaged backend Python runtime..."
if (Test-Path $runtimeDir) {
  Remove-Item -Recurse -Force $runtimeDir
}
& $python -m venv $runtimeDir
$runtimePython = Join-Path $runtimeDir "Scripts\python.exe"
& $runtimePython -m pip install --upgrade pip
& $runtimePython -m pip install `
  "fastapi>=0.115.0" `
  "uvicorn[standard]>=0.30.0" `
  "pydantic-settings>=2.6.0" `
  "pypdf>=5.0.0" `
  "python-docx>=1.1.2" `
  "PyMuPDF>=1.24.0" `
  "ocrmypdf>=16.0.0" `
  "playwright==1.60.0"

Write-Host "Staging Playwright Chromium runtime..."
New-Item -ItemType Directory -Force -Path $playwrightBrowserDir | Out-Null
$env:PLAYWRIGHT_BROWSERS_PATH = $playwrightBrowserDir
& $runtimePython -m playwright install chromium

if ($IncludeEmbeddingRuntime) {
  Write-Host "Installing optional embedding runtime dependencies..."
  & $runtimePython -m pip install "sentence-transformers>=3.0.0"
}

Write-Host "Building packaged expert Python runtime..."
if (Test-Path $expertRuntimeDir) {
  Remove-Item -Recurse -Force $expertRuntimeDir
}
& $python -m venv $expertRuntimeDir
$expertRuntimePython = Join-Path $expertRuntimeDir "Scripts\python.exe"
& $expertRuntimePython -m pip install --upgrade pip
& $expertRuntimePython -m pip install `
  "torch>=2.4.0" `
  "transformers>=4.55.0" `
  "peft>=0.17.0"

Write-Host "Generating helper integrity manifest..."
node $helperManifestScript

Write-Host "Auditing staged package layout..."
node $packageAuditScript $packagingRoot $packagingRoot

Write-Host "Packaging Windows app with electron-builder..."
$env:CSC_IDENTITY_AUTO_DISCOVERY = "false"
Push-Location $desktopDir
try {
  npm run package:win
} finally {
  Pop-Location
}
