param(
  [int]$RecommendedFreeSpaceGB = 12
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$requiredPaths = @(
  (Join-Path $repoRoot "package-logo.png"),
  (Join-Path $repoRoot "docs\model-integrity-manifest.json"),
  (Join-Path $repoRoot "apps\desktop\package.json"),
  (Join-Path $repoRoot "node_modules\electron"),
  $python
)

if (-not $IsWindows -and $env:OS -ne "Windows_NT") {
  throw "Windows development packages must be built on 64-bit Windows."
}
if (-not [Environment]::Is64BitOperatingSystem) {
  throw "The Windows development package requires a 64-bit operating system."
}

$missing = @($requiredPaths | Where-Object { -not (Test-Path -LiteralPath $_) })
if ($missing.Count -gt 0) {
  $relativeMissing = $missing | ForEach-Object {
    if ($_.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
      $_.Substring($repoRoot.Length).TrimStart("\")
    } else {
      $_
    }
  }
  throw @"
Development packaging prerequisites are missing:
$($relativeMissing -join "`n")

From the repository root run:
  npm ci
  py -3.12 -m venv .venv
  .\.venv\Scripts\python.exe -m pip install --upgrade pip
  .\.venv\Scripts\python.exe -m pip install -r requirements\contributors-backend.txt
"@
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
  throw "Node.js was not found. Install 64-bit Node.js 22 LTS and run npm ci."
}
$nodeVersionText = (& node --version 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $nodeVersionText) {
  throw "Node.js was not found. Install 64-bit Node.js 22 LTS and run npm ci."
}
$nodeMajor = [int]($nodeVersionText.TrimStart("v").Split(".")[0])
if ($nodeMajor -lt 22) {
  throw "Node.js 22 or newer is required; found $nodeVersionText."
}

$pythonInfo = & $python -c "import json, platform, struct, sys; print(json.dumps({'version': list(sys.version_info[:3]), 'bits': struct.calcsize('P') * 8, 'implementation': platform.python_implementation()}))"
if ($LASTEXITCODE -ne 0 -or -not $pythonInfo) {
  throw "Could not inspect the repository Python environment at $python."
}
$pythonState = $pythonInfo | ConvertFrom-Json
$pythonMajor = [int]$pythonState.version[0]
$pythonMinor = [int]$pythonState.version[1]
if ($pythonMajor -ne 3 -or $pythonMinor -lt 11 -or $pythonMinor -ge 15) {
  throw "Python 3.11 through 3.14 is required; found $($pythonState.version -join '.'). Python 3.12 x64 is recommended."
}
if ([int]$pythonState.bits -ne 64) {
  throw "The repository virtual environment must use 64-bit Python."
}

& $python -c "import importlib.util as u, sys; names=('PIL','playwright','sentence_transformers'); missing=[name for name in names if u.find_spec(name) is None]; print('Missing Python modules: ' + ', '.join(missing) if missing else 'Python packaging modules found.'); sys.exit(1 if missing else 0)"
if ($LASTEXITCODE -ne 0) {
  throw "The virtual environment is incomplete. Install requirements\contributors-backend.txt before packaging."
}

$repoDriveRoot = [System.IO.Path]::GetPathRoot($repoRoot)
$repoDrive = Get-PSDrive -Name $repoDriveRoot.Substring(0, 1) -ErrorAction Stop
$freeGB = [math]::Round($repoDrive.Free / 1GB, 1)
if ($freeGB -lt 6) {
  throw "The repository drive has only $freeGB GB free. Development packaging requires at least 6 GB and 12 GB is recommended."
}
if ($freeGB -lt $RecommendedFreeSpaceGB) {
  Write-Warning "The repository drive has $freeGB GB free; $RecommendedFreeSpaceGB GB is recommended for a first package build."
}

Write-Host "Windows development package prerequisites passed."
Write-Host "  Repository: $repoRoot"
Write-Host "  Node.js: $nodeVersionText"
Write-Host "  Python: $($pythonState.version -join '.') $($pythonState.bits)-bit"
Write-Host "  Repository drive free: $freeGB GB"
