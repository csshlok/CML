from uuid import uuid4
import json

from fastapi import APIRouter, HTTPException

from backend.app.core.cluster_suggestions import suggest_source_cluster_moves
from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.core.expert_lifecycle import (
    activation_guard_report,
    create_expert_job,
    expert_status_report,
    latest_expert_jobs,
)
from backend.app.core.lora_training import graduation_contract, verify_adapter_artifact
from backend.app.core.retrieval_cache import invalidate_caches_for_source
from backend.app.core.sql import build_update_assignments
from backend.app.schemas import (
    ClusterCreate,
    ClusterExpertJobRead,
    ClusterMergeRequest,
    ClusterRead,
    ClusterSuggestionRead,
    ClusterUpdate,
    ExpertArtifactRead,
    ExpertGraduationContractRead,
    ExpertStatusRead,
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


@router.post("", response_model=ClusterRead)
def create_cluster(payload: ClusterCreate) -> dict:
    now = utc_now()
    cluster = {
        "id": f"cluster-{uuid4()}",
        "vault_id": payload.vault_id,
        "name": payload.name,
        "description": payload.description,
        "color": payload.color,
        "expert_status": "setting-up",
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
                id, vault_id, name, description, color, expert_status, created_at, updated_at
            )
            VALUES (
                :id, :vault_id, :name, :description, :color, :expert_status, :created_at, :updated_at
            )
            """,
            cluster,
        )
    return cluster


@router.get("/suggestions", response_model=list[ClusterSuggestionRead])
def list_cluster_suggestions(vault_id: str, limit: int = 12) -> list[dict]:
    with connect() as conn:
        vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone()
        if vault is None:
            raise HTTPException(status_code=404, detail="Vault not found")
        return suggest_source_cluster_moves(conn, vault_id, limit=max(1, min(limit, 30)))


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
    assignments = build_update_assignments(
        updates,
        {"name", "description", "color", "expert_status", "updated_at"},
    )
    params = {"id": cluster_id, **updates}
    with connect() as conn:
        existing = conn.execute("SELECT id FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Cluster not found")
        conn.execute(f"UPDATE clusters SET {assignments} WHERE id = :id", params)
        row = conn.execute("SELECT * FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
    return dict_from_row(row)


@router.get("/{cluster_id}/expert/jobs", response_model=list[ClusterExpertJobRead])
def list_expert_jobs(cluster_id: str) -> list[dict]:
    with connect() as conn:
        existing = conn.execute("SELECT id FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Cluster not found")
        return latest_expert_jobs(conn, cluster_id)


@router.get("/{cluster_id}/expert/contract", response_model=ExpertGraduationContractRead)
def get_expert_graduation_contract(cluster_id: str) -> dict:
    with connect() as conn:
        existing = conn.execute("SELECT id FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Cluster not found")
    return graduation_contract()


@router.get("/{cluster_id}/expert/status", response_model=ExpertStatusRead)
def get_expert_status(cluster_id: str) -> dict:
    with connect() as conn:
        try:
            return expert_status_report(conn, cluster_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Cluster not found") from None


@router.get("/{cluster_id}/expert/artifacts", response_model=list[ExpertArtifactRead])
def list_expert_artifacts(cluster_id: str) -> list[dict]:
    with connect() as conn:
        existing = conn.execute("SELECT id FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Cluster not found")
        rows = conn.execute(
            """
            SELECT * FROM expert_artifacts
            WHERE cluster_id = ? AND deleted_at IS NULL
            ORDER BY updated_at DESC
            LIMIT 25
            """,
            (cluster_id,),
        ).fetchall()
        return [dict_from_row(row) for row in rows]


@router.post("/{cluster_id}/expert/retrain", response_model=ClusterExpertJobRead)
def queue_expert_retrain(cluster_id: str) -> dict:
    with connect() as conn:
        cluster = conn.execute("SELECT id, vault_id FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
        if cluster is None:
            raise HTTPException(status_code=404, detail="Cluster not found")
        return create_expert_job(
            conn,
            cluster_id=cluster_id,
            vault_id=cluster["vault_id"],
            action="retrain",
            detail="Manual expert-compression training pass queued.",
        )


@router.post("/{cluster_id}/expert/artifacts/{artifact_id}/activate", response_model=ExpertArtifactRead)
def activate_expert_artifact(cluster_id: str, artifact_id: str) -> dict:
    now = utc_now()
    with connect() as conn:
        cluster = conn.execute(
            "SELECT id FROM clusters WHERE id = ?",
            (cluster_id,),
        ).fetchone()
        if cluster is None:
            raise HTTPException(status_code=404, detail="Cluster not found")
        row = conn.execute(
            """
            SELECT * FROM expert_artifacts
            WHERE id = ? AND cluster_id = ? AND status = 'ready' AND deleted_at IS NULL
            """,
            (artifact_id, cluster_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Ready artifact not found")
        artifact = dict_from_row(row)
        try:
            verify_adapter_artifact(artifact["local_path"])
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        current_dataset_hash = str((expert_status_report(conn, cluster_id) or {}).get("current_dataset_hash") or "")
        guard = activation_guard_report(
            artifact,
            current_dataset_hash=current_dataset_hash,
            require_current_dataset_match=True,
        )
        if not guard["ok"]:
            conn.execute(
                "UPDATE clusters SET expert_status = 'expert_stale', updated_at = ? WHERE id = ?",
                (now, cluster_id),
            )
            raise HTTPException(status_code=409, detail=str(guard["detail"] or guard["failure_code"] or "Artifact cannot be activated"))
        conn.execute("UPDATE expert_artifacts SET active = 0, updated_at = ? WHERE cluster_id = ?", (now, cluster_id))
        conn.execute(
            "UPDATE expert_artifacts SET active = 1, rolled_back_at = NULL, updated_at = ? WHERE id = ?",
            (now, artifact_id),
        )
        conn.execute(
            "UPDATE clusters SET expert_status = 'expert_compression_ready', updated_at = ? WHERE id = ?",
            (now, cluster_id),
        )
        updated = conn.execute("SELECT * FROM expert_artifacts WHERE id = ?", (artifact_id,)).fetchone()
    return dict_from_row(updated)


@router.post("/{cluster_id}/expert/rollback", response_model=ExpertArtifactRead)
def rollback_expert_artifact(cluster_id: str) -> dict:
    now = utc_now()
    with connect() as conn:
        cluster = conn.execute("SELECT id FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
        if cluster is None:
            raise HTTPException(status_code=404, detail="Cluster not found")
        active = conn.execute(
            "SELECT id FROM expert_artifacts WHERE cluster_id = ? AND active = 1 AND deleted_at IS NULL",
            (cluster_id,),
        ).fetchone()
        if active is not None:
            conn.execute(
                "UPDATE expert_artifacts SET active = 0, rolled_back_at = ?, updated_at = ? WHERE id = ?",
                (now, now, active["id"]),
            )
        replacement = conn.execute(
            """
            SELECT * FROM expert_artifacts
            WHERE cluster_id = ? AND status = 'ready' AND deleted_at IS NULL
              AND (? IS NULL OR id != ?)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (cluster_id, active["id"] if active else None, active["id"] if active else None),
        ).fetchone()
        if replacement is None:
            conn.execute(
                "UPDATE clusters SET expert_status = 'rollback_ready', updated_at = ? WHERE id = ?",
                (now, cluster_id),
            )
            raise HTTPException(status_code=409, detail="No previous ready adapter is available for rollback")
        replacement_artifact = dict_from_row(replacement)
        current_dataset_hash = str((expert_status_report(conn, cluster_id) or {}).get("current_dataset_hash") or "")
        guard = activation_guard_report(
            replacement_artifact,
            current_dataset_hash=current_dataset_hash,
            require_current_dataset_match=True,
        )
        if not guard["ok"]:
            conn.execute(
                "UPDATE clusters SET expert_status = 'expert_stale', updated_at = ? WHERE id = ?",
                (now, cluster_id),
            )
            raise HTTPException(status_code=409, detail=str(guard["detail"] or guard["failure_code"] or "Artifact cannot be rolled back"))
        conn.execute("UPDATE expert_artifacts SET active = 1, rolled_back_at = NULL, updated_at = ? WHERE id = ?", (now, replacement["id"]))
        conn.execute(
            "UPDATE clusters SET expert_status = 'expert_compression_ready', updated_at = ? WHERE id = ?",
            (now, cluster_id),
        )
        updated = conn.execute("SELECT * FROM expert_artifacts WHERE id = ?", (replacement["id"],)).fetchone()
    return dict_from_row(updated)


@router.delete("/{cluster_id}/expert/artifacts/{artifact_id}", status_code=204)
def delete_expert_artifact(cluster_id: str, artifact_id: str) -> None:
    now = utc_now()
    with connect() as conn:
        row = conn.execute(
            "SELECT active FROM expert_artifacts WHERE id = ? AND cluster_id = ? AND deleted_at IS NULL",
            (artifact_id, cluster_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Artifact not found")
        if int(row["active"] or 0) == 1:
            raise HTTPException(status_code=409, detail="Active adapter must be rolled back before deletion")
        conn.execute(
            "UPDATE expert_artifacts SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (now, now, artifact_id),
        )


@router.post("/{cluster_id}/expert/pause", response_model=ClusterRead)
def pause_expert(cluster_id: str) -> dict:
    with connect() as conn:
        cluster = conn.execute("SELECT id FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
        if cluster is None:
            raise HTTPException(status_code=404, detail="Cluster not found")
        conn.execute(
            "UPDATE clusters SET expert_status = 'paused', updated_at = ? WHERE id = ?",
            (utc_now(), cluster_id),
        )
    return get_cluster(cluster_id)


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
        conn.execute(
            "UPDATE clusters SET expert_status = 'expert_stale', updated_at = ? WHERE id = ?",
            (now, payload.target_cluster_id),
        )
        conn.execute("DELETE FROM clusters WHERE id = ?", (cluster_id,))
        row = conn.execute("SELECT * FROM clusters WHERE id = ?", (payload.target_cluster_id,)).fetchone()
    return dict_from_row(row)


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
                    id, vault_id, name, description, color, expert_status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_cluster_id,
                    artifact["vault_id"],
                    str(source_snapshot.get("name") or "Restored cluster"),
                    str(source_snapshot.get("description") or ""),
                    str(source_snapshot.get("color") or "sage"),
                    "expert_stale",
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
        conn.execute(
            "UPDATE clusters SET expert_status = 'expert_stale', updated_at = ? WHERE id IN (?, ?)",
            (now, source_cluster_id, artifact["target_cluster_id"]),
        )
        conn.execute(
            "UPDATE cluster_merge_artifacts SET rolled_back_at = ? WHERE id = ?",
            (now, artifact_id),
        )
        row = conn.execute("SELECT * FROM clusters WHERE id = ?", (source_cluster_id,)).fetchone()
    return dict_from_row(row)


@router.delete("/{cluster_id}", status_code=204)
def delete_cluster(cluster_id: str) -> None:
    with connect() as conn:
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
