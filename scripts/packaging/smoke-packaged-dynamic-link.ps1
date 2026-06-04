param(
  [string]$PackageRoot = "",
  [string]$Url = "https://example.com/"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
if (-not $PackageRoot) {
  $PackageRoot = Join-Path $repoRoot "apps\desktop\release\win-unpacked"
}

$packagePath = [System.IO.Path]::GetFullPath($PackageRoot)
$resourcesPath = Join-Path $packagePath "resources"
$python = Join-Path $resourcesPath "python-runtime\Scripts\python.exe"
$backendRoot = Join-Path $resourcesPath "backend"

if (-not (Test-Path -LiteralPath $python)) {
  throw "Packaged Python runtime not found: $python"
}
if (-not (Test-Path -LiteralPath (Join-Path $backendRoot "app\main.py"))) {
  throw "Packaged backend source not found under $backendRoot"
}

$env:PYTHONPATH = $resourcesPath
$env:CML_DYNAMIC_LINK_SMOKE_URL = $Url
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $resourcesPath "ms-playwright"

$code = @'
import importlib.util
import json
import os
from backend.app.core.extraction import extract_text_from_url, link_extraction_diagnostics

url = os.environ["CML_DYNAMIC_LINK_SMOKE_URL"]
diagnostics = link_extraction_diagnostics(url)
title, text, cover = extract_text_from_url(url)
result = {
    "url": url,
    "title": title,
    "text_length": len(text),
    "cover_image_url": cover,
    "browser_runtime_available": importlib.util.find_spec("playwright") is not None,
    "diagnostics": diagnostics,
    "dynamic_render_smoke_completed": diagnostics.get("dynamic_fallback_available") is True,
}
if not result["browser_runtime_available"]:
    raise SystemExit("Packaged Playwright browser runtime is not importable.")
if not diagnostics.get("allowed"):
    raise SystemExit("Dynamic-link diagnostics rejected the public smoke URL.")
if len(text.strip()) < 50:
    raise SystemExit("Packaged link extraction returned too little readable text.")
print(json.dumps(result, indent=2))
'@

$code | & $python -
if ($LASTEXITCODE -ne 0) {
  throw "Packaged dynamic-link smoke failed."
}
