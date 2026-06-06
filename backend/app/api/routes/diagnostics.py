import json
import re
import sqlite3
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter

from backend.app.core.background_jobs import job_queue_status
from backend.app.core.config import get_settings
from backend.app.core.database import connect, utc_now
from backend.app.core.embeddings import embedding_download_status, embedding_status
from backend.app.core.model_registry import list_models
from backend.app.core.ocr import ocr_runtime_status
from backend.app.core.startup_repair import startup_repair_summary
from backend.app.core.startup_status import read_startup_status
from backend.app.core.storage_accounting import storage_accounting
from backend.app.core.vault_crypto import redact_security_material
from backend.app.core.vector_maintenance import embedding_index_policy, vector_repair_plan
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
        "redaction": "Raw source text, extracted text, URLs, file paths, tokens, passphrases, and recovery keys are not included.",
        "encrypted_storage": (
            "Secured vault content is stored through encrypted_content/blob records; diagnostics include counts only."
        ),
    }
    included_files: list[str] = [
        "manifest.json",
        "database-summary.json",
        "runtime-summary.json",
        "startup-repair-summary.json",
        "vector-summary.json",
        "log-rotation-policy.json",
        "storage-accounting.json",
    ]
    with ZipFile(bundle_path, "w", ZIP_DEFLATED) as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest, indent=2))
        bundle.writestr("database-summary.json", json.dumps(_database_summary(), indent=2))
        bundle.writestr("runtime-summary.json", json.dumps(_runtime_summary(), indent=2))
        bundle.writestr("startup-repair-summary.json", json.dumps(startup_repair_summary(), indent=2))
        bundle.writestr("vector-summary.json", json.dumps(_vector_summary(), indent=2))
        bundle.writestr("log-rotation-policy.json", json.dumps(log_rotation_policy(), indent=2))
        bundle.writestr("storage-accounting.json", json.dumps(storage_accounting(), indent=2))
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
        "encrypted_content",
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


def _runtime_summary() -> dict:
    models = []
    for model in list_models():
        download = model.get("download") or {}
        models.append(
            {
                "id": model["id"],
                "role": model["role"],
                "installed": model["installed"],
                "download_status": download.get("status"),
                "bytes_downloaded": download.get("bytes_downloaded"),
                "bytes_total": download.get("bytes_total") or download.get("total_bytes"),
            }
        )
    return {
        "startup_status": read_startup_status(),
        "ocr": ocr_runtime_status(),
        "embedding": embedding_status(),
        "embedding_download": embedding_download_status(),
        "model_downloads": models,
        "jobs": job_queue_status(),
    }


def _vector_summary() -> dict:
    return {
        "index_policy": embedding_index_policy(),
        "repair_plan": vector_repair_plan(),
    }


def log_rotation_policy() -> dict:
    return {
        "backend_log_dir": str(get_settings().data_dir / "logs"),
        "backend_log_name": "backend.log",
        "max_log_file_bytes": 5 * 1024 * 1024,
        "retained_log_files": 10,
        "max_bundle_log_bytes_per_file": 200_000,
        "redaction_required": True,
    }


def _candidate_logs(data_dir: Path) -> list[tuple[str, Path]]:
    return [
        ("backend.log", data_dir / "logs" / "backend.log"),
        ("backend-dev.log", Path("backend-dev.log")),
        ("desktop-dev.log", Path("desktop-dev.log")),
    ]


def _redact_log(text: str) -> str:
    redacted = redact_security_material(text)
    redacted = re.sub(r"(x-cml-api-token|x-cml-bridge-token|CML_BRIDGE_TOKEN)([=:]\s*)\S+", r"\1\2[redacted]", redacted)
    redacted = re.sub(r"(?i)(authorization:\s*bearer\s+)[A-Za-z0-9._~+/-]+=*", r"\1[redacted]", redacted)
    redacted = re.sub(r"(?i)(token|password|secret)([=:]\s*)[^\s\"']+", r"\1\2[redacted]", redacted)
    redacted = re.sub(r"[A-Za-z]:\\[^\s\"']+", "[local-path]", redacted)
    return redacted[-200_000:]
