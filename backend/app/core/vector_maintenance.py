import json
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.core.derived_state import query_epoch_snapshot_conn
from backend.app.core.embeddings import active_embedding_model_id, reindex_source_chunks
from backend.app.core.encrypted_storage import delete_encrypted_entity


ACTIVE_INDEX_VERSION = "v1"


class EmbeddingIndexNotReady(RuntimeError):
    def __init__(self, *, model_id: str, index_version: str, required_sources: int, ready_sources: int):
        self.model_id = model_id
        self.index_version = index_version
        self.required_sources = required_sources
        self.ready_sources = ready_sources
        super().__init__(
            f"embedding_index_not_ready:{ready_sources}/{required_sources}:"
            f"{model_id}:{index_version}"
        )


def embedding_index_policy() -> dict:
    path = _index_policy_path()
    payload = {
        "active_embedding_model_id": active_embedding_model_id(),
        "active_index_version": ACTIVE_INDEX_VERSION,
        "building_embedding_model_id": None,
        "building_index_version": None,
        "previous_embedding_model_id": None,
        "previous_index_version": None,
        "transition_state": "active",
        "updated_at": None,
    }
    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            saved = {}
        if isinstance(saved, dict):
            payload.update({key: saved.get(key, value) for key, value in payload.items()})
    if not payload["updated_at"]:
        payload["updated_at"] = utc_now()
    return payload


def active_embedding_selector() -> dict:
    policy = embedding_index_policy()
    return {
        "embedding_model_id": str(policy["active_embedding_model_id"]),
        "index_version": str(policy["active_index_version"]),
    }


def begin_embedding_index_transition(
    model_id: str,
    index_version: str = ACTIVE_INDEX_VERSION,
) -> dict:
    payload = embedding_index_policy()
    if (
        str(payload.get("active_embedding_model_id") or "") == model_id
        and str(payload.get("active_index_version") or ACTIVE_INDEX_VERSION) == index_version
    ):
        return payload
    payload.update(
        {
            "building_embedding_model_id": model_id,
            "building_index_version": index_version,
            "transition_state": "building",
            "updated_at": utc_now(),
        }
    )
    _write_index_policy(payload)
    return payload


def activate_embedding_index(model_id: str, index_version: str = ACTIVE_INDEX_VERSION) -> dict:
    readiness = embedding_index_readiness(model_id, index_version)
    if readiness["ready_sources"] < readiness["required_sources"]:
        raise EmbeddingIndexNotReady(
            model_id=model_id,
            index_version=index_version,
            required_sources=readiness["required_sources"],
            ready_sources=readiness["ready_sources"],
        )
    payload = embedding_index_policy()
    active_model = str(payload.get("active_embedding_model_id") or "")
    active_version = str(payload.get("active_index_version") or ACTIVE_INDEX_VERSION)
    payload.update(
        {
            "previous_embedding_model_id": active_model if active_model != model_id else payload.get("previous_embedding_model_id"),
            "previous_index_version": active_version if active_version != index_version else payload.get("previous_index_version"),
            "active_embedding_model_id": model_id,
            "active_index_version": index_version,
            "building_embedding_model_id": None,
            "building_index_version": None,
            "transition_state": "active",
            "updated_at": utc_now(),
        }
    )
    _write_index_policy(payload)
    return payload


def embedding_index_readiness(model_id: str, index_version: str = ACTIVE_INDEX_VERSION) -> dict:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS required_sources,
                COALESCE(SUM(CASE WHEN EXISTS (
                    SELECT 1 FROM source_chunks target
                    WHERE target.source_id = searchable.source_id
                      AND target.activation_state = 'active'
                      AND target.embedding_model_id = ?
                      AND target.index_version = ?
                      AND target.embedding <> ''
                ) THEN 1 ELSE 0 END), 0) AS ready_sources
            FROM (
                SELECT DISTINCT sources.id AS source_id
                FROM sources
                JOIN source_chunks active ON active.source_id = sources.id
                WHERE sources.deleted_at IS NULL
                  AND sources.state = 'indexed'
                  AND sources.activation_state = 'active'
                  AND active.activation_state = 'active'
            ) searchable
            """,
            (model_id, index_version),
        ).fetchone()
    return {
        "model_id": model_id,
        "index_version": index_version,
        "required_sources": int(row["required_sources"] or 0),
        "ready_sources": int(row["ready_sources"] or 0),
        "ready": int(row["ready_sources"] or 0) >= int(row["required_sources"] or 0),
    }


def vector_repair_plan(vault_id: str | None = None) -> dict:
    params: list[str] = []
    vault_clause = ""
    if vault_id:
        vault_clause = "AND sources.vault_id = ?"
        params.append(vault_id)
    policy = embedding_index_policy()
    transition_building = policy.get("transition_state") == "building" and bool(
        policy.get("building_embedding_model_id")
    )
    active_model = (
        policy["building_embedding_model_id"]
        if transition_building
        else policy["active_embedding_model_id"]
    )
    target_index_version = str(
        policy.get("building_index_version") or policy.get("active_index_version") or ACTIVE_INDEX_VERSION
    )
    with connect() as conn:
        tuple_stale_clause = ""
        tuple_params: list = []
        if vault_id:
            tuple_snapshot = query_epoch_snapshot_conn(
                conn,
                vault_id,
                embedding_model_id=str(active_model),
                index_version=target_index_version,
            )
            tuple_stale_clause = """
                OR chunks.normalization_version != ?
                OR chunks.extraction_version != ?
                OR chunks.derived_state_epoch != ?
            """
            tuple_params = [
                tuple_snapshot["normalization_version"],
                tuple_snapshot["extraction_version"],
                tuple_snapshot["epoch"],
            ]
        missing_rows = conn.execute(
            f"""
            SELECT sources.id
            FROM sources
            WHERE sources.state = 'indexed'
              AND sources.deleted_at IS NULL
              AND sources.activation_state = 'active'
              {vault_clause}
              AND NOT EXISTS (
                SELECT 1 FROM source_chunks chunks WHERE chunks.source_id = sources.id
              )
            ORDER BY sources.updated_at DESC
            """,
            params,
        ).fetchall()
        if transition_building:
            stale_rows = conn.execute(
                f"""
                SELECT sources.id
                FROM sources
                WHERE sources.deleted_at IS NULL
                  AND sources.state = 'indexed'
                  AND sources.activation_state = 'active'
                  {vault_clause}
                  AND EXISTS (
                    SELECT 1 FROM source_chunks current
                    WHERE current.source_id = sources.id AND current.activation_state = 'active'
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM source_chunks target
                    WHERE target.source_id = sources.id
                      AND target.activation_state = 'active'
                      AND target.embedding_model_id = ?
                      AND target.index_version = ?
                      AND target.embedding <> ''
                      AND target.indexed_at IS NOT NULL
                  )
                ORDER BY sources.updated_at DESC
                """,
                [*params, active_model, target_index_version],
            ).fetchall()
        else:
            stale_rows = conn.execute(
                f"""
                SELECT DISTINCT sources.id
                FROM sources
                JOIN source_chunks chunks ON chunks.source_id = sources.id
                WHERE sources.deleted_at IS NULL
                  AND sources.state = 'indexed'
                  AND sources.activation_state = 'active'
                  AND chunks.activation_state = 'active'
                  {vault_clause}
                  AND (
                    chunks.embedding = ''
                    OR chunks.indexed_at IS NULL
                    OR chunks.embedding_model_id != ?
                    OR chunks.index_version != ?
                    {tuple_stale_clause}
                  )
                ORDER BY sources.updated_at DESC
                """,
                [*params, active_model, target_index_version, *tuple_params],
            ).fetchall()
        orphan_chunks = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM source_chunks chunks
            LEFT JOIN sources ON sources.id = chunks.source_id
            WHERE sources.id IS NULL OR sources.deleted_at IS NOT NULL
            """
        ).fetchone()
    missing = [row["id"] for row in missing_rows]
    stale = [row["id"] for row in stale_rows if row["id"] not in missing]
    return {
        "vault_id": vault_id,
        "active_embedding_model_id": active_model,
        "active_index_version": target_index_version,
        "transition_state": "building" if transition_building else "active",
        "missing_vector_source_ids": missing,
        "stale_vector_source_ids": stale,
        "orphan_chunk_count": int(orphan_chunks["count"] if orphan_chunks else 0),
        "repair_source_count": len(missing) + len(stale),
        "compaction_recommended": int(orphan_chunks["count"] if orphan_chunks else 0) > 0,
    }


def repair_vectors(vault_id: str | None = None, *, limit: int = 100) -> dict:
    plan = vector_repair_plan(vault_id)
    if plan.get("transition_state") == "building":
        runtime_model = active_embedding_model_id()
        if runtime_model != plan["active_embedding_model_id"]:
            raise RuntimeError(
                "embedding_transition_runtime_mismatch: configure the building model before repair"
            )
    source_ids = [*plan["missing_vector_source_ids"], *plan["stale_vector_source_ids"]][:limit]
    chunks_indexed = 0
    repaired = 0
    for source_id in source_ids:
        with connect() as conn:
            row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
            if row is None:
                continue
            chunks_indexed += reindex_source_chunks(conn, dict_from_row(row))
            repaired += 1
    return {
        "vault_id": vault_id,
        "sources_repaired": repaired,
        "chunks_indexed": chunks_indexed,
        "remaining_repair_source_count": max(0, plan["repair_source_count"] - repaired),
    }


def compact_vectors(vault_id: str | None = None) -> dict:
    params: list[str] = []
    vault_clause = ""
    if vault_id:
        vault_clause = "AND chunks.vault_id = ?"
        params.append(vault_id)
    with connect() as conn:
        before = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM source_chunks chunks
            LEFT JOIN sources ON sources.id = chunks.source_id
            WHERE (sources.id IS NULL OR sources.deleted_at IS NOT NULL) {vault_clause}
            """,
            params,
        ).fetchone()
        conn.execute(
            f"""
            DELETE FROM source_chunks
            WHERE id IN (
              SELECT chunks.id
              FROM source_chunks chunks
              LEFT JOIN sources ON sources.id = chunks.source_id
              WHERE (sources.id IS NULL OR sources.deleted_at IS NOT NULL) {vault_clause}
            )
            """,
            params,
        )
        conn.execute("PRAGMA optimize")
    return {
        "vault_id": vault_id,
        "orphan_chunks_removed": int(before["count"] if before else 0),
        "optimized": True,
    }


def prune_unreferenced_vector_chunks(
    conn,
    *,
    cutoff: str,
    limit: int = 500,
    dry_run: bool = False,
) -> dict:
    policy = embedding_index_policy()
    protected = {
        (
            str(policy.get("active_embedding_model_id") or ""),
            str(policy.get("active_index_version") or ACTIVE_INDEX_VERSION),
        )
    }
    for model_key, version_key in (
        ("previous_embedding_model_id", "previous_index_version"),
        ("building_embedding_model_id", "building_index_version"),
    ):
        model = str(policy.get(model_key) or "")
        if model:
            protected.add((model, str(policy.get(version_key) or ACTIVE_INDEX_VERSION)))
    clauses = " AND ".join("NOT (embedding_model_id = ? AND index_version = ?)" for _ in protected)
    parameters = [value for pair in sorted(protected) for value in pair]
    bounded_limit = max(1, min(int(limit), 5_000))
    rows = conn.execute(
        f"""
        SELECT id, vault_id
        FROM source_chunks
        WHERE created_at < ? AND {clauses}
        ORDER BY created_at, id
        LIMIT ?
        """,
        [cutoff, *parameters, bounded_limit],
    ).fetchall()
    if dry_run:
        return {
            "eligible": len(rows),
            "deleted": 0,
            "batch_limited": len(rows) == bounded_limit,
        }
    chunk_ids = [str(row["id"]) for row in rows]
    if chunk_ids:
        placeholders = ",".join("?" for _ in chunk_ids)
        if _table_exists(conn, "retrieval_snapshot_items"):
            conn.execute(
                f"""
                UPDATE retrieval_snapshot_items
                SET chunk_id = NULL,
                    state = CASE WHEN state = 'current' THEN 'stale' ELSE state END
                WHERE chunk_id IN ({placeholders})
                """,
                chunk_ids,
            )
        for row in rows:
            delete_encrypted_entity(
                conn,
                vault_id=str(row["vault_id"]),
                entity_type="source_chunk",
                entity_id=str(row["id"]),
            )
        conn.execute(f"DELETE FROM source_chunks WHERE id IN ({placeholders})", chunk_ids)
    return {
        "eligible": len(rows),
        "deleted": len(chunk_ids),
        "batch_limited": len(rows) == bounded_limit,
        "protected_tuples": len(protected),
    }


def _table_exists(conn, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def _index_policy_path() -> Path:
    return get_settings().data_dir / "embedding-index-policy.json"


def _write_index_policy(payload: dict) -> None:
    path = _index_policy_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp.replace(path)
