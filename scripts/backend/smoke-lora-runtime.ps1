param(
  [Parameter(Mandatory = $true)]
  [string]$AdapterPath,
  [string]$BaseModel = $env:CML_LLM_MODEL,
  [string]$RuntimeUrl = $env:CML_LLM_BASE_URL,
  [string]$ReportPath = ".tmp/lora-runtime-smoke-report.json"
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}
if (-not $BaseModel) {
  throw "Base model is required. Pass -BaseModel or set CML_LLM_MODEL."
}
if (-not $RuntimeUrl) {
  throw "Runtime URL is required. Pass -RuntimeUrl or set CML_LLM_BASE_URL."
}

$reportFullPath = Join-Path $repoRoot $ReportPath
$reportDir = Split-Path -Parent $reportFullPath
if ($reportDir) {
  New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
}

$env:CML_LLM_BASE_URL = $RuntimeUrl
$env:CML_LLM_MODEL = $BaseModel
$env:CML_LLM_PROVIDER = if ($env:CML_LLM_PROVIDER) { $env:CML_LLM_PROVIDER } else { "openai-compatible" }
$env:ADAPTER_PATH = $AdapterPath
$env:REPORT_PATH = $reportFullPath

$pythonScript = @'
import json
import os
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.core.llm_runtime import runtime_status
from backend.app.core.lora_training import runtime_adapter_load_plan

get_settings.cache_clear()
adapter_path = Path(os.environ["ADAPTER_PATH"])
report_path = Path(os.environ["REPORT_PATH"])
base_model = os.environ["CML_LLM_MODEL"]
plan = runtime_adapter_load_plan(adapter_path=adapter_path, base_model=base_model)
runtime = runtime_status()
report = {"runtime": runtime, "adapter_load_plan": plan}
report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
if not plan["available"]:
    raise SystemExit("Adapter artifact is not loadable by contract.")
if not runtime["available"]:
    raise SystemExit("Local inference runtime is not reachable.")
'@

$pythonScript | & $python -
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

Write-Host "LoRA runtime smoke report written to $reportFullPath"
