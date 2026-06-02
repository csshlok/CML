param(
  [int]$Sources = 100,
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

$code = @'
import json
import os
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.core.database import init_db, connect, dict_from_row, utc_now
from backend.app.core.embeddings import reindex_source_chunks
from backend.app.core.retrieval_scoring import export_benchmark_report

sources = int(os.environ.get("CML_RETRIEVAL_BENCHMARK_SOURCES", "100"))
settings = get_settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
init_db()
now = utc_now()

with connect() as conn:
    conn.execute(
        "INSERT OR IGNORE INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("vault-benchmark", "Retrieval Benchmark", str(settings.data_dir), now, now),
    )
    for index in range(sources):
        source_id = f"benchmark-source-{index:04d}"
        topic = "ocr packaging ghostscript" if index % 3 == 0 else "bridge permissions external transcript" if index % 3 == 1 else "chat transcript source weighting"
        text = (f"{topic} benchmark source {index} local memory retrieval threshold " * 35).strip()
        conn.execute(
            """
            INSERT OR REPLACE INTO sources (
                id, vault_id, title, source_type, state, raw_text, extracted_text, summary, tags, created_at, updated_at
            )
            VALUES (?, 'vault-benchmark', ?, 'note', 'indexed', ?, ?, '', '[]', ?, ?)
            """,
            (source_id, f"Benchmark Source {index}", text, text, now, now),
        )
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        reindex_source_chunks(conn, dict_from_row(row))

report = export_benchmark_report(
    "vault-benchmark",
    fixtures=[
        {"query": "ocr packaging ghostscript", "must_include_source_ids": ["benchmark-source-0000"]},
        {"query": "bridge permissions external transcript", "must_include_source_ids": ["benchmark-source-0001"]},
        {"query": "chat transcript source weighting", "must_include_source_ids": ["benchmark-source-0002"]},
    ],
)
print(json.dumps(report, indent=2))
'@

$env:CML_RETRIEVAL_BENCHMARK_SOURCES = "$Sources"
if ($ReportPath) {
  $env:CML_DATA_DIR = $ReportPath
}
$code | & $python -
