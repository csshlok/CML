import hashlib
import json
import os
import platform
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from uuid import uuid4

from backend.app.core.database import connect, utc_now
from backend.app.core.encrypted_storage import is_vault_secured, write_encrypted_file_from_path
from backend.app.core.extraction import (
    MAX_LOCAL_FILE_BYTES,
    MAX_LOCAL_MEDIA_BYTES,
    SUPPORTED_CODE_EXTENSIONS,
    SUPPORTED_DOCUMENT_EXTENSIONS,
    SUPPORTED_IMAGE_EXTENSIONS,
    SUPPORTED_MEDIA_EXTENSIONS,
    SUPPORTED_TEXT_EXTENSIONS,
    ExtractionError,
    extract_pages_from_validated_path,
)
from backend.app.core.vault_crypto import is_vault_unlocked

MAX_TEXT_OUTPUT_BYTES = 5 * 1024 * 1024
MAX_WORKER_JSON_BYTES = 6 * 1024 * 1024
MAX_PAGE_COUNT = 500
MAX_PAGE_TEXT_BYTES = 512 * 1024
MAX_DOCX_ENTRIES = 2000
MAX_DOCX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_DOCX_EXPANSION_RATIO = 100
MAX_PDF_PAGES = 1000
PARSER_TIMEOUT_SECONDS = 180
IN_PROCESS_PARSER_EXTENSIONS = SUPPORTED_TEXT_EXTENSIONS | SUPPORTED_CODE_EXTENSIONS


class QuarantineError(ExtractionError):
    pass


def ingest_file_through_quarantine(vault_id: str, path: str) -> dict:
    candidate = validate_candidate_file(path)
    defender = defender_scan(candidate["canonical_path"])
    encrypted_blob = _encrypted_quarantine_blob(vault_id, Path(candidate["canonical_path"]))
    record_id = create_quarantine_record(vault_id, candidate, defender, encrypted_blob=encrypted_blob)
    try:
        parsed = parse_candidate_file(candidate)
        update_quarantine_record(
            record_id,
            validation_status="passed",
            parser_status="passed",
            parser_detail="worker_output_validated",
            trust_tier=_trust_tier(candidate, defender),
        )
    except Exception as exc:
        update_quarantine_record(
            record_id,
            validation_status="passed",
            parser_status="failed",
            parser_detail=str(exc)[:500],
            trust_tier="quarantined",
        )
        raise
    parsed["quarantine_record_id"] = record_id
    parsed["security"] = {
        "validation": candidate,
        "defender": defender,
        "encrypted_blob": encrypted_blob,
        "trust_tier": _trust_tier(candidate, defender),
        "provenance": "local_import",
        "security_labels": _security_labels(candidate, defender),
    }
    return parsed


def parse_candidate_file(candidate: dict) -> dict:
    suffix = str(candidate.get("suffix") or "").lower()
    path = str(candidate.get("canonical_path") or "")
    if suffix in IN_PROCESS_PARSER_EXTENSIONS:
        title, pages = extract_pages_from_validated_path(path)
        return validate_worker_output({"title": title, "pages": pages})
    return run_parser_worker(path)


def validate_candidate_file(path: str) -> dict:
    original = Path(path).expanduser()
    try:
        stat_result = original.lstat()
    except OSError as exc:
        raise QuarantineError("File does not exist or is not readable") from exc
    if stat.S_ISLNK(stat_result.st_mode):
        raise QuarantineError("Refusing to ingest symlinked files")
    if _is_windows_reparse_point(stat_result):
        raise QuarantineError("Refusing to ingest Windows reparse-point files")
    try:
        canonical = original.resolve(strict=True)
        resolved_stat = canonical.stat()
    except OSError as exc:
        raise QuarantineError("File does not exist or is not readable") from exc
    if not canonical.is_file():
        raise QuarantineError("File does not exist or is not readable")
    suffix = canonical.suffix.lower()
    if suffix not in SUPPORTED_DOCUMENT_EXTENSIONS:
        raise QuarantineError("This file type is not supported for local vault ingestion yet")
    size = int(resolved_stat.st_size)
    max_bytes = MAX_LOCAL_MEDIA_BYTES if suffix in SUPPORTED_MEDIA_EXTENSIONS else MAX_LOCAL_FILE_BYTES
    if size > max_bytes:
        raise QuarantineError("File is too large to ingest safely")
    magic = _validate_magic(canonical, suffix)
    structural = _structural_limits(canonical, suffix, size)
    return {
        "original_path": str(original),
        "canonical_path": str(canonical),
        "file_name": canonical.name,
        "suffix": suffix,
        "file_size": size,
        "content_hash": _file_sha256(canonical),
        "magic": magic,
        "structural": structural,
    }


def create_quarantine_record(
    vault_id: str,
    candidate: dict,
    defender: dict,
    *,
    encrypted_blob: dict | None = None,
) -> str:
    now = utc_now()
    record_id = f"quarantine-{uuid4()}"
    blob = encrypted_blob or {}
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO source_quarantine_records (
                id, vault_id, original_path, canonical_path, file_name, suffix,
                file_size, content_hash, encrypted_blob_id, encrypted_blob_path,
                validation_status, validation_json, defender_status, defender_detail,
                parser_status, parser_detail, trust_tier, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'passed', ?, ?, ?, 'pending', '', 'quarantined', ?, ?)
            """,
            (
                record_id,
                vault_id,
                candidate["original_path"],
                candidate["canonical_path"],
                candidate["file_name"],
                candidate["suffix"],
                candidate["file_size"],
                candidate["content_hash"],
                blob.get("blob_id", ""),
                blob.get("path", ""),
                json.dumps(candidate, sort_keys=True),
                defender["status"],
                defender["detail"],
                now,
                now,
            ),
        )
    return record_id


def attach_quarantine_record(record_id: str, source_id: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE source_quarantine_records SET source_id = ?, updated_at = ? WHERE id = ?",
            (source_id, utc_now(), record_id),
        )


def update_quarantine_record(
    record_id: str,
    *,
    validation_status: str,
    parser_status: str,
    parser_detail: str,
    trust_tier: str,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE source_quarantine_records
            SET validation_status = ?,
                parser_status = ?,
                parser_detail = ?,
                trust_tier = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (validation_status, parser_status, parser_detail, trust_tier, utc_now(), record_id),
        )


def run_parser_worker(path: str) -> dict:
    command = [sys.executable, "-m", "backend.app.core.parser_worker", path]
    env = _worker_env()
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=PARSER_TIMEOUT_SECONDS,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise QuarantineError("Parser worker timed out") from exc
    except OSError as exc:
        raise QuarantineError(f"Parser worker failed to launch: {exc}") from exc
    stdout_text = _decode_worker_stream(completed.stdout)
    stderr_text = _decode_worker_stream(completed.stderr)
    if completed.returncode != 0:
        detail = (stderr_text or stdout_text or "Parser worker failed").strip()
        raise QuarantineError(detail[:500])
    raw = stdout_text.encode("utf-8")
    if len(raw) > MAX_WORKER_JSON_BYTES:
        raise QuarantineError("Parser worker output exceeded the allowed size")
    try:
        payload = json.loads(stdout_text)
    except json.JSONDecodeError as exc:
        raise QuarantineError("Parser worker returned malformed JSON") from exc
    return validate_worker_output(payload)


def _decode_worker_stream(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def validate_worker_output(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise QuarantineError("Parser worker returned invalid output")
    title = payload.get("title")
    pages = payload.get("pages")
    if not isinstance(title, str) or not title.strip():
        raise QuarantineError("Parser worker output missing title")
    if not isinstance(pages, list) or not pages or len(pages) > MAX_PAGE_COUNT:
        raise QuarantineError("Parser worker output has invalid page count")
    total = 0
    clean_pages: list[str] = []
    for page in pages:
        if not isinstance(page, str):
            raise QuarantineError("Parser worker output page is invalid")
        text = _normalize_worker_text(page)
        encoded_length = len(text.encode("utf-8"))
        if encoded_length > MAX_PAGE_TEXT_BYTES:
            raise QuarantineError("Parser worker output page exceeded the allowed size")
        total += encoded_length
        if total > MAX_TEXT_OUTPUT_BYTES:
            raise QuarantineError("Parser worker output exceeded the allowed total text size")
        if text.strip():
            clean_pages.append(text)
    if not clean_pages:
        raise QuarantineError("Parser worker produced no readable text")
    return {
        "title": title[:240],
        "pages": clean_pages,
    }


def defender_scan(path: str) -> dict:
    if platform.system().lower() != "windows":
        return {"status": "unavailable", "detail": "Windows Defender scan is only available on Windows."}
    candidates = [
        Path(os.environ.get("ProgramFiles", "")) / "Windows Defender" / "MpCmdRun.exe",
        Path(os.environ.get("ProgramData", "")) / "Microsoft" / "Windows Defender" / "Platform",
    ]
    executable = None
    for candidate in candidates:
        if candidate.is_file():
            executable = candidate
            break
        if candidate.is_dir():
            matches = sorted(candidate.glob("*/MpCmdRun.exe"), reverse=True)
            if matches:
                executable = matches[0]
                break
    if executable is None:
        return {"status": "unavailable", "detail": "MpCmdRun.exe was not found."}
    try:
        completed = subprocess.run(
            [str(executable), "-Scan", "-ScanType", "3", "-File", path],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "unavailable", "detail": str(exc)[:500]}
    if completed.returncode == 0:
        return {"status": "passed", "detail": "Windows Defender reported no detected threat."}
    detail = (completed.stderr or completed.stdout or f"Defender returned {completed.returncode}").strip()
    return {"status": "failed", "detail": detail[:500]}


def _encrypted_quarantine_blob(vault_id: str, path: Path) -> dict | None:
    with connect() as conn:
        secured = is_vault_secured(conn, vault_id)
    if not secured or not is_vault_unlocked(vault_id):
        return None
    return write_encrypted_file_from_path(vault_id=vault_id, source_path=path, blob_id=f"quarantine-{uuid4()}")


def _validate_magic(path: Path, suffix: str) -> dict:
    header = path.read_bytes()[:16]
    if suffix == ".pdf" and not header.startswith(b"%PDF-"):
        raise QuarantineError("PDF file failed magic validation")
    if suffix == ".docx" and not zipfile.is_zipfile(path):
        raise QuarantineError("DOCX file failed ZIP container validation")
    if suffix in SUPPORTED_IMAGE_EXTENSIONS and not _looks_like_image(header, suffix):
        raise QuarantineError("Image file failed magic validation")
    return {"status": "passed", "header_checked": True}


def _structural_limits(path: Path, suffix: str, size: int) -> dict:
    if suffix == ".docx":
        return _validate_docx_zip(path, size)
    if suffix == ".pdf":
        return _validate_pdf_structure(path)
    if suffix in SUPPORTED_IMAGE_EXTENSIONS:
        return {"status": "passed", "max_dimension_check": "deferred_to_parser"}
    return {"status": "passed"}


def _validate_docx_zip(path: Path, size: int) -> dict:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            total_uncompressed = sum(max(0, item.file_size) for item in infos)
            has_document = any(item.filename == "word/document.xml" for item in infos)
    except zipfile.BadZipFile as exc:
        raise QuarantineError("DOCX file failed ZIP structure validation") from exc
    if len(infos) > MAX_DOCX_ENTRIES:
        raise QuarantineError("DOCX file has too many entries")
    if total_uncompressed > MAX_DOCX_UNCOMPRESSED_BYTES:
        raise QuarantineError("DOCX uncompressed size is too large")
    ratio = total_uncompressed / max(size, 1)
    if ratio > MAX_DOCX_EXPANSION_RATIO:
        raise QuarantineError("DOCX expansion ratio is too high")
    if not has_document:
        raise QuarantineError("DOCX is missing word/document.xml")
    return {
        "status": "passed",
        "entry_count": len(infos),
        "uncompressed_bytes": total_uncompressed,
        "expansion_ratio": round(ratio, 2),
    }


def _validate_pdf_structure(path: Path) -> dict:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path), strict=False)
        page_count = len(reader.pages)
    except Exception:
        # Some scanned PDFs require OCR tools to open. Magic and size checks still apply pre-worker.
        return {"status": "passed", "page_count": None, "page_count_check": "deferred_to_parser"}
    if page_count > MAX_PDF_PAGES:
        raise QuarantineError("PDF has too many pages")
    return {"status": "passed", "page_count": page_count}


def _looks_like_image(header: bytes, suffix: str) -> bool:
    if suffix in {".jpg", ".jpeg"}:
        return header.startswith(b"\xff\xd8\xff")
    if suffix == ".png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix == ".gif":
        return header.startswith((b"GIF87a", b"GIF89a"))
    if suffix == ".bmp":
        return header.startswith(b"BM")
    if suffix in {".tif", ".tiff"}:
        return header.startswith((b"II*\x00", b"MM\x00*"))
    if suffix == ".webp":
        return header.startswith(b"RIFF") and header[8:12] == b"WEBP"
    return True


def _is_windows_reparse_point(stat_result: os.stat_result) -> bool:
    return bool(getattr(stat_result, "st_file_attributes", 0) & 0x400)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_worker_text(text: str) -> str:
    return text.replace("\x00", "").strip()


def _worker_env() -> dict[str, str]:
    env = os.environ.copy()
    env["CML_PARSER_WORKER"] = "1"
    for key in list(env):
        upper = key.upper()
        if upper in {"CML_API_TOKEN", "CML_BRIDGE_TOKEN"}:
            env.pop(key, None)
        elif upper.startswith("CML_") and upper not in {"CML_PARSER_WORKER"}:
            env.pop(key, None)
    return env


def _trust_tier(candidate: dict, defender: dict) -> str:
    if defender["status"] == "failed":
        return "quarantined"
    return "imported_local"


def _security_labels(candidate: dict, defender: dict) -> list[str]:
    labels = ["local_file", "structurally_validated", "parser_worker"]
    if defender["status"] == "passed":
        labels.append("defender_passed")
    elif defender["status"] == "unavailable":
        labels.append("defender_unavailable")
    else:
        labels.append("defender_failed")
    if candidate["suffix"] in {".pdf", ".docx"}:
        labels.append("complex_document")
    return labels
