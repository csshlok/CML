import hashlib
import ctypes
import json
import os
import platform
import random
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from uuid import uuid4

from backend.app.core.database import connect, utc_now
from backend.app.core.encrypted_storage import (
    delete_encrypted_blob_file,
    is_vault_secured,
    write_encrypted_file_from_path,
)
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
MAX_IMAGE_PIXELS = 50_000_000
MAX_IMAGE_DIMENSION = 30_000
PARSER_MEMORY_BYTES = 1536 * 1024 * 1024
PARSER_MAX_PROCESSES = 8
PARSER_TIMEOUT_SECONDS = 180
IN_PROCESS_PARSER_EXTENSIONS = SUPPORTED_TEXT_EXTENSIONS | SUPPORTED_CODE_EXTENSIONS


class QuarantineError(ExtractionError):
    pass


def ingest_file_through_quarantine(vault_id: str, path: str) -> dict:
    candidate = validate_candidate_file(path)
    defender = defender_scan(candidate["canonical_path"])
    sandbox_only_policy = (
        platform.system().lower() == "windows"
        and defender["status"] == "unavailable"
        and os.environ.get("CML_SANDBOX_ONLY_ALLOW_DEFENDER_UNAVAILABLE", "").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    encrypted_blob = _encrypted_quarantine_blob(vault_id, Path(candidate["canonical_path"]))
    record_id = create_quarantine_record(vault_id, candidate, defender, encrypted_blob=encrypted_blob)
    if defender["status"] == "failed" or (
        platform.system().lower() == "windows"
        and defender["status"] == "unavailable"
        and not sandbox_only_policy
    ):
        update_quarantine_record(
            record_id,
            validation_status="blocked",
            parser_status="not_run",
            parser_detail="malware_scan_did_not_pass",
            trust_tier="quarantined",
        )
        raise QuarantineError("File remained quarantined because Windows Defender did not pass it")
    try:
        parsed = parse_candidate_file(candidate, force_sandbox=sandbox_only_policy)
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
        "parser": parsed.get("parser") or {},
    }
    return parsed


def parse_candidate_file(candidate: dict, *, force_sandbox: bool = False) -> dict:
    suffix = str(candidate.get("suffix") or "").lower()
    path = str(candidate.get("canonical_path") or "")
    if suffix in IN_PROCESS_PARSER_EXTENSIONS and not force_sandbox:
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


def delete_quarantine_artifacts_for_source(conn, source_id: str) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT id, vault_id, encrypted_blob_id
        FROM source_quarantine_records
        WHERE source_id = ?
        ORDER BY created_at, id
        """,
        (source_id,),
    ).fetchall()
    blobs_deleted = 0
    for row in rows:
        blob_id = str(row["encrypted_blob_id"] or "")
        if blob_id:
            references = conn.execute(
                "SELECT COUNT(*) AS count FROM source_quarantine_records WHERE encrypted_blob_id = ?",
                (blob_id,),
            ).fetchone()
            if int(references["count"] or 0) <= 1:
                blobs_deleted += int(
                    delete_encrypted_blob_file(vault_id=str(row["vault_id"]), blob_id=blob_id)
                )
    deleted = conn.execute(
        "DELETE FROM source_quarantine_records WHERE source_id = ?",
        (source_id,),
    ).rowcount
    return {"records_deleted": int(deleted), "blobs_deleted": blobs_deleted}


def prune_unattached_quarantine_artifacts(
    conn,
    *,
    passed_cutoff: str,
    failed_cutoff: str,
    limit: int,
    dry_run: bool = False,
) -> dict[str, int | bool]:
    bounded_limit = max(1, min(int(limit), 5_000))
    rows = conn.execute(
        """
        SELECT id, vault_id, encrypted_blob_id
        FROM source_quarantine_records
        WHERE source_id IS NULL AND (
            (parser_status = 'passed' AND updated_at < ?)
            OR (parser_status != 'passed' AND updated_at < ?)
        )
        ORDER BY updated_at, id
        LIMIT ?
        """,
        (passed_cutoff, failed_cutoff, bounded_limit),
    ).fetchall()
    if dry_run:
        return {
            "eligible": len(rows),
            "deleted": 0,
            "blobs_deleted": 0,
            "batch_limited": len(rows) == bounded_limit,
        }
    deleted = 0
    blobs_deleted = 0
    skipped = 0
    for row in rows:
        blob_id = str(row["encrypted_blob_id"] or "")
        try:
            if blob_id:
                references = conn.execute(
                    "SELECT COUNT(*) AS count FROM source_quarantine_records WHERE encrypted_blob_id = ?",
                    (blob_id,),
                ).fetchone()
                if int(references["count"] or 0) <= 1:
                    blobs_deleted += int(
                        delete_encrypted_blob_file(vault_id=str(row["vault_id"]), blob_id=blob_id)
                    )
            deleted += int(
                conn.execute(
                    "DELETE FROM source_quarantine_records WHERE id = ? AND source_id IS NULL",
                    (row["id"],),
                ).rowcount
            )
        except OSError:
            skipped += 1
    return {
        "eligible": len(rows),
        "deleted": deleted,
        "blobs_deleted": blobs_deleted,
        "skipped": skipped,
        "batch_limited": len(rows) == bounded_limit,
    }


def run_parser_worker(path: str) -> dict:
    command = [sys.executable, "-m", "backend.app.core.parser_worker", path]
    env = _worker_env()
    stdout_file = tempfile.TemporaryFile()
    stderr_file = tempfile.TemporaryFile()
    process = None
    job = None
    try:
        process = subprocess.Popen(
            command,
            stdout=stdout_file,
            stderr=stderr_file,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0,
        )
        job = _assign_windows_parser_job(process)
        if os.name == "nt" and job is None:
            _terminate_parser_tree(process, None)
            raise QuarantineError("Parser worker containment could not be established")
        try:
            return_code = process.wait(timeout=PARSER_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            _terminate_parser_tree(process, job)
            raise QuarantineError("Parser worker timed out") from exc
    except OSError as exc:
        raise QuarantineError(f"Parser worker failed to launch: {exc}") from exc
    finally:
        if job is not None:
            job.close()
    stdout_file.seek(0)
    stderr_file.seek(0)
    stdout_bytes = stdout_file.read(MAX_WORKER_JSON_BYTES + 1)
    stderr_bytes = stderr_file.read(64 * 1024 + 1)
    stdout_file.close()
    stderr_file.close()
    if len(stdout_bytes) > MAX_WORKER_JSON_BYTES:
        raise QuarantineError("Parser worker output exceeded the allowed size")
    stdout_text = _decode_worker_stream(stdout_bytes)
    stderr_text = _decode_worker_stream(stderr_bytes)
    if return_code != 0:
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


class _WindowsParserJob:
    def __init__(self, handle):
        self.handle = handle

    def terminate(self) -> None:
        if self.handle:
            ctypes.windll.kernel32.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        if self.handle:
            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None


def _assign_windows_parser_job(process) -> _WindowsParserJob | None:
    if os.name != "nt":
        return None

    class BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
        )]

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    kernel32.SetInformationJobObject.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32,
    ]
    kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel32.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        return None
    info = ExtendedLimitInformation()
    info.BasicLimitInformation.LimitFlags = 0x2000 | 0x100 | 0x200 | 0x8
    info.BasicLimitInformation.ActiveProcessLimit = PARSER_MAX_PROCESSES
    info.ProcessMemoryLimit = PARSER_MEMORY_BYTES
    info.JobMemoryLimit = PARSER_MEMORY_BYTES
    configured = kernel32.SetInformationJobObject(
        handle, 9, ctypes.byref(info), ctypes.sizeof(info)
    )
    assigned = configured and kernel32.AssignProcessToJobObject(
        handle, ctypes.c_void_p(int(process._handle))
    )
    if not assigned:
        kernel32.CloseHandle(handle)
        return None
    return _WindowsParserJob(handle)


def _terminate_parser_tree(process, job: _WindowsParserJob | None) -> None:
    if job is not None:
        job.terminate()
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        return
    process.kill()


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
    parser = payload.get("parser") if isinstance(payload.get("parser"), dict) else {}
    return {
        "title": title[:240],
        "pages": clean_pages,
        "parser": parser,
    }


def defender_scan(path: str, *, max_attempts: int = 3) -> dict:
    attempts = max(1, min(int(max_attempts), 5))
    result = {"status": "unavailable", "classification": "permanent", "detail": "Scanner unavailable."}
    for attempt in range(attempts):
        result = _defender_scan_once(path)
        result["attempts"] = attempt + 1
        if result["status"] != "unavailable" or result.get("classification") != "transient":
            return result
        if attempt + 1 < attempts:
            time.sleep((0.2 * (2**attempt)) + random.uniform(0, 0.1))
    return result


def _defender_scan_once(path: str) -> dict:
    if platform.system().lower() != "windows":
        return {
            "status": "unavailable",
            "classification": "permanent",
            "detail": "Windows Defender scan is only available on Windows.",
        }
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
    command = None
    scanner = "mpcmdrun"
    if executable is not None:
        command = [str(executable), "-Scan", "-ScanType", "3", "-File", path]
    else:
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if powershell:
            scanner = "powershell_defender"
            command = [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "param($scanPath) Start-MpScan -ScanType CustomScan -ScanPath $scanPath",
                path,
            ]
    if command is None:
        return {
            "status": "unavailable",
            "classification": "permanent",
            "detail": "Neither MpCmdRun.exe nor the Defender PowerShell fallback was found.",
        }
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "unavailable",
            "classification": "transient",
            "scanner": scanner,
            "detail": str(exc)[:500],
        }
    if completed.returncode == 0:
        return {
            "status": "passed",
            "classification": "clean",
            "scanner": scanner,
            "detail": "Windows Defender reported no detected threat.",
        }
    detail = (completed.stderr or completed.stdout or f"Defender returned {completed.returncode}").strip()
    if completed.returncode == 2 or any(
        marker in detail.casefold() for marker in ("threat", "malware", "virus", "infected")
    ):
        return {
            "status": "failed",
            "classification": "threat_detected",
            "scanner": scanner,
            "detail": detail[:500],
        }
    return {
        "status": "unavailable",
        "classification": "transient",
        "scanner": scanner,
        "detail": detail[:500],
    }


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
        try:
            from PIL import Image

            with Image.open(path) as image:
                width, height = image.size
        except Exception as exc:
            raise QuarantineError("Image dimensions could not be validated") from exc
        if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION or width * height > MAX_IMAGE_PIXELS:
            raise QuarantineError("Image dimensions exceed the safe decode budget")
        return {"status": "passed", "width": width, "height": height, "pixels": width * height}
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
    env["CML_DEFER_PDF_OCR"] = "1"
    for key in list(env):
        upper = key.upper()
        if upper in {"CML_API_TOKEN", "CML_BRIDGE_TOKEN"}:
            env.pop(key, None)
        elif upper.startswith("CML_") and upper not in {"CML_PARSER_WORKER", "CML_DEFER_PDF_OCR"}:
            env.pop(key, None)
    return env


def _trust_tier(candidate: dict, defender: dict) -> str:
    if defender["status"] == "failed" or (
        defender["status"] == "unavailable" and platform.system().lower() == "windows"
    ):
        return "quarantined"
    return "imported_local"


def _security_labels(candidate: dict, defender: dict) -> list[str]:
    labels = ["local_file", "structurally_validated", "parser_worker"]
    if defender["status"] == "passed":
        labels.append("defender_passed")
    elif defender["status"] == "unavailable":
        labels.append("defender_unavailable")
        if os.environ.get("CML_SANDBOX_ONLY_ALLOW_DEFENDER_UNAVAILABLE", "").strip().lower() in {
            "1", "true", "yes", "on"
        }:
            labels.append("sandbox_only_policy")
    else:
        labels.append("defender_failed")
    if candidate["suffix"] in {".pdf", ".docx"}:
        labels.append("complex_document")
    return labels
