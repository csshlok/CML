import json
from uuid import uuid4

from backend.app.core.database import connect, dict_from_row, utc_now

DEFAULT_NORMALIZATION_VERSION = "norm-v1"
DEFAULT_EXTRACTION_VERSION = "extract-v1"
DEFAULT_INDEX_VERSION = "v1"
DEFAULT_EPOCH = 1


class DerivedStateError(RuntimeError):
    pass


class DerivedStatePublicationError(DerivedStateError):
    pass


def query_epoch_snapshot(
    vault_id: str,
    *,
    embedding_model_id: str | None = None,
    index_version: str | None = None,
) -> dict:
    with connect() as conn:
        return query_epoch_snapshot_conn(
            conn,
            vault_id,
            embedding_model_id=embedding_model_id,
            index_version=index_version,
        )


def query_epoch_snapshot_conn(
    conn,
    vault_id: str,
    *,
    embedding_model_id: str | None = None,
    index_version: str | None = None,
) -> dict:
    row = conn.execute(
        "SELECT active_derived_state_tuple FROM vault_security_metadata WHERE vault_id = ?",
        (vault_id,),
    ).fetchone()
    raw_tuple = row["active_derived_state_tuple"] if row is not None else "{}"
    snapshot = normalize_tuple(
        raw_tuple,
        fallback_embedding_model_id=embedding_model_id,
        fallback_index_version=index_version,
    )
    return snapshot


def normalize_tuple(
    value: str | dict | None,
    *,
    fallback_embedding_model_id: str | None = None,
    fallback_index_version: str | None = None,
) -> dict:
    if isinstance(value, str):
        try:
            parsed = json.loads(value or "{}")
        except json.JSONDecodeError as exc:
            raise DerivedStateError("invalid_derived_state_tuple") from exc
    elif isinstance(value, dict):
        parsed = dict(value)
    else:
        parsed = {}
    embedding_model_id = (
        parsed.get("embedding_model_id")
        or parsed.get("embedding_model_version")
        or fallback_embedding_model_id
        or "hash"
    )
    if embedding_model_id in {"unset", "hash"} and fallback_embedding_model_id:
        embedding_model_id = fallback_embedding_model_id
    if (
        embedding_model_id == "hash-dev"
        and fallback_embedding_model_id
        and fallback_embedding_model_id not in {"hash", "hash-dev"}
    ):
        embedding_model_id = fallback_embedding_model_id
    snapshot = {
        "normalization_version": str(parsed.get("normalization_version") or DEFAULT_NORMALIZATION_VERSION),
        "embedding_model_id": str(embedding_model_id),
        "index_version": str(parsed.get("index_version") or fallback_index_version or DEFAULT_INDEX_VERSION),
        "extraction_version": str(parsed.get("extraction_version") or DEFAULT_EXTRACTION_VERSION),
        "epoch": int(parsed.get("epoch") or DEFAULT_EPOCH),
    }
    if snapshot["epoch"] <= 0:
        raise DerivedStateError("invalid_derived_state_epoch")
    return snapshot


def tuple_json(snapshot: dict) -> str:
    return json.dumps(normalize_tuple(snapshot), sort_keys=True, separators=(",", ":"))


def chunk_tuple_values(snapshot: dict) -> dict:
    normalized = normalize_tuple(snapshot)
    return {
        "normalization_version": normalized["normalization_version"],
        "extraction_version": normalized["extraction_version"],
        "derived_state_epoch": normalized["epoch"],
    }


def chunk_eligibility_sql(alias: str, snapshot: dict) -> tuple[str, list]:
    normalized = normalize_tuple(snapshot)
    prefix = f"{alias}." if alias else ""
    return (
        f"""
        AND {prefix}activation_state = 'active'
        AND {prefix}embedding_model_id = ?
        AND {prefix}index_version = ?
        AND {prefix}normalization_version = ?
        AND {prefix}extraction_version = ?
        AND {prefix}derived_state_epoch = ?
        """,
        [
            normalized["embedding_model_id"],
            normalized["index_version"],
            normalized["normalization_version"],
            normalized["extraction_version"],
            normalized["epoch"],
        ],
    )


def begin_publication(
    vault_id: str,
    target_tuple: dict,
    *,
    artifact_manifest: dict | None = None,
) -> dict:
    snapshot = normalize_tuple(target_tuple)
    now = utc_now()
    publication = {
        "id": f"derived-pub-{uuid4()}",
        "vault_id": vault_id,
        "epoch": snapshot["epoch"],
        "normalization_version": snapshot["normalization_version"],
        "embedding_model_id": snapshot["embedding_model_id"],
        "index_version": snapshot["index_version"],
        "extraction_version": snapshot["extraction_version"],
        "status": "staging",
        "artifact_manifest_json": json.dumps(artifact_manifest or {}, sort_keys=True),
        "created_at": now,
    }
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO derived_state_publications (
                id, vault_id, epoch, normalization_version, embedding_model_id,
                index_version, extraction_version, status, artifact_manifest_json, created_at
            )
            VALUES (
                :id, :vault_id, :epoch, :normalization_version, :embedding_model_id,
                :index_version, :extraction_version, :status, :artifact_manifest_json, :created_at
            )
            """,
            publication,
        )
    return publication


def record_staged_artifact(
    publication_id: str,
    *,
    vault_id: str,
    artifact_type: str,
    artifact_ref: str,
    content_hash: str = "",
    byte_length: int = 0,
    owner_job_id: str | None = None,
) -> dict:
    now = utc_now()
    artifact = {
        "id": f"derived-artifact-{uuid4()}",
        "vault_id": vault_id,
        "publication_id": publication_id,
        "artifact_type": artifact_type,
        "artifact_ref": artifact_ref,
        "content_hash": content_hash,
        "byte_length": max(0, int(byte_length)),
        "status": "staging",
        "owner_job_id": owner_job_id,
        "heartbeat_at": now,
        "created_at": now,
        "updated_at": now,
    }
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO derived_state_staged_artifacts (
                id, vault_id, publication_id, artifact_type, artifact_ref,
                content_hash, byte_length, status, owner_job_id, heartbeat_at,
                created_at, updated_at
            )
            VALUES (
                :id, :vault_id, :publication_id, :artifact_type, :artifact_ref,
                :content_hash, :byte_length, :status, :owner_job_id, :heartbeat_at,
                :created_at, :updated_at
            )
            """,
            artifact,
        )
    return artifact


def mark_artifact_status(artifact_id: str, status: str) -> None:
    if status not in {"staging", "verified", "published", "failed", "abandoned", "deleting"}:
        raise ValueError("invalid_artifact_status")
    with connect() as conn:
        conn.execute(
            """
            UPDATE derived_state_staged_artifacts
            SET status = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, utc_now(), artifact_id),
        )


def verify_publication(publication_id: str) -> dict:
    with connect() as conn:
        publication = _publication(conn, publication_id)
        failed = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM derived_state_staged_artifacts
            WHERE publication_id = ? AND status IN ('failed', 'abandoned', 'deleting')
            """,
            (publication_id,),
        ).fetchone()
        if int(failed["count"] or 0) > 0:
            conn.execute(
                "UPDATE derived_state_publications SET status = 'failed' WHERE id = ?",
                (publication_id,),
            )
            raise DerivedStatePublicationError("publication_has_failed_artifacts")
        now = utc_now()
        conn.execute(
            """
            UPDATE derived_state_staged_artifacts
            SET status = 'verified', updated_at = ?
            WHERE publication_id = ? AND status = 'staging'
            """,
            (now, publication_id),
        )
        conn.execute(
            """
            UPDATE derived_state_publications
            SET status = 'verified', verified_at = ?
            WHERE id = ?
            """,
            (now, publication_id),
        )
    publication["status"] = "verified"
    publication["verified_at"] = now
    return publication


def publish_verified(publication_id: str) -> dict:
    with connect() as conn:
        publication = _publication(conn, publication_id)
        if publication["status"] != "verified":
            raise DerivedStatePublicationError("publication_not_verified")
        target = _tuple_from_publication(publication)
        current = query_epoch_snapshot_conn(
            conn,
            publication["vault_id"],
            embedding_model_id=target["embedding_model_id"],
            index_version=target["index_version"],
        )
        now = utc_now()
        conn.execute(
            """
            UPDATE vault_security_metadata
            SET previous_verified_tuple = active_derived_state_tuple,
                active_derived_state_tuple = ?,
                updated_at = ?
            WHERE vault_id = ?
            """,
            (tuple_json(target), now, publication["vault_id"]),
        )
        conn.execute(
            """
            UPDATE derived_state_publications
            SET status = 'published', published_at = ?
            WHERE id = ?
            """,
            (now, publication_id),
        )
        conn.execute(
            """
            UPDATE derived_state_staged_artifacts
            SET status = 'published', updated_at = ?
            WHERE publication_id = ? AND status = 'verified'
            """,
            (now, publication_id),
        )
    return {"previous_tuple": current, "active_tuple": target, "published_at": now}


def rollback_to_previous_tuple(vault_id: str) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT active_derived_state_tuple, previous_verified_tuple FROM vault_security_metadata WHERE vault_id = ?",
            (vault_id,),
        ).fetchone()
        if row is None:
            raise DerivedStateError("vault_security_not_initialized")
        previous = normalize_tuple(row["previous_verified_tuple"])
        active = normalize_tuple(row["active_derived_state_tuple"])
        now = utc_now()
        conn.execute(
            """
            UPDATE vault_security_metadata
            SET active_derived_state_tuple = ?,
                previous_verified_tuple = ?,
                updated_at = ?
            WHERE vault_id = ?
            """,
            (tuple_json(previous), tuple_json(active), now, vault_id),
        )
        conn.execute(
            """
            UPDATE derived_state_publications
            SET rolled_back_at = ?
            WHERE vault_id = ? AND epoch = ?
            """,
            (now, vault_id, active["epoch"]),
        )
    return {"active_tuple": previous, "previous_tuple": active, "rolled_back_at": now}


def _publication(conn, publication_id: str) -> dict:
    row = conn.execute(
        "SELECT * FROM derived_state_publications WHERE id = ?",
        (publication_id,),
    ).fetchone()
    if row is None:
        raise DerivedStatePublicationError("publication_not_found")
    return dict_from_row(row)


def _tuple_from_publication(publication: dict) -> dict:
    return normalize_tuple(
        {
            "normalization_version": publication["normalization_version"],
            "embedding_model_id": publication["embedding_model_id"],
            "index_version": publication["index_version"],
            "extraction_version": publication["extraction_version"],
            "epoch": publication["epoch"],
        }
    )
