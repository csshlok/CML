from uuid import uuid4
import json

from fastapi import APIRouter, HTTPException

from backend.app.core.background_jobs import enqueue_job
from backend.app.core.cluster_suggestions import (
    list_or_create_source_cluster_move_batch,
    record_source_cluster_move_batch_decision,
)
from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.core.pagination import cursor_page, decode_cursor
from backend.app.core.cluster_lifecycle import (
    mark_cluster_needs_update,
    prune_empty_auto_cluster,
    refresh_cluster_profile,
)
from backend.app.core.retrieval_cache import invalidate_caches_for_source
from backend.app.core.sql import build_update_assignments
from backend.app.schemas import (
    ClusterCreate,
    ClusterMergeRequest,
    ClusterRead,
    ClusterSuggestionRead,
    ClusterSuggestionDecision,
    ClusterUpdate,
)

router = APIRouter(prefix="/clusters", tags=["clusters"])


@router.get("", response_model=list[ClusterRead])
def list_clusters(vault_id: str | None = None, limit: int = 500, offset: int = 0) -> list[dict]:
    safe_limit = max(1, min(int(limit), 1000))
    safe_offset = max(0, int(offset))
    with connect() as conn:
        if vault_id:
            vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone()
            if vault is None:
                raise HTTPException(status_code=404, detail="Vault not found")
        if vault_id:
            rows = conn.execute(
                "SELECT * FROM clusters WHERE vault_id = ? ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?",
                (vault_id, safe_limit, safe_offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM clusters ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?",
                (safe_limit, safe_offset),
            ).fetchall()
        return [dict_from_row(row) for row in rows]


@router.get("/page")
def list_clusters_page(vault_id: str | None = None, limit: int = 100, cursor: str | None = None) -> dict:
    clauses: list[str] = []
    params: list[object] = []
    if vault_id:
        clauses.append("vault_id = ?")
        params.append(vault_id)
    decoded = decode_cursor(cursor)
    if decoded:
        updated_at, item_id = decoded
        clauses.append("(updated_at < ? OR (updated_at = ? AND id < ?))")
        params.extend([updated_at, updated_at, item_id])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    safe_limit = max(1, min(int(limit), 200))
    with connect() as conn:
        if vault_id and conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Vault not found")
        rows = conn.execute(
            f"SELECT * FROM clusters {where} ORDER BY updated_at DESC, id DESC LIMIT ?",
            [*params, safe_limit + 1],
        ).fetchall()
    return cursor_page(
        [dict_from_row(row) for row in rows],
        requested_limit=safe_limit,
        sort_field="updated_at",
    )


@router.post("", response_model=ClusterRead)
def create_cluster(payload: ClusterCreate) -> dict:
    now = utc_now()
    cluster = {
        "id": f"cluster-{uuid4()}",
        "vault_id": payload.vault_id,
        "name": payload.name,
        "description": payload.description,
        "color": payload.color,
        "index_status": "empty",
        "profile_status": "missing",
        "cluster_summary": "",
        "cluster_glossary": "[]",
        "created_at": now,
        "updated_at": now,
    }
    with connect() as conn:
        vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (payload.vault_id,)).fetchone()
        if vault is None:
            raise HTTPException(status_code=404, detail="Vault not found")
        conn.execute(
            """
            INSERT INTO clusters (
                id, vault_id, name, description, color, index_status, profile_status,
                cluster_summary, cluster_glossary, created_at, updated_at
            )
            VALUES (
                :id, :vault_id, :name, :description, :color, :index_status, :profile_status,
                :cluster_summary, :cluster_glossary, :created_at, :updated_at
            )
            """,
            cluster,
        )
    return cluster


@router.get("/suggestions", response_model=list[ClusterSuggestionRead])
def list_cluster_suggestions(vault_id: str, limit: int = 12, refresh: bool = False) -> list[dict]:
    with connect() as conn:
        vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone()
        if vault is None:
            raise HTTPException(status_code=404, detail="Vault not found")
        return list_or_create_source_cluster_move_batch(
            conn,
            vault_id,
            limit=max(1, min(limit, 30)),
            refresh=refresh,
        )


@router.post("/suggestions/decision")
def decide_cluster_suggestion(payload: ClusterSuggestionDecision) -> dict:
    now = utc_now()
    with connect() as conn:
        source = conn.execute(
            """
            SELECT id, vault_id, cluster_id, updated_at, checksum, metadata_version
            FROM sources
            WHERE id = ? AND deleted_at IS NULL
            """,
            (payload.source_id,),
        ).fetchone()
        if source is None:
            raise HTTPException(status_code=404, detail="Source not found")
        target = conn.execute(
            "SELECT id, name FROM clusters WHERE id = ? AND vault_id = ?",
            (payload.suggested_cluster_id, source["vault_id"]),
        ).fetchone()
        if target is None:
            raise HTTPException(status_code=404, detail="Suggested cluster not found")

        source_updated_at = source["updated_at"]
        source_content_hash = str(source["checksum"] or "") or (
            f"meta:{int(source['metadata_version'] or 0)}:{source['updated_at']}"
        )
        previous_cluster_id = source["cluster_id"]
        candidate_evidence = conn.execute(
            """
            SELECT candidates.source_content_hash, candidates.candidate_profile_hash,
                   candidates.candidate_profile_version
            FROM cluster_suggestion_candidates candidates
            JOIN cluster_suggestion_batches batches ON batches.id = candidates.batch_id
            WHERE candidates.vault_id = ?
              AND candidates.source_id = ?
              AND candidates.suggested_cluster_id = ?
              AND candidates.decision IS NULL
              AND batches.status = 'active'
            ORDER BY candidates.created_at DESC
            LIMIT 1
            """,
            (source["vault_id"], payload.source_id, payload.suggested_cluster_id),
        ).fetchone()
        profile = conn.execute(
            """
            SELECT source_hash, profile_version
            FROM cluster_candidate_profiles
            WHERE cluster_id = ?
            """,
            (payload.suggested_cluster_id,),
        ).fetchone()
        candidate_profile_hash = (
            str(candidate_evidence["candidate_profile_hash"])
            if candidate_evidence is not None
            else str(profile["source_hash"] if profile is not None else "")
        )
        candidate_profile_version = (
            int(candidate_evidence["candidate_profile_version"])
            if candidate_evidence is not None
            else int(profile["profile_version"] if profile is not None else 0)
        )
        if candidate_evidence is not None:
            source_content_hash = str(candidate_evidence["source_content_hash"])
        if payload.action == "accepted":
            source_updated_at = now
            conn.execute(
                "UPDATE sources SET cluster_id = ?, updated_at = ? WHERE id = ?",
                (payload.suggested_cluster_id, now, payload.source_id),
            )
            mark_cluster_needs_update(conn, payload.suggested_cluster_id, "Source moved from a suggestion.")
            if not prune_empty_auto_cluster(conn, previous_cluster_id):
                mark_cluster_needs_update(conn, previous_cluster_id, "Source moved from a suggestion.")
            invalidate_caches_for_source(payload.source_id, conn=conn)

        conn.execute(
            """
            INSERT INTO cluster_suggestion_decisions (
                source_id, vault_id, suggested_cluster_id, action,
                source_updated_at, source_content_hash, candidate_profile_hash,
                candidate_profile_version, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                suggested_cluster_id = excluded.suggested_cluster_id,
                action = excluded.action,
                source_updated_at = excluded.source_updated_at,
                source_content_hash = excluded.source_content_hash,
                candidate_profile_hash = excluded.candidate_profile_hash,
                candidate_profile_version = excluded.candidate_profile_version,
                updated_at = excluded.updated_at
            """,
            (
                payload.source_id,
                source["vault_id"],
                payload.suggested_cluster_id,
                payload.action,
                source_updated_at,
                source_content_hash,
                candidate_profile_hash,
                candidate_profile_version,
                now,
                now,
            ),
        )
        record_source_cluster_move_batch_decision(
            conn,
            vault_id=str(source["vault_id"]),
            source_id=payload.source_id,
            suggested_cluster_id=payload.suggested_cluster_id,
            action=payload.action,
            decided_at=now,
        )
    return {
        "source_id": payload.source_id,
        "cluster_id": payload.suggested_cluster_id if payload.action == "accepted" else previous_cluster_id,
        "cluster_name": target["name"],
        "action": payload.action,
    }


@router.get("/{cluster_id}", response_model=ClusterRead)
def get_cluster(cluster_id: str) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return dict_from_row(row)


@router.patch("/{cluster_id}", response_model=ClusterRead)
def update_cluster(cluster_id: str, payload: ClusterUpdate) -> dict:
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return get_cluster(cluster_id)

    updates["updated_at"] = utc_now()
    if "name" in updates:
        updates["name_origin"] = "user"
    assignments = build_update_assignments(
        updates,
        {"name", "name_origin", "description", "color", "index_status", "profile_status", "updated_at"},
    )
    params = {"id": cluster_id, **updates}
    with connect() as conn:
        existing = conn.execute("SELECT id FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Cluster not found")
        conn.execute(f"UPDATE clusters SET {assignments} WHERE id = :id", params)
        row = conn.execute("SELECT * FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
    return dict_from_row(row)


@router.post("/{cluster_id}/merge", response_model=ClusterRead)
def merge_cluster(cluster_id: str, payload: ClusterMergeRequest) -> dict:
    if cluster_id == payload.target_cluster_id:
        raise HTTPException(status_code=400, detail="Choose a different target cluster.")

    now = utc_now()
    with connect() as conn:
        source = conn.execute("SELECT * FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
        target = conn.execute(
            "SELECT * FROM clusters WHERE id = ?",
            (payload.target_cluster_id,),
        ).fetchone()
        if source is None or target is None:
            raise HTTPException(status_code=404, detail="Cluster not found")
        if source["vault_id"] != target["vault_id"]:
            raise HTTPException(status_code=400, detail="Clusters must be in the same vault.")
        moved_sources = [
            row["id"]
            for row in conn.execute("SELECT id FROM sources WHERE cluster_id = ?", (cluster_id,)).fetchall()
        ]
        moved_chats = [
            row["id"]
            for row in conn.execute("SELECT id FROM chat_sessions WHERE scope_cluster_id = ?", (cluster_id,)).fetchall()
        ]
        conn.execute(
            """
            INSERT INTO cluster_merge_artifacts (
                id, vault_id, source_cluster_id, target_cluster_id, source_cluster_snapshot,
                target_cluster_snapshot, moved_source_ids, moved_chat_session_ids, reversible,
                rolled_back_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, NULL, ?)
            """,
            (
                f"cluster-merge-{uuid4()}",
                source["vault_id"],
                cluster_id,
                payload.target_cluster_id,
                json.dumps(dict_from_row(source), separators=(",", ":")),
                json.dumps(dict_from_row(target), separators=(",", ":")),
                json.dumps(moved_sources, separators=(",", ":")),
                json.dumps(moved_chats, separators=(",", ":")),
                now,
            ),
        )

        conn.execute(
            "UPDATE sources SET cluster_id = ?, updated_at = ? WHERE cluster_id = ?",
            (payload.target_cluster_id, now, cluster_id),
        )
        conn.execute(
            "UPDATE chat_sessions SET scope_cluster_id = ?, updated_at = ? WHERE scope_cluster_id = ?",
            (payload.target_cluster_id, now, cluster_id),
        )
        for source_id in moved_sources:
            invalidate_caches_for_source(source_id, conn=conn)
        mark_cluster_needs_update(conn, payload.target_cluster_id, "Cluster sources changed after a merge.")
        conn.execute("DELETE FROM clusters WHERE id = ?", (cluster_id,))
        row = conn.execute("SELECT * FROM clusters WHERE id = ?", (payload.target_cluster_id,)).fetchone()
    return dict_from_row(row)


@router.post("/{cluster_id}/refresh-profile", response_model=ClusterRead)
def refresh_cluster_profile_now(cluster_id: str) -> dict:
    now = utc_now()
    with connect() as conn:
        row = conn.execute("SELECT * FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Cluster not found")
        conn.execute(
            "UPDATE clusters SET profile_status = 'refreshing', updated_at = ? WHERE id = ?",
            (now, cluster_id),
        )
        enqueue_job(
            conn,
            job_type="refresh_cluster_profile",
            payload={"cluster_id": cluster_id, "vault_id": row["vault_id"]},
            dedupe_key=f"refresh-cluster-profile:{cluster_id}",
            scope_id=cluster_id,
            user_initiated=True,
        )
        refreshed = conn.execute("SELECT * FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
    return dict_from_row(refreshed)


@router.get("/{cluster_id}/merge-artifacts")
def list_cluster_merge_artifacts(cluster_id: str) -> dict:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM cluster_merge_artifacts
            WHERE source_cluster_id = ? OR target_cluster_id = ?
            ORDER BY created_at DESC
            LIMIT 50
            """,
            (cluster_id, cluster_id),
        ).fetchall()
    return {
        "cluster_id": cluster_id,
        "items": [
            {
                "id": row["id"],
                "vault_id": row["vault_id"],
                "source_cluster_id": row["source_cluster_id"],
                "target_cluster_id": row["target_cluster_id"],
                "moved_source_ids": json.loads(row["moved_source_ids"] or "[]"),
                "moved_chat_session_ids": json.loads(row["moved_chat_session_ids"] or "[]"),
                "reversible": bool(row["reversible"]),
                "rolled_back_at": row["rolled_back_at"],
                "created_at": row["created_at"],
            }
            for row in rows
        ],
    }


@router.post("/merge-artifacts/{artifact_id}/rollback", response_model=ClusterRead)
def rollback_cluster_merge_artifact(artifact_id: str) -> dict:
    now = utc_now()
    with connect() as conn:
        artifact = conn.execute("SELECT * FROM cluster_merge_artifacts WHERE id = ?", (artifact_id,)).fetchone()
        if artifact is None:
            raise HTTPException(status_code=404, detail="Merge artifact not found")
        if artifact["rolled_back_at"]:
            raise HTTPException(status_code=409, detail="Merge artifact was already rolled back")
        if int(artifact["reversible"] or 0) != 1:
            raise HTTPException(status_code=409, detail="Merge artifact is not reversible")

        source_snapshot = _json_object(artifact["source_cluster_snapshot"])
        target = conn.execute("SELECT * FROM clusters WHERE id = ?", (artifact["target_cluster_id"],)).fetchone()
        if target is None:
            raise HTTPException(status_code=409, detail="Target cluster no longer exists")

        source_cluster_id = artifact["source_cluster_id"]
        existing_source_cluster = conn.execute("SELECT id FROM clusters WHERE id = ?", (source_cluster_id,)).fetchone()
        if existing_source_cluster is None:
            conn.execute(
                """
                INSERT INTO clusters (
                    id, vault_id, name, description, color, index_status, profile_status,
                    cluster_summary, cluster_glossary, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_cluster_id,
                    artifact["vault_id"],
                    str(source_snapshot.get("name") or "Restored cluster"),
                    str(source_snapshot.get("description") or ""),
                    str(source_snapshot.get("color") or "sage"),
                    "ready",
                    "stale",
                    "",
                    "[]",
                    str(source_snapshot.get("created_at") or now),
                    now,
                ),
            )

        moved_source_ids = _json_list(artifact["moved_source_ids"])
        moved_chat_ids = _json_list(artifact["moved_chat_session_ids"])
        for source_id in moved_source_ids:
            conn.execute(
                """
                UPDATE sources
                SET cluster_id = ?, updated_at = ?
                WHERE id = ? AND vault_id = ? AND deleted_at IS NULL
                """,
                (source_cluster_id, now, source_id, artifact["vault_id"]),
            )
            invalidate_caches_for_source(source_id, conn=conn)
        for chat_id in moved_chat_ids:
            conn.execute(
                """
                UPDATE chat_sessions
                SET scope_cluster_id = ?, updated_at = ?
                WHERE id = ? AND vault_id = ?
                """,
                (source_cluster_id, now, chat_id, artifact["vault_id"]),
            )
        mark_cluster_needs_update(conn, source_cluster_id, "Cluster merge rollback restored sources.")
        mark_cluster_needs_update(conn, artifact["target_cluster_id"], "Cluster merge rollback removed sources.")
        refresh_cluster_profile(conn, source_cluster_id)
        conn.execute(
            "UPDATE cluster_merge_artifacts SET rolled_back_at = ? WHERE id = ?",
            (now, artifact_id),
        )
        row = conn.execute("SELECT * FROM clusters WHERE id = ?", (source_cluster_id,)).fetchone()
    return dict_from_row(row)


@router.delete("/{cluster_id}", status_code=204)
def delete_cluster(cluster_id: str) -> None:
    with connect() as conn:
        conn.execute(
            "DELETE FROM cluster_suggestion_decisions WHERE suggested_cluster_id = ?",
            (cluster_id,),
        )
        result = conn.execute("DELETE FROM clusters WHERE id = ?", (cluster_id,))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Cluster not found")


def _json_list(raw: str) -> list[str]:
    try:
        parsed = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _json_object(raw: str) -> dict:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
