param(
  [string]$SourceRoot = ".",
  [string]$ReportPath = "",
  [int]$MaxFiles = 25
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  throw "Missing .venv python at $python"
}
$env:PYTHONPATH = $repoRoot

$tmpScript = Join-Path $repoRoot ".tmp\benchmark-pdf-parsers.py"
New-Item -ItemType Directory -Force -Path (Split-Path $tmpScript) | Out-Null
@'
import json
import shutil
from pathlib import Path

from backend.app.core.benchmark_matrix import benchmark_pdf_parser_corpus

source_root = Path(r"__SOURCE_ROOT__").resolve()
report_path = r"__REPORT_PATH__".strip()
max_files = int("__MAX_FILES__")
pdfs = [str(path) for path in source_root.rglob("*.pdf") if path.is_file()][:max_files]
report = benchmark_pdf_parser_corpus(pdfs)
if report_path:
    target = Path(report_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(report["json_path"], target)
print(json.dumps({
    "report_id": report["report_id"],
    "document_count": len(pdfs),
    "json_path": report["json_path"],
    "markdown_path": report["markdown_path"],
    "parser_summaries": report["parser_summaries"],
}, indent=2))
'@.Replace("__SOURCE_ROOT__", $SourceRoot.Replace("\", "\\")).
    Replace("__REPORT_PATH__", $ReportPath.Replace("\", "\\")).
    Replace("__MAX_FILES__", "$MaxFiles") | Set-Content -Encoding UTF8 $tmpScript

& $python $tmpScript
