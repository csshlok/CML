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

if ($ReportPath) {
  $resolvedReportPath = [System.IO.Path]::GetFullPath($ReportPath)
  $extension = [System.IO.Path]::GetExtension($resolvedReportPath)
  if ($extension) {
    $reportDir = Split-Path -Parent $resolvedReportPath
    if ($reportDir) {
      New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
      $env:CML_DATA_DIR = $reportDir
    }
    $env:CML_RETRIEVAL_BENCHMARK_REPORT_PATH = $resolvedReportPath
  } else {
    New-Item -ItemType Directory -Force -Path $resolvedReportPath | Out-Null
    $env:CML_DATA_DIR = $resolvedReportPath
    $env:CML_RETRIEVAL_BENCHMARK_REPORT_PATH = Join-Path $resolvedReportPath "retrieval-benchmark-report.json"
  }
  if ($env:CML_DATA_DIR) {
    $env:CML_DATABASE_PATH = Join-Path $env:CML_DATA_DIR "retrieval-benchmark.sqlite3"
    if (Test-Path -LiteralPath $env:CML_DATABASE_PATH) {
      Remove-Item -Force -LiteralPath $env:CML_DATABASE_PATH
    }
  }
}

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
detailed_report = {}
json_path = Path(report.get("json_path") or "")
if json_path.exists():
    try:
        detailed_report = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        detailed_report = {}
fixture_count = int(detailed_report.get("fixture_count") or 0)
passing_fixture_count = sum(1 for row in detailed_report.get("rows", []) if row.get("passes_fixture"))
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
result = {
    **report,
    "fixture_count": fixture_count,
    "passing_fixture_count": passing_fixture_count,
    "detailed_report_path": str(json_path) if json_path.exists() else "",
    "targets": targets,
}
report_path = os.environ.get("CML_RETRIEVAL_BENCHMARK_REPORT_PATH", "").strip()
if report_path:
    report_file = Path(report_path)
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
    markdown_path = report_file.with_suffix(".md")
    markdown_path.write_text(
        "\n".join(
            [
                "# Retrieval Benchmark Report",
                "",
                f"- Sources: {targets['source_count']}",
                f"- Index seconds: {targets['index_seconds']}",
                f"- Query latency seconds: {targets['query_latency_seconds']}",
                f"- Max query latency seconds: {targets['max_query_latency_seconds']}",
                f"- Compact seconds: {targets['compact_seconds']}",
                f"- Database bytes: {targets['database_bytes']}",
                f"- Passes low-spec targets: {targets['passes_low_spec_targets']}",
                f"- Fixture count: {fixture_count}",
                f"- Passing fixture count: {passing_fixture_count}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    result["written_reports"] = {"json": str(report_file), "markdown": str(markdown_path)}
print(json.dumps(result, indent=2))
'@

$env:CML_RETRIEVAL_BENCHMARK_SOURCES = "$Sources"
$code | & $python -
