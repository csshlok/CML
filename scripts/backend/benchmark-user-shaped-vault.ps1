param(
  [string]$ReportRoot = "T:\CML-build-smoke\user-shaped-retrieval",
  [int]$Sources = 100
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}

$env:CML_DATA_DIR = $ReportRoot
$env:CML_DATABASE_PATH = Join-Path $ReportRoot "cml.sqlite3"
$env:CML_ALLOW_HASH_EMBEDDINGS = "1"
$env:CML_EMBEDDING_PROVIDER = "hash"

$code = @'
import json
import os
from pathlib import Path

from backend.app.core.config import ROOT_DIR, get_settings
from backend.app.core.database import connect, dict_from_row, init_db, utc_now
from backend.app.core.embeddings import reindex_source_chunks
from backend.app.core.retrieval_scoring import export_benchmark_report

source_limit = int(os.environ.get("CML_USER_SHAPED_SOURCES", "100"))
settings = get_settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
init_db()
now = utc_now()

candidate_files = [
    ROOT_DIR / "docs" / "PROJECT_CONTEXT.md",
    ROOT_DIR / "docs" / "OVERALL_CONTEXT.md",
    ROOT_DIR / "ReadME.md",
    ROOT_DIR / "docs" / "WORKING_COMMANDS.md",
    ROOT_DIR / "docs" / "RELEASE_VALIDATION_CHECKLIST.md",
]
chunks = []
for path in candidate_files:
    if not path.exists():
        continue
    text = path.read_text(encoding="utf-8", errors="ignore")
    paragraphs = [item.strip() for item in text.split("\n\n") if len(item.strip()) > 120]
    for index, paragraph in enumerate(paragraphs):
        chunks.append((path.name, index, paragraph))
        if len(chunks) >= source_limit:
            break
    if len(chunks) >= source_limit:
        break

with connect() as conn:
    conn.execute(
        "INSERT OR IGNORE INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("vault-user-shaped", "User Shaped Benchmark", str(settings.data_dir), now, now),
    )
    for index, (name, para_index, text) in enumerate(chunks):
        source_id = f"user-shaped-source-{index:04d}"
        conn.execute(
            """
            INSERT OR REPLACE INTO sources (
                id, vault_id, title, source_type, state, raw_text, extracted_text, summary, tags, created_at, updated_at
            )
            VALUES (?, 'vault-user-shaped', ?, 'note', 'indexed', ?, ?, '', '[]', ?, ?)
            """,
            (source_id, f"{name} paragraph {para_index}", text, text, now, now),
        )
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        reindex_source_chunks(conn, dict_from_row(row))

report = export_benchmark_report(
    "vault-user-shaped",
    fixtures=[
        {"query": "OCR Ghostscript Tesseract packaging", "must_include_source_ids": []},
        {"query": "MCP Bridge external turn capture", "must_include_source_ids": []},
        {"query": "retrieval threshold source class weighting", "must_include_source_ids": []},
    ],
)
print(json.dumps({"sources": len(chunks), **report}, indent=2))
'@

$env:CML_USER_SHAPED_SOURCES = "$Sources"
$code | & $python -
