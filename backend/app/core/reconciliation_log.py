from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

from backend.app.core.bridge_security import load_secure_json, now_utc, store_secure_json
from backend.app.core.database import dict_from_row, utc_now

RUN_RETENTION_DAYS = 30
RUN_ROW_CAP = 1000
ITEM_ROW_CAP_PER_RUN = 2000


def create_reconciliation_run(
    conn,
    *,
    vault_id: str,
    import_id: str,
    trigger_source: str,
    root_path: str,
    import_files: bool,
    tombstone_missing: bool,
) -> str:
    run_id = f"reconcile-run-{uuid4()}"
    now = utc_now()
    conn.execute(
        """
        INSERT INTO reconciliation_runs (
            id, vault_id, import_id, trigger_source, root_path, status, import_files,
            tombstone_missing, imported_count, updated_count, moved_count, unchanged_count,
            tombstoned_count, failed_count, retryable_failed_count, detail_count,
            started_at, finished_at, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, 'running', ?, ?, 0, 0, 0, 0, 0, 0, 0, 0, ?, NULL, ?, ?)
        """,
        (
            run_id,
            vault_id,
            import_id,
            trigger_source,
            root_path,
            1 if import_files else 0,
            1 if tombstone_missing else 0,
            now,
            now,
            now,
        ),
    )
    return run_id


def append_reconciliation_item(
    conn,
    *,
    run_id: str,
    vault_id: str,
    import_id: str,
    item_reference: str,
    action: str,
    result: str,
    error: str = "",
    retryable: bool = False,
    detail: dict[str, Any] | None = None,
) -> str:
    item_id = f"reconcile-item-{uuid4()}"
    now = utc_now()
    detail_json = store_secure_json(
        conn,
        vault_id=vault_id,
        entity_type="reconciliation_item",
        entity_id=item_id,
        field_name="detail_json",
        payload=detail or {},
        now=now,
    )
    conn.execute(
        """
        INSERT INTO reconciliation_items (
            id, run_id, vault_id, import_id, item_reference, action, result,
            error, retryable, detail_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item_id,
            run_id,
            vault_id,
            import_id,
            item_reference,
            action,
            result,
            error[:1000],
            1 if retryable else 0,
            detail_json,
            now,
            now,
        ),
    )
    conn.execute(
        """
        UPDATE reconciliation_runs
        SET detail_count = detail_count + 1,
            retryable_failed_count = retryable_failed_count + ?,
            updated_at = ?
        WHERE id = ?
        """,
        (1 if retryable and result == "failed" else 0, now, run_id),
    )
    return item_id


def finish_reconciliation_run(
    conn,
    *,
    run_id: str,
    status: str,
    counts: dict[str, int],
) -> None:
    now = utc_now()
    conn.execute(
        """
        UPDATE reconciliation_runs
        SET status = ?,
            imported_count = ?,
            updated_count = ?,
            moved_count = ?,
            unchanged_count = ?,
            tombstoned_count = ?,
            failed_count = ?,
            finished_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            status,
            int(counts.get("imported_count") or 0),
            int(counts.get("updated_count") or 0),
            int(counts.get("moved_count") or 0),
            int(counts.get("unchanged_count") or 0),
            int(counts.get("tombstoned_count") or 0),
            int(counts.get("failed_count") or 0),
            now,
            now,
            run_id,
        ),
    )


def list_reconciliation_runs(conn, *, import_id: str, limit: int = 10) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM reconciliation_runs
        WHERE import_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (import_id, max(1, min(limit, 100))),
    ).fetchall()
    return [run_from_row(row) for row in rows]


def list_reconciliation_items(
    conn,
    *,
    run_id: str,
    limit: int = 50,
    offset: int = 0,
    result: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    params: list[Any] = [run_id]
    where = "WHERE run_id = ?"
    if result:
        where += " AND result = ?"
        params.append(result)
    count_row = conn.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM reconciliation_items
        {where}
        """,
        tuple(params),
    ).fetchone()
    params.extend([max(1, min(limit, 200)), max(offset, 0)])
    rows = conn.execute(
        f"""
        SELECT *
        FROM reconciliation_items
        {where}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params),
    ).fetchall()
    return [item_from_row(conn, row) for row in rows], int(count_row["count"] or 0)


def load_reconciliation_item(conn, item_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM reconciliation_items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        return None
    return item_from_row(conn, row)


def compact_reconciliation_logs(conn) -> None:
    run_cutoff = (now_utc() - timedelta(days=RUN_RETENTION_DAYS)).isoformat()
    old_run_rows = conn.execute(
        "SELECT id FROM reconciliation_runs WHERE created_at < ?",
        (run_cutoff,),
    ).fetchall()
    old_run_ids = [row["id"] for row in old_run_rows]
    if old_run_ids:
        _delete_reconciliation_encrypted_rows(conn, run_ids=old_run_ids)
        conn.executemany("DELETE FROM reconciliation_runs WHERE id = ?", [(run_id,) for run_id in old_run_ids])

    count_row = conn.execute("SELECT COUNT(*) AS count FROM reconciliation_runs").fetchone()
    excess_runs = max(0, int(count_row["count"] or 0) - RUN_ROW_CAP)
    if excess_runs > 0:
        rows = conn.execute(
            """
            SELECT id
            FROM reconciliation_runs
            ORDER BY created_at DESC
            LIMIT -1 OFFSET ?
            """,
            (RUN_ROW_CAP,),
        ).fetchall()
        extra_run_ids = [row["id"] for row in rows]
        if extra_run_ids:
            _delete_reconciliation_encrypted_rows(conn, run_ids=extra_run_ids)
            conn.executemany("DELETE FROM reconciliation_runs WHERE id = ?", [(run_id,) for run_id in extra_run_ids])

    run_rows = conn.execute("SELECT id FROM reconciliation_runs").fetchall()
    for row in run_rows:
        run_id = row["id"]
        count = conn.execute(
            "SELECT COUNT(*) AS count FROM reconciliation_items WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if int(count["count"] or 0) <= ITEM_ROW_CAP_PER_RUN:
            continue
        rows = conn.execute(
            """
            SELECT id
            FROM reconciliation_items
            WHERE run_id = ?
            ORDER BY created_at DESC
            LIMIT -1 OFFSET ?
            """,
            (run_id, ITEM_ROW_CAP_PER_RUN),
        ).fetchall()
        item_ids = [entry["id"] for entry in rows]
        if item_ids:
            _delete_reconciliation_encrypted_rows(conn, item_ids=item_ids)
            conn.executemany("DELETE FROM reconciliation_items WHERE id = ?", [(item_id,) for item_id in item_ids])


def run_from_row(row) -> dict[str, Any]:
    record = dict_from_row(row)
    record["import_files"] = bool(record["import_files"])
    record["tombstone_missing"] = bool(record["tombstone_missing"])
    return record


def item_from_row(conn, row) -> dict[str, Any]:
    record = dict_from_row(row)
    record["retryable"] = bool(record["retryable"])
    record["detail"] = load_secure_json(
        conn,
        vault_id=record["vault_id"],
        entity_type="reconciliation_item",
        entity_id=record["id"],
        field_name="detail_json",
        fallback_text=record.get("detail_json"),
    )
    return record


def _delete_reconciliation_encrypted_rows(
    conn,
    *,
    run_ids: list[str] | None = None,
    item_ids: list[str] | None = None,
) -> None:
    item_refs = list(item_ids or [])
    if run_ids:
        rows = conn.execute(
            f"""
            SELECT id
            FROM reconciliation_items
            WHERE run_id IN ({",".join("?" for _ in run_ids)})
            """,
            tuple(run_ids),
        ).fetchall()
        item_refs.extend(row["id"] for row in rows)
    if not item_refs:
        return
    conn.executemany(
        """
        DELETE FROM encrypted_content
        WHERE entity_type = 'reconciliation_item'
          AND entity_id = ?
          AND field_name = 'detail_json'
        """,
        [(item_id,) for item_id in item_refs],
    )
