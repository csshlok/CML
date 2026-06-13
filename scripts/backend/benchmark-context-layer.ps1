param(
  [int]$Sources = 24,
  [string]$ReportPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}

$env:CML_ALLOW_HASH_EMBEDDINGS = "1"
$env:CML_EMBEDDING_PROVIDER = "hash"

if ($ReportPath) {
  $resolvedReportPath = [System.IO.Path]::GetFullPath($ReportPath)
  $reportDir = Split-Path -Parent $resolvedReportPath
  if ($reportDir) {
    New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
    $env:CML_DATA_DIR = $reportDir
    $env:CML_DATABASE_PATH = Join-Path $reportDir "context-layer-benchmark.sqlite3"
    if (Test-Path -LiteralPath $env:CML_DATABASE_PATH) {
      Remove-Item -Force -LiteralPath $env:CML_DATABASE_PATH
    }
  }
  $env:CML_CONTEXT_LAYER_REPORT_PATH = $resolvedReportPath
}

$code = @'
import json
import os
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.core.context_layer_eval import export_context_layer_report
from backend.app.core.database import connect, dict_from_row, init_db, utc_now
from backend.app.core.embeddings import reindex_source_chunks

sources = int(os.environ.get("CML_CONTEXT_LAYER_BENCHMARK_SOURCES", "24"))
settings = get_settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
init_db()
now = utc_now()

with connect() as conn:
    conn.execute(
        "INSERT OR IGNORE INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("vault-context", "Context Layer Benchmark", str(settings.data_dir), now, now),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO clusters (
            id, vault_id, name, description, color, expert_status, created_at, updated_at
        )
        VALUES ('cluster-context', 'vault-context', 'Context Layer', '', 'sage', 'retrieval_ready', ?, ?)
        """,
        (now, now),
    )
    for index in range(sources):
        source_id = f"context-source-{index:03d}"
        title = f"Context source {index}"
        text = (
            "We decided to use retrieval first and compact packets. "
            "The system must preserve memory items and working memory. "
            f"Source marker {index}. "
        ) * 18
        conn.execute(
            """
            INSERT OR REPLACE INTO sources (
                id, vault_id, cluster_id, title, source_type, state, raw_text, extracted_text, summary, tags, created_at, updated_at
            )
            VALUES (?, 'vault-context', 'cluster-context', ?, 'note', 'indexed', ?, ?, ?, '[]', ?, ?)
            """,
            (source_id, title, text, text, f"{title} summary", now, now),
        )
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        reindex_source_chunks(conn, dict_from_row(row))

report = export_context_layer_report("vault-context", cluster_id="cluster-context", limit=6)
report_path = os.environ.get("CML_CONTEXT_LAYER_REPORT_PATH", "").strip()
if report_path:
    target = Path(report_path)
    payload = json.loads(Path(report["json_path"]).read_text(encoding="utf-8"))
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    target.with_suffix(".md").write_text(Path(report["markdown_path"]).read_text(encoding="utf-8"), encoding="utf-8")
    report["written_reports"] = {"json": str(target), "markdown": str(target.with_suffix(".md"))}
print(json.dumps(report, indent=2))
'@

$env:CML_CONTEXT_LAYER_BENCHMARK_SOURCES = "$Sources"
$code | & $python -
