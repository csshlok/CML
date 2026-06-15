param(
  [string]$SourceRoot = ".",
  [string]$ReportPath = "",
  [int]$MaxFiles = 100
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  throw "Missing .venv python at $python"
}
$env:PYTHONPATH = $repoRoot

$tmpScript = Join-Path $repoRoot ".tmp\benchmark-ingestion-matrix.py"
New-Item -ItemType Directory -Force -Path (Split-Path $tmpScript) | Out-Null
@'
import json
import shutil
from pathlib import Path

from backend.app.core.benchmark_matrix import benchmark_ingestion_corpus

source_root = Path(r"__SOURCE_ROOT__").resolve()
max_files = int("__MAX_FILES__")
allowed = []
for path in source_root.rglob("*"):
    if not path.is_file():
        continue
    allowed.append(str(path))
    if len(allowed) >= max_files:
        break
report = benchmark_ingestion_corpus(allowed)
report_path = r"__REPORT_PATH__".strip()
if report_path:
    target = Path(report_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(report["json_path"], target)
print(json.dumps({
    "report_id": report["report_id"],
    "document_count": len(allowed),
    "json_path": report["json_path"],
    "markdown_path": report["markdown_path"],
    "operator_summary": report["operator_summary"],
    "product_summary": report["product_summary"],
}, indent=2))
'@.Replace("__SOURCE_ROOT__", $SourceRoot.Replace("\", "\\")).
    Replace("__MAX_FILES__", "$MaxFiles").
    Replace("__REPORT_PATH__", $ReportPath.Replace("\", "\\")) | Set-Content -Encoding UTF8 $tmpScript

& $python $tmpScript
