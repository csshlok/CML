param(
  [string[]]$SearchRoots = @("data\benchmark-reports", ".tmp"),
  [string[]]$ReportPaths = @(),
  [string]$OutputDir = "data\benchmark-reports\graphs"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  throw "Missing .venv python at $python"
}
$env:PYTHONPATH = $repoRoot

$jsonReportPaths = $ReportPaths | ConvertTo-Json -Compress
$jsonSearchRoots = $SearchRoots | ConvertTo-Json -Compress

$tmpScript = Join-Path $repoRoot ".tmp\render-benchmark-graphs.py"
New-Item -ItemType Directory -Force -Path (Split-Path $tmpScript) | Out-Null
@'
import json
import os
from pathlib import Path

from backend.app.core.benchmark_graphs import discover_benchmark_reports, render_graphical_reports

report_paths = json.loads(os.environ.get("CML_BENCHMARK_GRAPH_REPORT_PATHS", "[]"))
search_roots = json.loads(os.environ.get("CML_BENCHMARK_GRAPH_SEARCH_ROOTS", "[]"))
output_dir = Path(os.environ["CML_BENCHMARK_GRAPH_OUTPUT_DIR"]).resolve()

if isinstance(report_paths, str):
    report_paths = [report_paths]
if isinstance(search_roots, str):
    search_roots = [search_roots]

selected_paths = [path for path in report_paths if str(path).strip()]
if not selected_paths:
    selected_paths = discover_benchmark_reports(search_roots)

result = render_graphical_reports(selected_paths, output_dir=output_dir)
print(json.dumps(result, indent=2))
'@ | Set-Content -Encoding UTF8 $tmpScript

$env:CML_BENCHMARK_GRAPH_REPORT_PATHS = $jsonReportPaths
$env:CML_BENCHMARK_GRAPH_SEARCH_ROOTS = $jsonSearchRoots
$env:CML_BENCHMARK_GRAPH_OUTPUT_DIR = $OutputDir

& $python $tmpScript
