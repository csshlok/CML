param(
  [string]$Url = "https://example.com/"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}

$code = @'
import importlib.util
import json
import os
from backend.app.core.extraction import link_extraction_diagnostics

url = os.environ["CML_DYNAMIC_LINK_SMOKE_URL"]
result = link_extraction_diagnostics(url)
print(json.dumps({
    "url": url,
    "browser_runtime_available": importlib.util.find_spec("playwright") is not None,
    "diagnostics": result,
    "dynamic_render_smoke_completed": result.get("dynamic_fallback_available") is True,
}, indent=2))
'@

$env:CML_DYNAMIC_LINK_SMOKE_URL = $Url
$code | & $python -
