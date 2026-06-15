param(
  [Parameter(Mandatory = $true)]
  [string]$AdapterPath,
  [string]$BaseModel = $env:CML_LLM_MODEL,
  [string]$Prompt = "Reply with the single word CML.",
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

$reportFullPath = Join-Path $repoRoot $ReportPath
$reportDir = Split-Path -Parent $reportFullPath
if ($reportDir) {
  New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
}

$env:CML_LLM_MODEL = $BaseModel
$env:ADAPTER_PATH = $AdapterPath
$env:SMOKE_PROMPT = $Prompt
$env:REPORT_PATH = $reportFullPath

$pythonScript = @'
import json
import os
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.core.expert_runtime import run_adapter_runtime_smoke, runtime_adapter_load_plan

get_settings.cache_clear()
adapter_path = Path(os.environ["ADAPTER_PATH"])
report_path = Path(os.environ["REPORT_PATH"])
base_model = os.environ["CML_LLM_MODEL"]
prompt = os.environ["SMOKE_PROMPT"]
plan = runtime_adapter_load_plan(adapter_path=adapter_path, base_model=base_model)
runtime = run_adapter_runtime_smoke(adapter_path=adapter_path, base_model=base_model, prompt=prompt)
report = {"runtime": runtime, "adapter_load_plan": plan}
report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
if not plan["available"]:
    raise SystemExit("Adapter artifact is not ready for local runtime smoke.")
if not runtime["ok"]:
    raise SystemExit(runtime.get("error") or "Local adapter runtime smoke failed.")
'@

$pythonScript | & $python -
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

Write-Host "LoRA runtime smoke report written to $reportFullPath"
