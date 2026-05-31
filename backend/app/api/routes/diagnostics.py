import json
import re
import sqlite3
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter

from backend.app.core.config import get_settings
from backend.app.core.database import connect, utc_now
from backend.app.schemas import DiagnosticBundleResponse

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])

BUNDLE_FORMAT_VERSION = 1
BACKEND_VERSION = "0.1.0"


@router.post("/bundle", response_model=DiagnosticBundleResponse)
def create_diagnostic_bundle() -> dict:
    settings = get_settings()
    generated_at = utc_now()
    diagnostics_dir = settings.data_dir / "diagnostics"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = diagnostics_dir / f"vault-diagnostics-{uuid4()}.zip"
    schema_version = _schema_version()
    manifest = {
        "bundle_format_version": BUNDLE_FORMAT_VERSION,
        "bundle_generated_at": generated_at,
        "app_version": "0.1.0",
        "backend_version": BACKEND_VERSION,
        "schema_version": schema_version,
        "redaction": "Raw source text, extracted text, URLs, file paths, and tokens are not included.",
    }
    included_files: list[str] = ["manifest.json", "database-summary.json"]
    with ZipFile(bundle_path, "w", ZIP_DEFLATED) as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest, indent=2))
        bundle.writestr("database-summary.json", json.dumps(_database_summary(), indent=2))
        for name, path in _candidate_logs(settings.data_dir):
            if path.exists() and path.is_file():
                bundle.writestr(f"logs/{name}", _redact_log(path.read_text(encoding="utf-8", errors="ignore")))
                included_files.append(f"logs/{name}")
    return {
        "bundle_path": str(bundle_path),
        "bundle_format_version": BUNDLE_FORMAT_VERSION,
        "bundle_generated_at": generated_at,
        "app_version": "0.1.0",
        "backend_version": BACKEND_VERSION,
        "schema_version": schema_version,
        "included_files": included_files,
    }


def _schema_version() -> int:
    with connect() as conn:
        row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0] if row else 0)


def _database_summary() -> dict:
    tables = [
        "vaults",
        "clusters",
        "sources",
        "source_pages",
        "source_chunks",
        "chat_sessions",
        "chat_messages",
        "chat_attachments",
        "app_jobs",
        "bridge_requests",
        "vault_lock_audit",
        "integration_imports",
        "extension_captures",
        "expert_artifacts",
    ]
    summary = {}
    with connect() as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchall()
        summary["integrity_check"] = [row[0] for row in integrity]
        for table in tables:
            try:
                row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
                summary[table] = int(row["count"])
            except sqlite3.Error:
                summary[table] = None
    return summary


def _candidate_logs(data_dir: Path) -> list[tuple[str, Path]]:
    return [
        ("backend.log", data_dir / "logs" / "backend.log"),
        ("backend-dev.log", Path("backend-dev.log")),
        ("desktop-dev.log", Path("desktop-dev.log")),
    ]


def _redact_log(text: str) -> str:
    redacted = re.sub(r"(x-cml-api-token|x-cml-bridge-token|CML_BRIDGE_TOKEN)([=:]\s*)\\S+", r"\1\2[redacted]", text)
    redacted = re.sub(r"[A-Za-z]:\\\\[^\\s\"']+", "[local-path]", redacted)
    return redacted[-200_000:]
