from uuid import uuid4

from backend.app.core.database import dict_from_row, utc_now
from backend.app.core.hardware import hardware_status
from backend.app.core.lora_training import runtime_adapter_load_plan
from backend.app.core.training_dataset import build_cluster_dataset


def mark_cluster_needs_update(conn, cluster_id: str | None, detail: str) -> None:
    if not cluster_id:
        return
    row = conn.execute("SELECT id, vault_id, expert_status FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
    if row is None:
        return
    already_stale = str(row["expert_status"] or "") == "needs-update"
    if row["expert_status"] not in {"training_pending", "training_running"}:
        conn.execute(
            "UPDATE clusters SET expert_status = 'needs-update', updated_at = ? WHERE id = ?",
            (utc_now(), cluster_id),
        )
    create_expert_job(
        conn,
        cluster_id=cluster_id,
        vault_id=row["vault_id"],
        action="refresh-needed",
        detail=detail,
        dedupe_if_already_stale=already_stale,
    )


def create_expert_job(
    conn,
    *,
    cluster_id: str,
    vault_id: str,
    action: str,
    detail: str = "",
    dedupe_if_already_stale: bool = False,
) -> dict:
    now = utc_now()
    hardware = hardware_status()
    status = "queued"
    failure_code = ""
    if action == "refresh-needed":
        if dedupe_if_already_stale:
            existing = conn.execute(
                """
                SELECT *
                FROM cluster_expert_jobs
                WHERE cluster_id = ? AND action = 'refresh-needed'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (cluster_id,),
            ).fetchone()
            if existing is not None:
                conn.execute(
                    """
                    UPDATE cluster_expert_jobs
                    SET detail = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (detail, now, existing["id"]),
                )
                refreshed = conn.execute("SELECT * FROM cluster_expert_jobs WHERE id = ?", (existing["id"],)).fetchone()
                return dict_from_row(refreshed)
        status = "completed"
    if action in {"retrain", "train"} and hardware["training_supported"] is False:
        status = "manual_review"
        failure_code = "hardware_unsupported"
        detail = detail or hardware["detail"]
    job = {
        "id": f"expert-job-{uuid4()}",
        "cluster_id": cluster_id,
        "vault_id": vault_id,
        "action": action,
        "status": status,
        "detail": detail,
        "failure_code": failure_code,
        "artifact_path": None,
        "hardware_tier": hardware["hardware_tier"],
        "created_at": now,
        "updated_at": now,
    }
    conn.execute(
        """
        INSERT INTO cluster_expert_jobs (
            id, cluster_id, vault_id, action, status, detail, failure_code, artifact_path,
            hardware_tier, created_at, updated_at
        )
        VALUES (
            :id, :cluster_id, :vault_id, :action, :status, :detail, :failure_code,
            :artifact_path, :hardware_tier, :created_at, :updated_at
        )
        """,
        job,
    )
    if action in {"retrain", "train"} and status == "queued":
        conn.execute(
            "UPDATE clusters SET expert_status = 'training_pending', updated_at = ? WHERE id = ?",
            (utc_now(), cluster_id),
        )
        from backend.app.core.background_jobs import enqueue_job

        enqueue_job(
            conn,
            job_type="train_cluster_adapter",
            payload={"cluster_id": cluster_id, "vault_id": vault_id, "expert_job_id": job["id"]},
            dedupe_key=f"train-cluster-adapter:{cluster_id}",
            scope_id=cluster_id,
            user_initiated=True,
        )
    return job


def latest_expert_jobs(conn, cluster_id: str, limit: int = 10) -> list[dict]:
    rows = conn.execute(
        """
        SELECT * FROM cluster_expert_jobs
        WHERE cluster_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (cluster_id, limit),
    ).fetchall()
    return [dict_from_row(row) for row in rows]


def expert_status_report(conn, cluster_id: str) -> dict:
    cluster_row = conn.execute("SELECT * FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
    if cluster_row is None:
        raise KeyError(cluster_id)
    cluster = dict_from_row(cluster_row)
    active_row = conn.execute(
        """
        SELECT * FROM expert_artifacts
        WHERE cluster_id = ? AND active = 1 AND deleted_at IS NULL
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (cluster_id,),
    ).fetchone()
    latest_job = conn.execute(
        """
        SELECT * FROM cluster_expert_jobs
        WHERE cluster_id = ?
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (cluster_id,),
    ).fetchone()
    dataset_hash = ""
    try:
        dataset_hash = str(build_cluster_dataset(cluster_id).get("dataset_hash") or "")
    except Exception:
        dataset_hash = ""

    active = dict_from_row(active_row) if active_row is not None else None
    stale = bool(active and dataset_hash and active.get("dataset_hash") != dataset_hash)
    runtime_load = {}
    trained = bool(active and not stale)
    runtime_load_failed = False
    if active:
        runtime_load = runtime_adapter_load_plan(
            adapter_path=active.get("local_path") or "",
            base_model=active.get("base_model") or "",
        )
        runtime_load_failed = not bool(runtime_load.get("available"))
        trained = trained and not runtime_load_failed

    failure_code = ""
    detail = ""
    if latest_job is not None:
        job = dict_from_row(latest_job)
        failure_code = str(job.get("failure_code") or "")
        detail = str(job.get("detail") or "")
    if active and runtime_load_failed:
        failure_code = failure_code or "runtime_load_failed"
        detail = detail or str(runtime_load.get("detail") or "Active adapter is not loadable on this machine.")

    expert_status = str(cluster.get("expert_status") or "retrieval_ready")
    if stale and expert_status == "training_ready":
        expert_status = "needs-update"
        detail = detail or "Cluster sources changed after the active adapter was trained."
    elif runtime_load_failed and expert_status == "training_ready":
        expert_status = "training_failed"
    user_status = _user_status(
        expert_status,
        trained=trained,
        stale=stale,
        failure_code=failure_code,
    )
    return {
        "cluster_id": cluster_id,
        "expert_status": expert_status,
        "user_status": user_status,
        "searchable": True,
        "trained": trained,
        "stale": stale,
        "active_artifact_id": active.get("id") if active else None,
        "active_dataset_hash": active.get("dataset_hash") if active else None,
        "current_dataset_hash": dataset_hash,
        "runtime_load": runtime_load,
        "failure_code": failure_code,
        "detail": detail,
    }


def _user_status(expert_status: str, *, trained: bool, stale: bool, failure_code: str) -> str:
    if trained and not stale:
        return "Ready"
    if stale or expert_status == "needs-update":
        return "Needs update"
    if expert_status in {"training_pending", "training_running"}:
        return "Learning"
    if expert_status in {"training_failed", "hardware_unsupported"} or failure_code:
        return "Issue"
    if expert_status == "paused":
        return "Paused"
    return "Searchable now"
