import json
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.core.embeddings import active_embedding_model_id, reindex_source_chunks


ACTIVE_INDEX_VERSION = "v1"


def embedding_index_policy() -> dict:
    path = _index_policy_path()
    payload = {
        "active_embedding_model_id": active_embedding_model_id(),
        "active_index_version": ACTIVE_INDEX_VERSION,
        "building_embedding_model_id": None,
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


def begin_embedding_index_transition(model_id: str) -> dict:
    payload = embedding_index_policy()
    payload.update(
        {
            "building_embedding_model_id": model_id,
            "transition_state": "building",
            "updated_at": utc_now(),
        }
    )
    _write_index_policy(payload)
    return payload


def activate_embedding_index(model_id: str, index_version: str = ACTIVE_INDEX_VERSION) -> dict:
    payload = embedding_index_policy()
    payload.update(
        {
            "active_embedding_model_id": model_id,
            "active_index_version": index_version,
            "building_embedding_model_id": None,
            "transition_state": "active",
            "updated_at": utc_now(),
        }
    )
    _write_index_policy(payload)
    return payload


def vector_repair_plan(vault_id: str | None = None) -> dict:
    params: list[str] = []
    vault_clause = ""
    if vault_id:
        vault_clause = "AND sources.vault_id = ?"
        params.append(vault_id)
    active_model = embedding_index_policy()["active_embedding_model_id"]
    with connect() as conn:
        missing_rows = conn.execute(
            f"""
            SELECT sources.id
            FROM sources
            WHERE sources.state = 'indexed'
              AND sources.deleted_at IS NULL
              {vault_clause}
              AND NOT EXISTS (
                SELECT 1 FROM source_chunks chunks WHERE chunks.source_id = sources.id
              )
            ORDER BY sources.updated_at DESC
            """,
            params,
        ).fetchall()
        stale_rows = conn.execute(
            f"""
            SELECT DISTINCT sources.id
            FROM sources
            JOIN source_chunks chunks ON chunks.source_id = sources.id
            WHERE sources.deleted_at IS NULL
              {vault_clause}
              AND (
                chunks.embedding = ''
                OR chunks.indexed_at IS NULL
                OR chunks.embedding_model_id != ?
                OR chunks.index_version != ?
              )
            ORDER BY sources.updated_at DESC
            """,
            [*params, active_model, ACTIVE_INDEX_VERSION],
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
        "active_index_version": ACTIVE_INDEX_VERSION,
        "missing_vector_source_ids": missing,
        "stale_vector_source_ids": stale,
        "orphan_chunk_count": int(orphan_chunks["count"] if orphan_chunks else 0),
        "repair_source_count": len(missing) + len(stale),
        "compaction_recommended": int(orphan_chunks["count"] if orphan_chunks else 0) > 0,
    }


def repair_vectors(vault_id: str | None = None, *, limit: int = 100) -> dict:
    plan = vector_repair_plan(vault_id)
    source_ids = [*plan["missing_vector_source_ids"], *plan["stale_vector_source_ids"]][:limit]
    chunks_indexed = 0
    repaired = 0
    with connect() as conn:
        for source_id in source_ids:
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


def _index_policy_path() -> Path:
    return get_settings().data_dir / "embedding-index-policy.json"


def _write_index_policy(payload: dict) -> None:
    path = _index_policy_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp.replace(path)
