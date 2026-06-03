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
import time
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.core.database import init_db, connect, dict_from_row, utc_now
from backend.app.core.embeddings import reindex_source_chunks
from backend.app.core.vector_maintenance import compact_vectors
from backend.app.core.retrieval_scoring import export_benchmark_report

sources = int(os.environ.get("CML_RETRIEVAL_BENCHMARK_SOURCES", "100"))
settings = get_settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
init_db()
now = utc_now()
started = time.perf_counter()
index_started = time.perf_counter()

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
index_seconds = round(time.perf_counter() - index_started, 4)

query_latencies = []
from backend.app.core.retrieval_scoring import scoring_ledger
for query in [
    "ocr packaging ghostscript",
    "bridge permissions external transcript",
    "chat transcript source weighting",
]:
    query_started = time.perf_counter()
    scoring_ledger("vault-benchmark", query, limit=20)
    query_latencies.append(round(time.perf_counter() - query_started, 4))

compact_started = time.perf_counter()
compact_result = compact_vectors("vault-benchmark")
compact_seconds = round(time.perf_counter() - compact_started, 4)

report = export_benchmark_report(
    "vault-benchmark",
    fixtures=[
        {"query": "ocr packaging ghostscript", "must_include_source_ids": ["benchmark-source-0000"]},
        {"query": "bridge permissions external transcript", "must_include_source_ids": ["benchmark-source-0001"]},
        {"query": "chat transcript source weighting", "must_include_source_ids": ["benchmark-source-0002"]},
    ],
)
db_size = Path(settings.database_path).stat().st_size if Path(settings.database_path).exists() else 0
targets = {
    "source_count": sources,
    "index_seconds": index_seconds,
    "query_latency_seconds": query_latencies,
    "max_query_latency_seconds": max(query_latencies) if query_latencies else 0,
    "compact_seconds": compact_seconds,
    "database_bytes": db_size,
    "low_spec_targets": {
        "source_count": 1000,
        "max_index_seconds": 900,
        "max_query_latency_seconds": 5,
        "max_compact_seconds": 60,
        "max_database_bytes": 1073741824,
    },
    "passes_low_spec_targets": (
        sources < 1000 or (
            index_seconds <= 900
            and (max(query_latencies) if query_latencies else 0) <= 5
            and compact_seconds <= 60
            and db_size <= 1073741824
        )
    ),
    "compact_result": compact_result,
    "total_seconds": round(time.perf_counter() - started, 4),
}
print(json.dumps({**report, "targets": targets}, indent=2))
'@

$env:CML_RETRIEVAL_BENCHMARK_SOURCES = "$Sources"
if ($ReportPath) {
  $env:CML_DATA_DIR = $ReportPath
}
$code | & $python -
