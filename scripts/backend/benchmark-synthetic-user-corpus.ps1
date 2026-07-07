param(
  [string]$ReportRoot = ".tmp\\synthetic-user-benchmark",
  [string]$VaultId = "vault-synthetic-user",
  [int]$TargetFileCount = 15,
  [switch]$KeepCorpus
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  throw "Missing .venv python at $python"
}

$env:PYTHONPATH = $repoRoot
$resolvedReportRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $ReportRoot))
New-Item -ItemType Directory -Force -Path $resolvedReportRoot | Out-Null
$env:CML_DATA_DIR = (Join-Path $resolvedReportRoot "data")
$env:CML_DATABASE_PATH = (Join-Path $resolvedReportRoot "data\\synthetic-user.sqlite3")
if (Test-Path -LiteralPath $env:CML_DATABASE_PATH) {
  Remove-Item -Force -LiteralPath $env:CML_DATABASE_PATH
}
$env:CML_ALLOW_HASH_EMBEDDINGS = "1"
$env:CML_EMBEDDING_PROVIDER = "hash"

$tmpScript = Join-Path $repoRoot ".tmp\benchmark-synthetic-user-corpus.py"
New-Item -ItemType Directory -Force -Path (Split-Path $tmpScript) | Out-Null
@'
import json
import shutil
import tempfile
import time
from pathlib import Path

from backend.app.api.routes.sources import _create_source_record
from backend.app.core.benchmark_corpus import THEMES, create_synthetic_user_corpus
from backend.app.core.benchmark_matrix import (
    benchmark_ingestion_corpus,
    benchmark_pdf_parser_corpus,
    export_context_strategy_report,
    validate_context_benchmark_inputs,
)
from backend.app.core.config import get_settings
from backend.app.core.database import connect, dict_from_row, init_db, utc_now
from backend.app.core.embeddings import reindex_source_chunks
from backend.app.core.source_records import source_type_for_suffix
from backend.app.schemas import SourceCreate

report_root = Path(r"__REPORT_ROOT__")
vault_id = "__VAULT_ID__"
target_file_count = int("__TARGET_FILE_COUNT__")
keep_corpus = "__KEEP_CORPUS__" == "1"
settings = get_settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
init_db()
now = utc_now()

corpus_dir = Path(tempfile.mkdtemp(prefix="cml-synthetic-corpus-"))
report_root.mkdir(parents=True, exist_ok=True)
summary = {}
started = time.perf_counter()
try:
    phase_started = time.perf_counter()
    corpus = create_synthetic_user_corpus(corpus_dir, target_file_count=target_file_count)
    corpus_generation_seconds = round(time.perf_counter() - phase_started, 4)
    all_paths = [Path(path) for path in corpus["all_paths"]]
    pdf_paths = [Path(path) for path in corpus["pdf_paths"]]
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (vault_id, "Synthetic User Benchmark", str(report_root), now, now),
        )
        for cluster_index, theme in enumerate(THEMES):
            conn.execute(
                """
                INSERT OR IGNORE INTO clusters (
                    id, vault_id, name, description, color, index_status, profile_status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'sage', 'ready', 'ready', ?, ?)
                """,
                (
                    f"cluster-synthetic-{cluster_index:02d}",
                    vault_id,
                    theme.title(),
                    f"Synthetic benchmark cluster for {theme}",
                    now,
                    now,
                ),
            )
    phase_started = time.perf_counter()
    ingestion = benchmark_ingestion_corpus(all_paths, capture_payloads=True)
    ingestion_benchmark_seconds = round(time.perf_counter() - phase_started, 4)
    phase_started = time.perf_counter()
    pdf_report = benchmark_pdf_parser_corpus(pdf_paths, parsers=["builtin", "opendataloader_pdf"])
    pdf_benchmark_seconds = round(time.perf_counter() - phase_started, 4)

    phase_started = time.perf_counter()
    captures = ingestion.get("_captures") or []
    for capture_index, capture in enumerate(captures):
        suffix = str(capture["suffix"])
        source_type = source_type_for_suffix(suffix)
        cluster_id = f"cluster-synthetic-{capture_index % len(THEMES):02d}"
        _create_source_record(
            SourceCreate(
                vault_id=vault_id,
                cluster_id=cluster_id,
                title=str(capture["title"]),
                source_type=source_type,
                original_path=str(capture["path"]),
                raw_text=str(capture["text"]),
            ),
            page_texts=[str(page) for page in capture["pages"]],
        )
    vault_ingest_seconds = round(time.perf_counter() - phase_started, 4)

    phase_started = time.perf_counter()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM sources WHERE vault_id = ? AND deleted_at IS NULL ORDER BY created_at ASC",
            (vault_id,),
        ).fetchall()
        chunk_count = 0
        for row in rows:
            chunk_count += reindex_source_chunks(conn, dict_from_row(row))
        source_count = len(rows)
    reindex_seconds = round(time.perf_counter() - phase_started, 4)

    validate_context_benchmark_inputs(vault_id, query_specs=[{"prompt": query} for query in corpus["queries"]])
    phase_started = time.perf_counter()
    context = export_context_strategy_report(vault_id, queries=corpus["queries"], strict=True)
    context_benchmark_seconds = round(time.perf_counter() - phase_started, 4)
    context_json = json.loads(Path(context["json_path"]).read_text(encoding="utf-8"))

    suffixes_seen = sorted({Path(item["path"]).suffix.lower() for item in ingestion["rows"]})
    missing_suffixes = sorted(set(corpus["expected_suffixes"]) - set(suffixes_seen))
    if missing_suffixes:
        raise RuntimeError(f"Ingestion benchmark missed expected file types: {missing_suffixes}")

    if int(context_json["query_count"]) <= 0:
        raise RuntimeError("Context benchmark produced no query rows.")
    if sum(int(row.get("result_count") or 0) for row in context_json.get("rows") or []) <= 0:
        raise RuntimeError("Context benchmark produced zero retrieval hits.")

    summary = {
        "corpus_file_count": len(all_paths),
        "corpus_pdf_count": len(pdf_paths),
        "corpus_suffixes": corpus["expected_suffixes"],
        "corpus_counts": corpus["counts"],
        "source_count": source_count,
        "chunk_count": chunk_count,
        "timings": {
            "corpus_generation_seconds": corpus_generation_seconds,
            "ingestion_benchmark_seconds": ingestion_benchmark_seconds,
            "pdf_benchmark_seconds": pdf_benchmark_seconds,
            "vault_ingest_seconds": vault_ingest_seconds,
            "reindex_seconds": reindex_seconds,
            "context_benchmark_seconds": context_benchmark_seconds,
            "total_seconds": round(time.perf_counter() - started, 4),
        },
        "ingestion_report": {
            "report_id": ingestion["report_id"],
            "json_path": ingestion["json_path"],
            "markdown_path": ingestion["markdown_path"],
            "document_count": ingestion["operator_summary"]["document_count"],
            "type_breakdown": ingestion["operator_summary"]["type_breakdown"],
        },
        "pdf_report": {
            "report_id": pdf_report["report_id"],
            "json_path": pdf_report["json_path"],
            "markdown_path": pdf_report["markdown_path"],
            "parser_summaries": pdf_report["parser_summaries"],
        },
        "context_report": {
            "report_id": context["report_id"],
            "json_path": context["json_path"],
            "markdown_path": context["markdown_path"],
            "query_count": context["query_count"],
            "operator_summary": context["operator_summary"],
            "product_summary": context["product_summary"],
            "total_retrieval_hits": sum(int(row.get("result_count") or 0) for row in context_json.get("rows") or []),
        },
        "cleanup": {
            "corpus_deleted": not keep_corpus,
            "corpus_path": str(corpus_dir),
        },
    }
    summary_path = report_root / "synthetic-user-benchmark-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({**summary, "summary_path": str(summary_path)}, indent=2))
finally:
    if not keep_corpus:
        shutil.rmtree(corpus_dir, ignore_errors=True)
'@.Replace("__REPORT_ROOT__", $resolvedReportRoot.Replace("\", "\\")).
    Replace("__VAULT_ID__", $VaultId).
    Replace("__TARGET_FILE_COUNT__", "$TargetFileCount").
    Replace("__KEEP_CORPUS__", $(if ($KeepCorpus) { "1" } else { "0" })) | Set-Content -Encoding UTF8 $tmpScript

& $python $tmpScript
