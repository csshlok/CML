from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from backend.app.core.config import get_settings
from backend.app.core.database import connect, utc_now

ScanType = Literal["antivirus", "full"]


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _future_timestamp(days: int, *, from_value: str | None = None) -> str:
    base = _parse_timestamp(from_value) or datetime.now(UTC)
    return (base + timedelta(days=days)).isoformat().replace("+00:00", "Z")


def _ensure_settings_row(conn) -> None:
    now = utc_now()
    conn.execute(
        """
        INSERT OR IGNORE INTO security_scan_settings (
            id, enabled, interval_days, next_run_at, created_at, updated_at
        ) VALUES ('default', 1, 30, ?, ?, ?)
        """,
        (_future_timestamp(30, from_value=now), now, now),
    )


def security_scan_status() -> dict:
    with connect() as conn:
        _ensure_settings_row(conn)
        row = conn.execute(
            "SELECT * FROM security_scan_settings WHERE id = 'default'"
        ).fetchone()
        active = conn.execute(
            """
            SELECT id, status, status_detail, created_at, started_at
            FROM app_jobs
            WHERE job_type = 'security_scan' AND status IN ('queued', 'running')
            ORDER BY created_at DESC LIMIT 1
            """
        ).fetchone()
    summary = {}
    try:
        summary = json.loads(row["last_summary_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        summary = {}
    return {
        "enabled": bool(row["enabled"]),
        "interval_days": int(row["interval_days"]),
        "last_started_at": row["last_started_at"],
        "last_completed_at": row["last_completed_at"],
        "last_scan_type": row["last_scan_type"],
        "last_status": row["last_status"],
        "last_summary": summary,
        "next_run_at": row["next_run_at"] if row["enabled"] else None,
        "active_job": dict(active) if active is not None else None,
    }


def update_security_scan_schedule(*, enabled: bool | None, interval_days: int | None) -> dict:
    with connect() as conn:
        _ensure_settings_row(conn)
        row = conn.execute(
            "SELECT * FROM security_scan_settings WHERE id = 'default'"
        ).fetchone()
        next_enabled = bool(row["enabled"]) if enabled is None else enabled
        next_interval = int(row["interval_days"]) if interval_days is None else interval_days
        anchor = row["last_completed_at"] if row["last_scan_type"] == "full" else None
        next_run = _future_timestamp(next_interval, from_value=anchor) if next_enabled else None
        conn.execute(
            """
            UPDATE security_scan_settings
            SET enabled = ?, interval_days = ?, next_run_at = ?, updated_at = ?
            WHERE id = 'default'
            """,
            (int(next_enabled), next_interval, next_run, utc_now()),
        )
    return security_scan_status()


def enqueue_due_security_scan() -> dict | None:
    from backend.app.core.background_jobs import enqueue_job

    with connect() as conn:
        _ensure_settings_row(conn)
        row = conn.execute(
            "SELECT * FROM security_scan_settings WHERE id = 'default'"
        ).fetchone()
        due = _parse_timestamp(row["next_run_at"])
        if not row["enabled"] or due is None or due > datetime.now(UTC):
            return None
        active = conn.execute(
            """
            SELECT id FROM app_jobs
            WHERE dedupe_key = 'security-scan:active'
              AND status IN ('queued', 'running', 'paused', 'blocked_by_dependency', 'blocked_setup_required', 'deferred')
            LIMIT 1
            """
        ).fetchone()
        if active is not None:
            return None
        job = enqueue_job(
            conn,
            job_type="security_scan",
            payload={"scan_type": "full", "trigger": "scheduled"},
            dedupe_key="security-scan:active",
            user_initiated=False,
        )
        return job


def execute_security_scan(scan_type: ScanType, *, trigger: str = "manual") -> dict:
    started_at = utc_now()
    with connect() as conn:
        _ensure_settings_row(conn)
        row = conn.execute(
            "SELECT enabled, interval_days FROM security_scan_settings WHERE id = 'default'"
        ).fetchone()
        next_run = (
            _future_timestamp(int(row["interval_days"]), from_value=started_at)
            if trigger == "scheduled" and row["enabled"]
            else None
        )
        conn.execute(
            """
            UPDATE security_scan_settings
            SET last_started_at = ?, last_scan_type = ?, last_status = 'running',
                next_run_at = CASE WHEN ? IS NULL THEN next_run_at ELSE ? END,
                updated_at = ?
            WHERE id = 'default'
            """,
            (started_at, scan_type, next_run, next_run, started_at),
        )

    antivirus = _run_antivirus_scan()
    checks = [antivirus]
    if scan_type == "full":
        checks.extend(_application_security_checks())

    if any(check["status"] == "failed" for check in checks):
        status = "failed"
    elif any(check["status"] in {"attention", "unavailable"} for check in checks):
        status = "attention"
    else:
        status = "passed"
    completed_at = utc_now()
    summary = {
        "scan_type": scan_type,
        "trigger": trigger,
        "status": status,
        "checks": checks,
        "started_at": started_at,
        "completed_at": completed_at,
    }
    with connect() as conn:
        _ensure_settings_row(conn)
        row = conn.execute(
            "SELECT enabled, interval_days FROM security_scan_settings WHERE id = 'default'"
        ).fetchone()
        next_run = (
            _future_timestamp(int(row["interval_days"]), from_value=completed_at)
            if scan_type == "full" and row["enabled"]
            else None
        )
        conn.execute(
            """
            UPDATE security_scan_settings
            SET last_completed_at = ?, last_scan_type = ?, last_status = ?,
                last_summary_json = ?,
                next_run_at = CASE WHEN ? IS NULL THEN next_run_at ELSE ? END,
                updated_at = ?
            WHERE id = 'default'
            """,
            (completed_at, scan_type, status, json.dumps(summary), next_run, next_run, completed_at),
        )
    return summary


def record_security_scan_failure(scan_type: ScanType, *, trigger: str = "manual") -> None:
    completed_at = utc_now()
    summary = {
        "scan_type": scan_type,
        "trigger": trigger,
        "status": "failed",
        "checks": [{
            "id": "scan_runtime",
            "label": "Security scan runtime",
            "status": "failed",
            "detail": "The scan stopped unexpectedly. Retry it or export diagnostics for support.",
        }],
        "completed_at": completed_at,
    }
    with connect() as conn:
        _ensure_settings_row(conn)
        conn.execute(
            """
            UPDATE security_scan_settings
            SET last_completed_at = ?, last_scan_type = ?, last_status = 'failed',
                last_summary_json = ?, updated_at = ?
            WHERE id = 'default'
            """,
            (completed_at, scan_type, json.dumps(summary), completed_at),
        )


def _defender_executable() -> str | None:
    direct = shutil.which("MpCmdRun.exe") or shutil.which("MpCmdRun")
    if direct:
        return direct
    candidates = []
    program_data = os.environ.get("ProgramData")
    program_files = os.environ.get("ProgramFiles")
    if program_data:
        platform = Path(program_data) / "Microsoft" / "Windows Defender" / "Platform"
        if platform.exists():
            candidates.extend(sorted(platform.glob("*/MpCmdRun.exe"), reverse=True))
    if program_files:
        candidates.append(Path(program_files) / "Windows Defender" / "MpCmdRun.exe")
    return next((str(path) for path in candidates if path.is_file()), None)


def _scan_targets() -> list[Path]:
    settings = get_settings()
    targets = [settings.data_dir.resolve()]
    with connect() as conn:
        rows = conn.execute("SELECT path FROM vaults WHERE deleted_at IS NULL").fetchall()
    for row in rows:
        path = Path(str(row["path"] or "")).expanduser()
        if path.exists():
            resolved = path.resolve()
            if resolved not in targets:
                targets.append(resolved)
    return targets


def _run_antivirus_scan() -> dict:
    if os.name != "nt":
        return {
            "id": "antivirus",
            "label": "Microsoft Defender antivirus",
            "status": "unavailable",
            "detail": "Microsoft Defender scanning is available in the installed Windows app.",
        }
    executable = _defender_executable()
    if not executable:
        return {
            "id": "antivirus",
            "label": "Microsoft Defender antivirus",
            "status": "unavailable",
            "detail": "Microsoft Defender command-line scanning is unavailable or disabled.",
        }
    targets = _scan_targets()
    scanned = 0
    for target in targets:
        try:
            result = subprocess.run(
                [executable, "-Scan", "-ScanType", "3", "-File", str(target)],
                capture_output=True,
                text=True,
                timeout=60 * 60,
                check=False,
                creationflags=(
                    getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
                ),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                "id": "antivirus",
                "label": "Microsoft Defender antivirus",
                "status": "failed",
                "detail": f"The antivirus scan could not finish ({type(exc).__name__}).",
            }
        scanned += 1
        if result.returncode != 0:
            return {
                "id": "antivirus",
                "label": "Microsoft Defender antivirus",
                "status": "attention",
                "detail": "Defender reported a detection or scan error. Open Windows Security for details and remediation.",
                "exit_code": result.returncode,
            }
    return {
        "id": "antivirus",
        "label": "Microsoft Defender antivirus",
        "status": "passed",
        "detail": f"Defender completed custom scans for {scanned} vault location{'s' if scanned != 1 else ''}.",
    }


def _application_security_checks() -> list[dict]:
    checks: list[dict] = []
    try:
        with connect() as conn:
            quick = [str(row[0]) for row in conn.execute("PRAGMA quick_check").fetchall()]
            foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchmany(25)
            secured_plaintext = _secured_plaintext_count(conn)
            unsafe_clients = _unsafe_client_scope_count(conn)
        checks.append({
            "id": "database_integrity",
            "label": "Vault database integrity",
            "status": "passed" if quick == ["ok"] and not foreign_keys else "failed",
            "detail": "Database and reference integrity checks passed." if quick == ["ok"] and not foreign_keys else "Database integrity needs repair.",
        })
        checks.append({
            "id": "encrypted_storage",
            "label": "Protected-content storage",
            "status": "passed" if secured_plaintext == 0 else "failed",
            "detail": "No protected Bridge content was found in plaintext." if secured_plaintext == 0 else f"Found {secured_plaintext} protected Bridge record(s) requiring secure-storage repair.",
            "affected_records": secured_plaintext,
        })
        checks.append({
            "id": "client_scopes",
            "label": "Connection access scopes",
            "status": "passed" if unsafe_clients == 0 else "attention",
            "detail": "Enabled connections have explicit library or cluster scopes." if unsafe_clients == 0 else f"Found {unsafe_clients} enabled connection(s) without an explicit scope.",
            "affected_clients": unsafe_clients,
        })
    except sqlite3.Error:
        checks.append({
            "id": "application_security",
            "label": "Vault security invariants",
            "status": "failed",
            "detail": "Vault could not complete its database security checks.",
        })
    return checks


def _table_exists(conn, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def _secured_plaintext_count(conn) -> int:
    if not _table_exists(conn, "vault_security_metadata"):
        return 0
    total = 0
    if _table_exists(conn, "bridge_context_packets"):
        row = conn.execute(
            """
            SELECT COUNT(*) FROM bridge_context_packets
            WHERE vault_id IN (SELECT vault_id FROM vault_security_metadata)
              AND (TRIM(COALESCE(query, '')) <> '' OR TRIM(COALESCE(packet_text, '')) <> '')
            """
        ).fetchone()
        total += int(row[0])
    if _table_exists(conn, "bridge_requests"):
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(bridge_requests)")}
        if "vault_id" in columns:
            row = conn.execute(
                """
                SELECT COUNT(*) FROM bridge_requests
                WHERE vault_id IN (SELECT vault_id FROM vault_security_metadata)
                  AND TRIM(COALESCE(query, '')) <> ''
                """
            ).fetchone()
            total += int(row[0])
    return total


def _unsafe_client_scope_count(conn) -> int:
    total = 0
    if _table_exists(conn, "extension_clients"):
        total += int(conn.execute(
            """SELECT COUNT(*) FROM extension_clients
               WHERE enabled = 1 AND TRIM(COALESCE(allowed_vault_ids, '[]')) = '[]'"""
        ).fetchone()[0])
    if _table_exists(conn, "bridge_clients"):
        total += int(conn.execute(
            """SELECT COUNT(*) FROM bridge_clients
               WHERE enabled = 1
                 AND TRIM(COALESCE(allowed_vault_ids, '[]')) = '[]'
                 AND TRIM(COALESCE(allowed_cluster_ids, '[]')) = '[]'"""
        ).fetchone()[0])
    return total
