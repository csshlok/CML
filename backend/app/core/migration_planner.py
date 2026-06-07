from pathlib import Path
from uuid import uuid4

from backend.app.core.config import get_settings
from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.core.derived_state import begin_publication, normalize_tuple, query_epoch_snapshot
from backend.app.core.preflight import disk_preflight

DEFAULT_SAFETY_MARGIN_BYTES = 512 * 1024 * 1024
DEFAULT_SIZE_MULTIPLIER = 1.25
DEFAULT_GC_LIMIT = 100
DEFAULT_STALE_AFTER_SECONDS = 60 * 60


class MigrationPlannerError(RuntimeError):
    pass


class MigrationPreflightError(MigrationPlannerError):
    pass


def plan_derived_state_migration(
    vault_id: str,
    target_tuple: dict,
    *,
    safety_margin_bytes: int = DEFAULT_SAFETY_MARGIN_BYTES,
    size_multiplier: float = DEFAULT_SIZE_MULTIPLIER,
) -> dict:
    target = normalize_tuple(target_tuple)
    current = query_epoch_snapshot(
        vault_id,
        embedding_model_id=target["embedding_model_id"],
        index_version=target["index_version"],
    )
    current_size = _current_derived_size(vault_id)
    estimated_new_size = max(1, int(current_size * max(0.1, float(size_multiplier))))
    coexistence_overhead = current_size + estimated_new_size
    required_bytes = coexistence_overhead + max(0, int(safety_margin_bytes))
    check = disk_preflight(str(get_settings().data_dir), required_bytes=required_bytes)
    return {
        "vault_id": vault_id,
        "current_tuple": current,
        "target_tuple": target,
        "current_derived_bytes": current_size,
        "estimated_new_derived_bytes": estimated_new_size,
        "coexistence_overhead_bytes": coexistence_overhead,
        "safety_margin_bytes": max(0, int(safety_margin_bytes)),
        "required_free_bytes": required_bytes,
        "disk_preflight": check,
        "ok": bool(check["ok"]),
    }


def begin_planned_migration(
    vault_id: str,
    target_tuple: dict,
    *,
    safety_margin_bytes: int = DEFAULT_SAFETY_MARGIN_BYTES,
    size_multiplier: float = DEFAULT_SIZE_MULTIPLIER,
) -> dict:
    plan = plan_derived_state_migration(
        vault_id,
        target_tuple,
        safety_margin_bytes=safety_margin_bytes,
        size_multiplier=size_multiplier,
    )
    if not plan["ok"]:
        raise MigrationPreflightError("migration_disk_preflight_failed")
    publication = begin_publication(vault_id, plan["target_tuple"], artifact_manifest={"migration_plan": plan})
    return {"plan": plan, "publication": publication}


def mark_publication_failed(
    publication_id: str,
    *,
    reason: str,
) -> dict:
    now = utc_now()
    with connect() as conn:
        publication = conn.execute(
            "SELECT * FROM derived_state_publications WHERE id = ?",
            (publication_id,),
        ).fetchone()
        if publication is None:
            raise MigrationPlannerError("publication_not_found")
        conn.execute(
            """
            UPDATE derived_state_publications
            SET status = 'failed', artifact_manifest_json = artifact_manifest_json, verified_at = NULL
            WHERE id = ?
            """,
            (publication_id,),
        )
        conn.execute(
            """
            UPDATE derived_state_staged_artifacts
            SET status = 'failed', updated_at = ?
            WHERE publication_id = ? AND status IN ('staging', 'verified')
            """,
            (now, publication_id),
        )
    return {
        "publication_id": publication_id,
        "status": "failed",
        "reason": reason[:500],
        "old_tuple_preserved": True,
    }


def staging_summary(vault_id: str | None = None) -> dict:
    params: list[str] = []
    clause = ""
    if vault_id:
        clause = "WHERE vault_id = ?"
        params.append(vault_id)
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT status, COUNT(*) AS count, COALESCE(SUM(byte_length), 0) AS bytes
            FROM derived_state_staged_artifacts
            {clause}
            GROUP BY status
            """,
            params,
        ).fetchall()
        publications = conn.execute(
            f"""
            SELECT status, COUNT(*) AS count
            FROM derived_state_publications
            {clause}
            GROUP BY status
            """,
            params,
        ).fetchall()
    return {
        "vault_id": vault_id,
        "artifacts": {row["status"]: {"count": int(row["count"]), "bytes": int(row["bytes"])} for row in rows},
        "publications": {row["status"]: int(row["count"]) for row in publications},
    }


def collect_staged_garbage(
    vault_id: str | None = None,
    *,
    limit: int = DEFAULT_GC_LIMIT,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
) -> dict:
    bounded_limit = max(1, min(int(limit), 1000))
    cutoff = _cutoff_iso(stale_after_seconds)
    params: list = []
    vault_clause = ""
    if vault_id:
        vault_clause = "AND vault_id = ?"
        params.append(vault_id)
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM derived_state_staged_artifacts
            WHERE status IN ('failed', 'abandoned', 'deleting')
              {vault_clause}
              AND (heartbeat_at IS NULL OR heartbeat_at = '' OR heartbeat_at < ?)
            ORDER BY updated_at ASC
            LIMIT ?
            """,
            [*params, cutoff, bounded_limit],
        ).fetchall()
        deleted = 0
        bytes_deleted = 0
        retained_live = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM derived_state_staged_artifacts
            WHERE status IN ('staging', 'verified')
              {vault_clause}
              AND heartbeat_at >= ?
            """,
            [*params, cutoff],
        ).fetchone()
        for row in rows:
            artifact = dict_from_row(row)
            _delete_artifact_file_if_safe(artifact["artifact_ref"])
            bytes_deleted += int(artifact["byte_length"] or 0)
            conn.execute("DELETE FROM derived_state_staged_artifacts WHERE id = ?", (artifact["id"],))
            deleted += 1
    return {
        "vault_id": vault_id,
        "deleted_artifacts": deleted,
        "bytes_released_estimate": bytes_deleted,
        "retained_live_artifacts": int(retained_live["count"] if retained_live else 0),
        "limit": bounded_limit,
    }


def _current_derived_size(vault_id: str) -> int:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(LENGTH(text)), 0) AS text_bytes,
                COALESCE(SUM(LENGTH(embedding)), 0) AS embedding_bytes
            FROM source_chunks
            WHERE vault_id = ?
            """,
            (vault_id,),
        ).fetchone()
        encrypted_row = conn.execute(
            """
            SELECT COALESCE(SUM(LENGTH(ciphertext)), 0) AS encrypted_bytes
            FROM encrypted_content
            WHERE vault_id = ? AND entity_type IN ('source_chunk', 'source_page')
            """,
            (vault_id,),
        ).fetchone()
    return int(row["text_bytes"] or 0) + int(row["embedding_bytes"] or 0) + int(encrypted_row["encrypted_bytes"] or 0)


def _cutoff_iso(stale_after_seconds: int) -> str:
    # ISO timestamps compare lexicographically because utc_now() uses a fixed UTC offset.
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) - timedelta(seconds=max(0, int(stale_after_seconds)))).isoformat()


def _delete_artifact_file_if_safe(artifact_ref: str) -> None:
    if not artifact_ref:
        return
    path = Path(artifact_ref)
    if not path.is_absolute():
        return
    try:
        resolved = path.resolve()
        data_dir = get_settings().data_dir.resolve()
        if data_dir not in resolved.parents and resolved != data_dir:
            return
        if resolved.is_file():
            resolved.unlink(missing_ok=True)
    except OSError:
        return


def new_staging_ref(vault_id: str, artifact_type: str) -> str:
    safe_type = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in artifact_type)[:80]
    return str(get_settings().data_dir / "staging" / vault_id / safe_type / f"{uuid4()}.stage")
