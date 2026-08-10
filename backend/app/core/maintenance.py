from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from typing import Any

from backend.app.core.database import connect, utc_now


@dataclass(frozen=True)
class RetentionPolicy:
    name: str
    table: str
    timestamp_column: str
    retention_days: int
    predicate: str
    cutoff_parameters: int = 1


# Every predicate is static application SQL. Active/retriable work is
# deliberately absent, and every scheduled pass deletes at most one batch per
# policy so maintenance cannot monopolize SQLite.
RETENTION_POLICIES = (
    RetentionPolicy(
        "jobs_terminal",
        "app_jobs",
        "updated_at",
        30,
        "status IN ('succeeded', 'cancelled', 'partial_success') AND updated_at < ?",
    ),
    RetentionPolicy(
        "jobs_diagnostics",
        "app_jobs",
        "updated_at",
        90,
        "status IN ('failed', 'manual_review') AND updated_at < ?",
    ),
    RetentionPolicy(
        "chat_generations_terminal",
        "chat_generations",
        "updated_at",
        30,
        "state IN ('completed', 'stopped') AND updated_at < ?",
    ),
    RetentionPolicy(
        "retrieval_snapshots",
        "retrieval_snapshots",
        "created_at",
        90,
        "created_at < ?",
    ),
    RetentionPolicy(
        "query_cache_invalidated",
        "query_evidence_cache",
        "updated_at",
        7,
        "invalidated_at IS NOT NULL AND updated_at < ?",
    ),
    RetentionPolicy(
        "query_cache_stale",
        "query_evidence_cache",
        "updated_at",
        30,
        "updated_at < ?",
    ),
    RetentionPolicy(
        "cli_sessions",
        "cli_sessions",
        "expires_at",
        7,
        "(expires_at < ? OR (revoked_at IS NOT NULL AND revoked_at < ?))",
        cutoff_parameters=2,
    ),
    RetentionPolicy(
        "cli_pairing_challenges",
        "cli_pairing_challenges",
        "expires_at",
        7,
        "expires_at < ? AND status != 'pending'",
    ),
    RetentionPolicy("vault_lock_audit", "vault_lock_audit", "created_at", 180, "created_at < ?"),
    RetentionPolicy("bridge_audit", "bridge_audit_events", "created_at", 180, "created_at < ?"),
    RetentionPolicy("cli_auth_audit", "cli_auth_audit", "created_at", 180, "created_at < ?"),
    RetentionPolicy(
        "extension_permission_audit",
        "extension_permission_audit",
        "created_at",
        180,
        "created_at < ?",
    ),
)


def run_maintenance(
    *,
    dry_run: bool = False,
    batch_size: int = 500,
    now: datetime | None = None,
    connection=None,
) -> dict[str, Any]:
    bounded_batch = max(1, min(int(batch_size), 5_000))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if connection is not None:
        return _run_with_connection(
            connection,
            dry_run=dry_run,
            batch_size=bounded_batch,
            now=current,
            record_state=False,
        )
    with connect() as conn:
        return _run_with_connection(
            conn,
            dry_run=dry_run,
            batch_size=bounded_batch,
            now=current,
            record_state=not dry_run,
        )


def run_maintenance_if_due(*, interval_hours: int = 6, batch_size: int = 500) -> dict[str, Any] | None:
    now = datetime.now(timezone.utc)
    with connect() as conn:
        _ensure_state_table(conn)
        row = conn.execute(
            "SELECT last_completed_at, status, updated_at FROM maintenance_state WHERE id = 'default'"
        ).fetchone()
        if row is not None:
            last_completed = _parse_timestamp(row["last_completed_at"])
            running_since = _parse_timestamp(row["updated_at"])
            if last_completed is not None and last_completed > now - timedelta(hours=max(1, interval_hours)):
                return None
            if row["status"] == "running" and running_since is not None and running_since > now - timedelta(hours=1):
                return None
        return _run_with_connection(
            conn,
            dry_run=False,
            batch_size=max(1, min(int(batch_size), 5_000)),
            now=now,
            record_state=True,
        )


def _run_with_connection(
    conn,
    *,
    dry_run: bool,
    batch_size: int,
    now: datetime,
    record_state: bool,
) -> dict[str, Any]:
    started_at = _iso(now)
    if record_state:
        _ensure_state_table(conn)
        conn.execute(
            """
            INSERT INTO maintenance_state (id, last_started_at, status, updated_at)
            VALUES ('default', ?, 'running', ?)
            ON CONFLICT(id) DO UPDATE SET
                last_started_at = excluded.last_started_at,
                status = 'running', updated_at = excluded.updated_at
            """,
            (started_at, started_at),
        )

    results: dict[str, dict[str, Any]] = {}
    total = 0
    try:
        for policy in RETENTION_POLICIES:
            if not _table_exists(conn, policy.table):
                results[policy.name] = {"eligible": 0, "deleted": 0, "skipped": "table_missing"}
                continue
            cutoff = _iso(now - timedelta(days=policy.retention_days))
            parameters: list[Any] = [cutoff] * policy.cutoff_parameters
            rows = conn.execute(
                f"SELECT rowid FROM {policy.table} WHERE {policy.predicate} "
                f"ORDER BY {policy.timestamp_column}, rowid LIMIT ?",
                [*parameters, batch_size],
            ).fetchall()
            rowids = [int(row["rowid"]) for row in rows]
            deleted = 0
            if rowids and not dry_run:
                placeholders = ",".join("?" for _ in rowids)
                deleted = int(
                    conn.execute(
                        f"DELETE FROM {policy.table} WHERE rowid IN ({placeholders})",
                        rowids,
                    ).rowcount
                )
            results[policy.name] = {
                "eligible": len(rowids),
                "deleted": deleted,
                "retention_days": policy.retention_days,
                "batch_limited": len(rowids) == batch_size,
            }
            total += deleted
        if _table_exists(conn, "source_quarantine_records"):
            from backend.app.core.quarantine import prune_unattached_quarantine_artifacts

            quarantine = prune_unattached_quarantine_artifacts(
                conn,
                passed_cutoff=_iso(now - timedelta(days=30)),
                failed_cutoff=_iso(now - timedelta(days=90)),
                limit=batch_size,
                dry_run=dry_run,
            )
            results["quarantine_artifacts"] = quarantine
            total += int(quarantine.get("deleted") or 0)
        if _table_exists(conn, "source_chunks"):
            from backend.app.core.vector_maintenance import prune_unreferenced_vector_chunks

            vectors = prune_unreferenced_vector_chunks(
                conn,
                cutoff=_iso(now - timedelta(days=30)),
                limit=batch_size,
                dry_run=dry_run,
            )
            results["unreferenced_vector_chunks"] = vectors
            total += int(vectors.get("deleted") or 0)
        if _table_exists(conn, "vaults"):
            from backend.app.core.turbovec_runtime import prune_turbovec_sidecar_epochs

            sidecars = prune_turbovec_sidecar_epochs(
                conn,
                cutoff_timestamp=(now - timedelta(days=7)).timestamp(),
                limit=min(batch_size, 25),
                dry_run=dry_run,
            )
            results["unreferenced_vector_sidecars"] = sidecars
            total += int(sidecars.get("deleted") or 0)
    except Exception as exc:
        if record_state:
            failed_at = utc_now()
            conn.execute(
                """
                UPDATE maintenance_state
                SET status = 'failed', last_report_json = ?, updated_at = ?
                WHERE id = 'default'
                """,
                (json.dumps({"error": str(exc)[:500], "policies": results}), failed_at),
            )
        raise

    report = {
        "dry_run": dry_run,
        "batch_size": batch_size,
        "deleted": total,
        "policies": results,
        "started_at": started_at,
        "completed_at": utc_now(),
        "vacuum_run": False,
    }
    if record_state:
        conn.execute(
            """
            UPDATE maintenance_state
            SET last_completed_at = ?, status = 'succeeded', last_report_json = ?, updated_at = ?
            WHERE id = 'default'
            """,
            (report["completed_at"], json.dumps(report, separators=(",", ":")), report["completed_at"]),
        )
    return report


def _ensure_state_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS maintenance_state (
            id TEXT PRIMARY KEY CHECK (id = 'default'),
            last_started_at TEXT,
            last_completed_at TEXT,
            status TEXT NOT NULL DEFAULT 'never_run',
            last_report_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        )
        """
    )


def _table_exists(conn, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
