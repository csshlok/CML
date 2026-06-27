import json
from uuid import uuid4

from backend.app.core.database import dict_from_row, utc_now
from backend.app.core.expert_runtime import runtime_adapter_load_plan
from backend.app.core.hardware import hardware_status
from backend.app.core.training_dataset import build_cluster_dataset


def mark_cluster_needs_update(conn, cluster_id: str | None, detail: str) -> None:
    if not cluster_id:
        return
    row = conn.execute("SELECT id, vault_id, expert_status FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
    if row is None:
        return
    current_status = _normalized_expert_status(str(row["expert_status"] or ""))
    already_stale = current_status == "expert_stale"
    if current_status not in {"expert_training_pending", "expert_training_running"}:
        conn.execute(
            "UPDATE clusters SET expert_status = 'expert_stale', updated_at = ? WHERE id = ?",
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
    active_metadata = _artifact_metadata(active) if active else {}
    stale = bool(active and dataset_hash and active.get("dataset_hash") != dataset_hash)
    runtime_load = {}
    trained = bool(active and not stale)
    runtime_load_failed = False
    activation_guard = activation_guard_report(
        active,
        current_dataset_hash=dataset_hash,
        require_current_dataset_match=False,
    ) if active else {}
    objective_incompatible = bool(active and not activation_guard.get("objective_version_ok", True))
    benchmark_incompatible = bool(active and not activation_guard.get("benchmark_pass_ok", True))
    if active:
        runtime_load = runtime_adapter_load_plan(
            adapter_path=active.get("local_path") or "",
            base_model=active.get("base_model") or "",
        )
        runtime_load_failed = not bool(runtime_load.get("available"))
        trained = trained and not runtime_load_failed
        trained = trained and not objective_incompatible
        trained = trained and not benchmark_incompatible

    failure_code = ""
    detail = ""
    if latest_job is not None:
        job = dict_from_row(latest_job)
        failure_code = str(job.get("failure_code") or "")
        detail = str(job.get("detail") or "")
    objective_version = str(active_metadata.get("expert_objective_version") or "").strip()
    if active and objective_incompatible and objective_version:
        failure_code = failure_code or "legacy_prompt_only"
        detail = detail or "Active adapter uses a legacy prompt-only objective and cannot graduate as expert compression ready."
    elif active and runtime_load_failed:
        failure_code = failure_code or "runtime_load_failed"
        detail = detail or str(runtime_load.get("detail") or "Active adapter is not loadable on this machine.")
    elif active and objective_incompatible:
        failure_code = failure_code or "legacy_prompt_only"
        detail = detail or "Active adapter uses a legacy prompt-only objective and cannot graduate as expert compression ready."
    elif active and benchmark_incompatible:
        failure_code = failure_code or "benchmark_unverified"
        detail = detail or "Active adapter is missing a passing bundle benchmark for the current expert-compression objective."

    expert_status = _normalized_expert_status(str(cluster.get("expert_status") or "retrieval_ready"))
    if stale and expert_status == "expert_compression_ready":
        expert_status = "expert_stale"
        detail = detail or "Cluster sources changed after the active adapter was trained."
    elif runtime_load_failed and expert_status == "expert_compression_ready":
        expert_status = "training_failed"
    elif objective_incompatible and expert_status == "expert_compression_ready":
        expert_status = "expert_stale"
    elif benchmark_incompatible and expert_status == "expert_compression_ready":
        expert_status = "expert_stale"
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
        "activation_guard": activation_guard if active else {},
    }


def _artifact_metadata(active: dict) -> dict:
    raw = str(active.get("metrics_json") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def activation_guard_report(
    artifact: dict | None,
    *,
    current_dataset_hash: str = "",
    require_current_dataset_match: bool = True,
) -> dict:
    if not artifact:
        return {
            "ok": False,
            "objective_version_ok": False,
            "benchmark_pass_ok": False,
            "dataset_match_ok": False,
            "failure_code": "artifact_missing",
            "detail": "No expert artifact is available.",
        }
    metadata = _artifact_metadata(artifact)
    objective_version = str(metadata.get("expert_objective_version") or "").strip()
    benchmark_report = dict(metadata.get("benchmark_report") or {})
    metadata_dataset_hash = str(metadata.get("dataset_hash") or "").strip()
    artifact_dataset_hash = str(artifact.get("dataset_hash") or "").strip()
    benchmark_dataset_hash = str(benchmark_report.get("dataset_hash") or "").strip()
    benchmark_passes = bool(benchmark_report.get("passes"))
    objective_version_ok = objective_version == "retrieval_grounded_compression_v1"
    benchmark_pass_ok = benchmark_passes and str((benchmark_report.get("metadata") or {}).get("expert_objective_version") or objective_version).strip() == "retrieval_grounded_compression_v1"
    artifact_dataset = artifact_dataset_hash or metadata_dataset_hash
    dataset_match_ok = True
    if require_current_dataset_match and current_dataset_hash:
        dataset_match_ok = bool(
            artifact_dataset
            and artifact_dataset == current_dataset_hash
            and (not benchmark_dataset_hash or benchmark_dataset_hash == current_dataset_hash)
        )
    failure_code = ""
    detail = ""
    if not objective_version_ok:
        failure_code = "legacy_prompt_only"
        detail = "Artifact objective version is not retrieval_grounded_compression_v1."
    elif not benchmark_pass_ok:
        failure_code = "benchmark_unverified"
        detail = "Artifact does not carry a passing bundle benchmark for the retrieval-grounded expert-compression objective."
    elif not dataset_match_ok:
        failure_code = "dataset_mismatch"
        detail = "Artifact dataset hash does not match the cluster's current dataset hash."
    return {
        "ok": not failure_code,
        "objective_version": objective_version,
        "objective_version_ok": objective_version_ok,
        "benchmark_pass_ok": benchmark_pass_ok,
        "dataset_match_ok": dataset_match_ok,
        "artifact_dataset_hash": artifact_dataset,
        "benchmark_dataset_hash": benchmark_dataset_hash,
        "current_dataset_hash": current_dataset_hash,
        "failure_code": failure_code,
        "detail": detail,
    }


def _user_status(expert_status: str, *, trained: bool, stale: bool, failure_code: str) -> str:
    if trained and not stale:
        return "Expert compression ready"
    if stale or expert_status in {"needs-update", "expert_stale"}:
        return "Expert needs update"
    if expert_status in {"training_pending", "expert_training_pending"}:
        return "Preparing expert compression"
    if expert_status in {"training_running", "expert_training_running"}:
        return "Training cluster compressor"
    if expert_status in {"training_failed", "hardware_unsupported"} or failure_code:
        return "Issue"
    if expert_status == "paused":
        return "Paused"
    if expert_status == "retrieval_only":
        return "Retrieval-only mode"
    if expert_status in {"retrieval_ready", "searchable"}:
        return "Searchable"
    return "Searchable"


def _normalized_expert_status(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"training_pending", "expert_training_pending"}:
        return "expert_training_pending"
    if raw in {"training_running", "expert_training_running"}:
        return "expert_training_running"
    if raw in {"training_ready", "expert_compression_ready", "ready"}:
        return "expert_compression_ready"
    if raw in {"needs-update", "expert_stale"}:
        return "expert_stale"
    if raw in {"retrieval_only"}:
        return "retrieval_only"
    if raw in {"retrieval_ready", "searchable"}:
        return "retrieval_ready"
    return str(value or "retrieval_ready")
