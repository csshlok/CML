param(
  [string[]]$Roots = @("C:\Users\csshl\Desktop", "C:\Users\csshl\Documents"),
  [string[]]$ExcludeRoots = @(),
  [int]$MaxFiles = 50,
  [string]$ReportPath = "",
  [string]$DataRoot = "",
  [int]$QueryCount = 20,
  [int]$TopK = 10,
  [int]$TurbovecBitWidth = 4
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  $python = "python"
}

if (-not $DataRoot) {
  $DataRoot = Join-Path $env:TEMP ("cml-real-vault-benchmark-" + [guid]::NewGuid().ToString("n"))
}
if (-not $ReportPath) {
  $ReportPath = Join-Path $DataRoot "real-vault-benchmark-report.json"
}

$env:CML_DATA_DIR = $DataRoot
$env:CML_DATABASE_PATH = Join-Path $DataRoot "cml.sqlite3"
$env:CML_ALLOW_HASH_EMBEDDINGS = "0"
$env:CML_EMBEDDING_PROVIDER = "sentence-transformers"
$env:CML_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

$jsonRoots = $Roots | ConvertTo-Json -Compress
$defaultExcludes = @($repoRoot)
if ($ExcludeRoots.Count -gt 0) {
  $defaultExcludes += $ExcludeRoots
}
$jsonExcludeRoots = $defaultExcludes | ConvertTo-Json -Compress

$code = @'
import json
import os
import time
from pathlib import Path

from backend.app.core.storage_accounting import storage_accounting
from backend.app.core.turbovec_benchmark import (
    benchmark_current_scan,
    benchmark_turbovec_scan,
    corpus_stats,
    discover_pdf_files,
    ensure_benchmark_vault,
    ingest_pdf_corpus,
    load_chunk_rows,
    overlap_report,
    process_metrics,
    projected_costs,
    reindex_vault_sources,
    sampled_queries,
    warm_embedding_runtime,
    write_report,
)

roots = json.loads(os.environ["CML_REAL_BENCHMARK_ROOTS"])
exclude_roots = json.loads(os.environ["CML_REAL_BENCHMARK_EXCLUDE_ROOTS"])
max_files = int(os.environ["CML_REAL_BENCHMARK_MAX_FILES"])
query_count = int(os.environ["CML_REAL_BENCHMARK_QUERY_COUNT"])
top_k = int(os.environ["CML_REAL_BENCHMARK_TOP_K"])
bit_width = int(os.environ["CML_REAL_BENCHMARK_BIT_WIDTH"])
report_path = os.environ["CML_REAL_BENCHMARK_REPORT_PATH"]
index_path = str(Path(report_path).with_suffix(".turbovec.tvim"))

started = time.perf_counter()
vault_id = ensure_benchmark_vault()
warmup = warm_embedding_runtime()
pdfs = discover_pdf_files(roots, max_files=max_files, exclude_roots=exclude_roots)
ingest = ingest_pdf_corpus(pdfs, vault_id=vault_id)
reindex = reindex_vault_sources(vault_id)
rows = load_chunk_rows(vault_id)
queries = sampled_queries(rows, limit=query_count)
corpus = corpus_stats(rows)
current = benchmark_current_scan(rows, queries, top_k=top_k)
index_candidate = benchmark_turbovec_scan(
    rows,
    queries,
    top_k=top_k,
    bit_width=bit_width,
    persist_path=index_path,
)
report = {
    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "roots": roots,
    "requested_max_files": max_files,
    "discovered_pdf_count": len(pdfs),
    "discovered_pdf_sample": [str(path) for path in pdfs[:20]],
    "embedding_warmup": warmup,
    "ingest": ingest,
    "reindex": reindex,
    "corpus": corpus,
    "storage": storage_accounting(vault_id),
    "queries": queries,
    "current_architecture": current,
    "turbovec_prototype": index_candidate,
    "overlap": overlap_report(current, index_candidate, top_k=top_k),
    "process_metrics": process_metrics(),
    "projected_100k_chunk_costs": projected_costs(
        chunk_count=100_000,
        avg_embedding_bytes=float(corpus.get("avg_embedding_bytes", 0.0) or 0.0),
        avg_chunk_text_bytes=float(corpus.get("avg_chunk_text_bytes", 0.0) or 0.0),
        dim=384,
        bit_width=bit_width,
    ),
    "total_seconds": round(time.perf_counter() - started, 4),
}
write_report(report_path, report)
print(json.dumps(report, indent=2))
'@

$env:CML_REAL_BENCHMARK_ROOTS = $jsonRoots
$env:CML_REAL_BENCHMARK_EXCLUDE_ROOTS = $jsonExcludeRoots
$env:CML_REAL_BENCHMARK_MAX_FILES = "$MaxFiles"
$env:CML_REAL_BENCHMARK_QUERY_COUNT = "$QueryCount"
$env:CML_REAL_BENCHMARK_TOP_K = "$TopK"
$env:CML_REAL_BENCHMARK_BIT_WIDTH = "$TurbovecBitWidth"
$env:CML_REAL_BENCHMARK_REPORT_PATH = $ReportPath

$code | & $python -
