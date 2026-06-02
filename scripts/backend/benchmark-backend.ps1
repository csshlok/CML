param(
  [int]$Sources = 250,
  [int]$WordsPerSource = 240,
  [string]$ReportPath = ".tmp\backend-benchmark-report.md"
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}

$env:CML_EMBEDDING_PROVIDER = "hash"
$env:CML_ALLOW_HASH_EMBEDDINGS = "1"
$env:CML_BACKEND_BENCH_REPORT = $ReportPath

@"
import os
import tempfile
import time
from pathlib import Path

from backend.app.core.config import get_settings

root = Path(tempfile.mkdtemp(prefix="cml-backend-benchmark-"))
os.environ["CML_DATA_DIR"] = str(root / "data")
os.environ["CML_DATABASE_PATH"] = str(root / "data" / "benchmark.sqlite3")
os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"
get_settings.cache_clear()

from backend.app.core.database import connect, init_db, utc_now
from backend.app.core.embeddings import reindex_source_chunks
from backend.app.core.vector_maintenance import compact_vectors, repair_vectors, vector_repair_plan
from backend.app.api.routes.search import semantic_search
from backend.app.schemas import SemanticSearchRequest

sources = int("$Sources")
words_per_source = int("$WordsPerSource")
init_db()
now = utc_now()

start = time.perf_counter()
with connect() as conn:
    conn.execute(
        "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("vault-bench", "Benchmark vault", str(root), now, now),
    )
    for index in range(sources):
        text = ("benchmark source %d local memory vector repair semantic search " % index) * max(1, words_per_source // 8)
        conn.execute(
            """
            INSERT INTO sources (id, vault_id, title, source_type, state, raw_text, extracted_text, created_at, updated_at)
            VALUES (?, 'vault-bench', ?, 'note', 'indexed', ?, ?, ?, ?)
            """,
            (f"source-{index}", f"Source {index}", text, text, now, now),
        )
insert_seconds = time.perf_counter() - start

start = time.perf_counter()
with connect() as conn:
    rows = conn.execute("SELECT * FROM sources WHERE vault_id = 'vault-bench'").fetchall()
    chunks = sum(reindex_source_chunks(conn, dict(row)) for row in rows)
index_seconds = time.perf_counter() - start

start = time.perf_counter()
result = semantic_search(SemanticSearchRequest(vault_id="vault-bench", query="vector repair semantic memory", limit=10))
search_seconds = time.perf_counter() - start

start = time.perf_counter()
plan = vector_repair_plan("vault-bench")
repair = repair_vectors("vault-bench", limit=50)
compact = compact_vectors("vault-bench")
repair_seconds = time.perf_counter() - start

report = f"""# Backend Benchmark Report

- Sources: {sources}
- Words per source: {words_per_source}
- Chunks indexed: {chunks}
- Insert seconds: {insert_seconds:.4f}
- Index seconds: {index_seconds:.4f}
- Search seconds: {search_seconds:.4f}
- Search results: {len(result["results"])}
- Repair plan source count: {plan["repair_source_count"]}
- Repair sources processed: {repair["sources_repaired"]}
- Orphan chunks removed: {compact["orphan_chunks_removed"]}
- Repair/compact seconds: {repair_seconds:.4f}
"""
report_path = Path(os.environ["CML_BACKEND_BENCH_REPORT"])
report_path.parent.mkdir(parents=True, exist_ok=True)
report_path.write_text(report, encoding="utf-8")
print(report)
"@ | & $python -
