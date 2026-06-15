param(
  [Parameter(Mandatory = $true)][string]$VaultId,
  [string]$ClusterId = "",
  [string]$QueriesJson = "",
  [string]$ReportPath = "",
  [switch]$Strict
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  throw "Missing .venv python at $python"
}
$env:PYTHONPATH = $repoRoot

$tmpScript = Join-Path $repoRoot ".tmp\benchmark-context-strategies.py"
New-Item -ItemType Directory -Force -Path (Split-Path $tmpScript) | Out-Null
@'
import json
import shutil
from pathlib import Path

from backend.app.core.benchmark_matrix import export_context_strategy_report

queries_raw = r"""__QUERIES_JSON__""".strip()
queries = json.loads(queries_raw) if queries_raw else None
report = export_context_strategy_report(
    vault_id="__VAULT_ID__",
    cluster_id="__CLUSTER_ID__" or None,
    queries=queries,
    strict=__STRICT__,
)
report_path = r"__REPORT_PATH__".strip()
if report_path:
    target = Path(report_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(report["json_path"], target)
print(json.dumps({
    "report_id": report["report_id"],
    "query_count": report["query_count"],
    "json_path": report["json_path"],
    "markdown_path": report["markdown_path"],
    "operator_summary": report["operator_summary"],
    "product_summary": report["product_summary"],
}, indent=2))
'@.Replace("__VAULT_ID__", $VaultId).
    Replace("__CLUSTER_ID__", $ClusterId).
    Replace("__STRICT__", $(if ($Strict) { "True" } else { "False" })).
    Replace("__QUERIES_JSON__", $QueriesJson.Replace("\", "\\")).
    Replace("__REPORT_PATH__", $ReportPath.Replace("\", "\\")) | Set-Content -Encoding UTF8 $tmpScript

& $python $tmpScript
