import json
import re
import sqlite3
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter

from backend.app.core.background_jobs import enqueue_job, job_queue_status
from backend.app.core.config import get_settings
from backend.app.core.database import connect, utc_now
from backend.app.core.embeddings import embedding_download_status, embedding_status
from backend.app.core.model_registry import list_models
from backend.app.core.migration_planner import staging_summary
from backend.app.core.ocr import ocr_runtime_status
from backend.app.core.startup_repair import startup_repair_summary
from backend.app.core.startup_status import read_startup_status
from backend.app.core.version import app_version
from backend.app.core.storage_accounting import storage_accounting
from backend.app.core.vault_crypto import redact_security_material
from backend.app.core.vector_maintenance import embedding_index_policy, vector_repair_plan
from backend.app.schemas import AppJobRead, DiagnosticBundleJobRequest, DiagnosticBundleResponse

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])

BUNDLE_FORMAT_VERSION = 2
BACKEND_VERSION = app_version()


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
        "app_version": BACKEND_VERSION,
        "backend_version": BACKEND_VERSION,
        "schema_version": schema_version,
        "redaction": (
            "Raw logs, source text, extracted text, prompts, URLs, file paths, "
            "tokens, passphrases, and recovery keys are not included."
        ),
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
        "migration-staging-summary.json",
        "log-summary.json",
    ]
    with ZipFile(bundle_path, "w", ZIP_DEFLATED) as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest, indent=2))
        bundle.writestr("database-summary.json", json.dumps(_database_summary(), indent=2))
        bundle.writestr("runtime-summary.json", json.dumps(_runtime_summary(), indent=2))
        bundle.writestr(
            "startup-repair-summary.json",
            json.dumps(_privacy_safe(startup_repair_summary()), indent=2),
        )
        bundle.writestr("vector-summary.json", json.dumps(_privacy_safe(_vector_summary()), indent=2))
        bundle.writestr("log-rotation-policy.json", json.dumps(log_rotation_policy(), indent=2))
        bundle.writestr(
            "storage-accounting.json",
            json.dumps(_privacy_safe(storage_accounting()), indent=2),
        )
        bundle.writestr(
            "migration-staging-summary.json",
            json.dumps(_privacy_safe(staging_summary()), indent=2),
        )
        bundle.writestr("log-summary.json", json.dumps(_log_summary(settings.data_dir), indent=2))
    return {
        "bundle_path": str(bundle_path),
        "bundle_format_version": BUNDLE_FORMAT_VERSION,
        "bundle_generated_at": generated_at,
        "app_version": BACKEND_VERSION,
        "backend_version": BACKEND_VERSION,
        "schema_version": schema_version,
        "included_files": included_files,
    }


@router.post("/bundle", response_model=AppJobRead, status_code=202)
def queue_diagnostic_bundle(payload: DiagnosticBundleJobRequest | None = None) -> dict:
    request = payload or DiagnosticBundleJobRequest()
    with connect() as conn:
        return enqueue_job(
            conn,
            job_type="diagnostic_bundle",
            payload={},
            dedupe_key=request.idempotency_key or "diagnostic-bundle:active",
            user_initiated=True,
        )


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
        "source_quarantine_records",
        "chat_sessions",
        "chat_messages",
        "chat_attachments",
        "temporal_facts",
        "temporal_fact_session_state",
        "atomic_memory_facts",
        "atomic_memory_source_units",
        "atomic_memory_session_state",
        "atomic_memory_semantic_state",
        "temporal_fact_reviews",
        "app_jobs",
        "bridge_requests",
        "vault_lock_audit",
        "integration_imports",
        "extension_captures",
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
        "startup_status": _safe_startup_status(read_startup_status()),
        "ocr": ocr_runtime_status(),
        "embedding": embedding_status(probe_model=False),
        "embedding_download": embedding_download_status(),
        "model_downloads": models,
        "jobs": _safe_job_summary(job_queue_status()),
    }


def _vector_summary() -> dict:
    return {
        "index_policy": embedding_index_policy(),
        "repair_plan": vector_repair_plan(),
    }


def log_rotation_policy() -> dict:
    return {
        "backend_log_name": "backend.log",
        "max_log_file_bytes": 5 * 1024 * 1024,
        "retained_log_files": 10,
        "max_bundle_log_bytes_per_file": 200_000,
        "raw_logs_included": False,
    }


def _candidate_logs(data_dir: Path) -> list[tuple[str, Path]]:
    startup_status_path = get_settings().startup_status_path
    electron_log_dir = startup_status_path.parent if startup_status_path is not None else None
    logs = [
        ("backend.log", data_dir / "logs" / "backend.log"),
        ("backend-dev.log", Path("backend-dev.log")),
        ("desktop-dev.log", Path("desktop-dev.log")),
    ]
    if electron_log_dir is not None:
        logs.extend(
            [
                ("desktop-runtime.log", electron_log_dir / "desktop-runtime.log"),
                ("backend-stdout.log", electron_log_dir / "backend-stdout.log"),
                ("backend-stderr.log", electron_log_dir / "backend-stderr.log"),
            ]
        )
    return logs


def _redact_log(text: str) -> str:
    redacted = redact_security_material(text)
    redacted = re.sub(r"(x-cml-api-token|x-cml-bridge-token|CML_BRIDGE_TOKEN)([=:]\s*)\S+", r"\1\2[redacted]", redacted)
    redacted = re.sub(r"(?i)(authorization:\s*bearer\s+)[A-Za-z0-9._~+/-]+=*", r"\1[redacted]", redacted)
    redacted = re.sub(r"(?i)(token|password|secret)([=:]\s*)[^\s\"']+", r"\1\2[redacted]", redacted)
    redacted = re.sub(r"(?i)\b(https?://)[^/\s\"'@]+@([^\s\"']+)", r"\1[redacted]@\2", redacted)
    redacted = re.sub(r"[A-Za-z]:\\[^\s\"']+", "[local-path]", redacted)
    return redacted[-200_000:]


def _safe_startup_status(status: dict | None) -> dict | None:
    if status is None:
        return None
    allowed = {
        "startup_instance_id",
        "sequence",
        "phase",
        "status",
        "error_code",
        "backend_mode",
        "updated_at",
        "total_elapsed_ms",
        "previous_phase",
        "previous_phase_duration_ms",
    }
    return {key: status.get(key) for key in allowed if key in status}


def _safe_job_summary(summary: dict) -> dict:
    safe: dict = {}
    for key, value in summary.items():
        if key in {"running_jobs", "latest"}:
            if not isinstance(value, list):
                continue
            safe[key] = [
                {
                    field: row.get(field)
                    for field in (
                        "id",
                        "job_type",
                        "status",
                        "attempts",
                        "max_attempts",
                        "error_code",
                        "diagnostic_id",
                        "created_at",
                        "updated_at",
                    )
                    if isinstance(row, dict) and field in row
                }
                for row in value[:50]
                if isinstance(row, dict)
            ]
        elif isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
    return safe


def _privacy_safe(value, *, key: str = ""):
    normalized_key = key.casefold()
    if normalized_key.endswith("error_code") or normalized_key.endswith("diagnostic_id"):
        return value
    if any(
        marker in normalized_key
        for marker in (
            "path",
            "url",
            "message",
            "detail",
            "prompt",
            "token",
            "passphrase",
            "password",
            "secret",
            "recovery_key",
            "raw_text",
            "source_text",
        )
    ):
        if value in (None, "", [], {}):
            return value
        return "[redacted]"
    if normalized_key == "issues" and isinstance(value, list):
        return [_issue_code(item) for item in value]
    if isinstance(value, dict):
        return {str(child_key): _privacy_safe(child, key=str(child_key)) for child_key, child in value.items()}
    if isinstance(value, list):
        return [_privacy_safe(item, key=key) for item in value]
    if isinstance(value, str):
        return _redact_log(value)
    return value


def _issue_code(value) -> str:
    prefix = str(value or "").split(":", 1)[0].strip()
    return prefix if re.fullmatch(r"[a-z][a-z0-9_]{2,80}", prefix) else "diagnostic_issue"


def _read_log_tail(path: Path, max_bytes: int = 200_000) -> str:
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - max_bytes))
        return handle.read(max_bytes).decode("utf-8", errors="ignore")


def _log_summary(data_dir: Path) -> dict:
    files = []
    level_pattern = re.compile(r"\b(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL)\b", re.IGNORECASE)
    diagnostic_pattern = re.compile(r"\bdiagnostic(?:_id)?[=:]\s*([a-f0-9-]{8,64})\b", re.IGNORECASE)
    for name, path in _candidate_logs(data_dir):
        if not path.exists() or not path.is_file():
            continue
        try:
            tail = _read_log_tail(path)
            counts: dict[str, int] = {}
            diagnostic_ids: list[str] = []
            for line in tail.splitlines():
                match = level_pattern.search(line)
                if match:
                    level = "warning" if match.group(1).casefold() == "warn" else match.group(1).casefold()
                    counts[level] = counts.get(level, 0) + 1
                diagnostic = diagnostic_pattern.search(line)
                if diagnostic and diagnostic.group(1) not in diagnostic_ids:
                    diagnostic_ids.append(diagnostic.group(1))
            files.append(
                {
                    "name": name,
                    "size_bytes": path.stat().st_size,
                    "sampled_bytes": len(tail.encode("utf-8")),
                    "line_count": len(tail.splitlines()),
                    "level_counts": counts,
                    "diagnostic_ids": diagnostic_ids[:100],
                }
            )
        except OSError:
            files.append({"name": name, "status": "unavailable"})
    return {"raw_logs_included": False, "files": files}
