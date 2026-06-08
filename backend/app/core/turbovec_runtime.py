from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np

from backend.app.core.config import get_settings
from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.core.derived_state import chunk_eligibility_sql, query_epoch_snapshot_conn
from backend.app.core.encrypted_storage import chunk_from_encrypted_row
from backend.app.core.retrieval_trust import is_low_trust, trust_weight

try:
    from turbovec import IdMapIndex
except ImportError:  # pragma: no cover - optional runtime dependency
    IdMapIndex = None


VECTOR_MANIFEST_VERSION = 1
SIDECAR_DIR_NAME = ".cml/derived-artifacts/vectors"
MANIFEST_NAME = "manifest.json"
INDEX_NAME = "index.tvim"
MANIFEST_STATUSES = {"staging", "published", "unhealthy", "abandoned", "deleting"}
ALLOWED_BIT_WIDTHS = {2, 4}
TURBOVEC_CANDIDATE_MULTIPLIER = 25
TURBOVEC_MIN_CANDIDATES = 50
REBUILD_CHURN_THRESHOLD = 0.15


class TurbovecSidecarError(RuntimeError):
    pass


class TurbovecSidecarUnavailable(TurbovecSidecarError):
    pass


class TurbovecSidecarUnhealthy(TurbovecSidecarError):
    pass


def turbovec_runtime_available() -> bool:
    return IdMapIndex is not None


def vector_backend_policy() -> dict[str, Any]:
    settings = get_settings()
    return {
        "configured_backend": settings.vector_search_backend,
        "turbovec_runtime_available": turbovec_runtime_available(),
        "turbovec_bit_width": int(settings.turbovec_bit_width),
        "turbovec_min_chunk_count": int(settings.turbovec_min_chunk_count),
    }


def stable_u64(value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).digest()[:8]
    candidate = int.from_bytes(digest, "little", signed=False)
    return candidate or 1


def semantic_search_results(
    vault_id: str,
    query_vector: list[float],
    *,
    cluster_id: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    with connect() as conn:
        vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone()
        if vault is None:
            raise KeyError("vault_not_found")
        snapshot = _active_snapshot(conn, vault_id)
        eligible_count = _eligible_chunk_count(conn, vault_id, snapshot, cluster_id=cluster_id)
        backend = _resolve_backend(conn, vault_id, eligible_count=eligible_count)
        if backend == "turbovec":
            try:
                results = _semantic_search_turbovec(
                    conn,
                    vault_id,
                    query_vector,
                    snapshot=snapshot,
                    cluster_id=cluster_id,
                    limit=limit,
                )
                return {"backend": "turbovec", "results": results, "eligible_count": eligible_count}
            except TurbovecSidecarError:
                results = _semantic_search_exact(
                    conn,
                    vault_id,
                    query_vector,
                    snapshot=snapshot,
                    cluster_id=cluster_id,
                    limit=limit,
                )
                return {"backend": "exact_fallback", "results": results, "eligible_count": eligible_count}
        results = _semantic_search_exact(
            conn,
            vault_id,
            query_vector,
            snapshot=snapshot,
            cluster_id=cluster_id,
            limit=limit,
        )
        return {"backend": "exact", "results": results, "eligible_count": eligible_count}


def build_turbovec_sidecar(vault_id: str, *, rebuild_reason: str = "manual") -> dict[str, Any]:
    if not turbovec_runtime_available():
        raise TurbovecSidecarUnavailable("turbovec_runtime_unavailable")
    with connect() as conn:
        snapshot = _active_snapshot(conn, vault_id)
        return _build_turbovec_sidecar_conn(conn, vault_id, snapshot=snapshot, rebuild_reason=rebuild_reason)


def turbovec_sidecar_status(vault_id: str) -> dict[str, Any]:
    with connect() as conn:
        snapshot = _active_snapshot(conn, vault_id)
        return _sidecar_status_for_snapshot(conn, vault_id, snapshot)


def turbovec_sidecar_repair_plan(vault_id: str | None = None) -> dict[str, Any]:
    with connect() as conn:
        if vault_id:
            vault_ids = [vault_id]
        else:
            vault_ids = [str(row["id"]) for row in conn.execute("SELECT id FROM vaults ORDER BY id").fetchall()]
        items = []
        for current_vault_id in vault_ids:
            snapshot = _active_snapshot(conn, current_vault_id)
            item = _sidecar_status_for_snapshot(conn, current_vault_id, snapshot)
            item["needs_rebuild"] = item["status"] in {"missing", "unhealthy", "stale", "corrupt"}
            items.append(item)
    return {
        "runtime_available": turbovec_runtime_available(),
        "configured_backend": get_settings().vector_search_backend,
        "vaults": items,
    }


def repair_turbovec_sidecars(vault_id: str | None = None) -> dict[str, Any]:
    if not turbovec_runtime_available():
        return {
            "runtime_available": False,
            "rebuilt_vaults": [],
            "skipped_vaults": [],
        }
    rebuilt: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    with connect() as conn:
        if vault_id:
            vault_ids = [vault_id]
        else:
            vault_ids = [str(row["id"]) for row in conn.execute("SELECT id FROM vaults ORDER BY id").fetchall()]
        for current_vault_id in vault_ids:
            snapshot = _active_snapshot(conn, current_vault_id)
            status = _sidecar_status_for_snapshot(conn, current_vault_id, snapshot)
            if status["status"] in {"missing", "unhealthy", "stale", "corrupt"}:
                rebuilt.append(
                    _build_turbovec_sidecar_conn(
                        conn,
                        current_vault_id,
                        snapshot=snapshot,
                        rebuild_reason=f"repair:{status['status']}",
                    )
                )
            else:
                skipped.append({"vault_id": current_vault_id, "status": status["status"]})
    return {
        "runtime_available": True,
        "rebuilt_vaults": rebuilt,
        "skipped_vaults": skipped,
    }


def apply_source_delta_to_sidecar(
    conn,
    *,
    vault_id: str,
    snapshot: dict,
    removed_chunk_ids: list[str],
    added_chunks: list[dict[str, str]],
    rebuild_reason: str,
) -> dict[str, Any]:
    if not turbovec_runtime_available():
        return {"applied": False, "reason": "turbovec_runtime_unavailable"}
    manifest, manifest_error = _read_manifest_with_validation(conn, vault_id, snapshot["epoch"])
    if manifest is None:
        return {"applied": False, "reason": "sidecar_missing"}
    if manifest_error:
        return {"applied": False, "reason": "sidecar_corrupt", "error": manifest_error}
    if manifest.get("status") != "published":
        return {"applied": False, "reason": f"sidecar_{manifest.get('status') or 'unknown'}"}
    if not _manifest_matches_snapshot(manifest, snapshot):
        return {"applied": False, "reason": "sidecar_snapshot_mismatch"}
    removed = len({chunk_id for chunk_id in removed_chunk_ids if chunk_id})
    added = len(added_chunks)
    allocated = max(1, int(manifest.get("allocated_slot_count") or manifest.get("chunk_count") or 0))
    threshold = max(1, math.ceil(allocated * REBUILD_CHURN_THRESHOLD))
    if removed + added >= threshold or removed >= threshold or added >= threshold:
        rebuilt = _build_turbovec_sidecar_conn(conn, vault_id, snapshot=snapshot, rebuild_reason=rebuild_reason)
        rebuilt["applied"] = False
        rebuilt["reason"] = "rebuild_threshold"
        return rebuilt
    try:
        index = _load_index(manifest)
        removed_applied = 0
        for chunk_id in removed_chunk_ids:
            if chunk_id and index.remove(stable_u64(chunk_id)):
                removed_applied += 1
        if added_chunks:
            vectors = np.ascontiguousarray(
                np.array([_decode_embedding(str(chunk["embedding"])) for chunk in added_chunks], dtype=np.float32)
            )
            if vectors.size > 0:
                ids = np.ascontiguousarray(
                    np.array([stable_u64(str(chunk["chunk_id"])) for chunk in added_chunks], dtype=np.uint64)
                )
                index.add_with_ids(vectors, ids)
        index.prepare()
        index_path = Path(str(manifest["tvim_path"]))
        _write_index_atomically(index, index_path)
        now = utc_now()
        manifest["chunk_count"] = int(len(index))
        manifest["allocated_slot_count"] = int(len(index))
        manifest["tvim_size_bytes"] = int(index_path.stat().st_size if index_path.exists() else 0)
        manifest["updated_at"] = now
        manifest["last_error"] = ""
        manifest["last_error_at"] = ""
        _write_manifest(_manifest_path(conn, vault_id, snapshot["epoch"]), manifest)
        return {
            "applied": True,
            "removed": removed_applied,
            "added": added,
            "chunk_count": manifest["chunk_count"],
            "allocated_slot_count": manifest["allocated_slot_count"],
        }
    except Exception as exc:
        _mark_manifest_unhealthy(conn, vault_id, snapshot["epoch"], error=str(exc))
        return {"applied": False, "reason": "sidecar_marked_unhealthy", "error": str(exc)}


def maybe_remove_source_chunks_from_sidecar(
    conn,
    *,
    source_id: str,
    vault_id: str,
    rebuild_reason: str,
) -> dict[str, Any]:
    row = conn.execute("SELECT 1 FROM vaults WHERE id = ?", (vault_id,)).fetchone()
    if row is None:
        return {"applied": False, "reason": "vault_missing"}
    snapshot = _active_snapshot(conn, vault_id)
    chunk_rows = conn.execute(
        """
        SELECT id
        FROM source_chunks
        WHERE source_id = ? AND vault_id = ?
        """,
        (source_id, vault_id),
    ).fetchall()
    return apply_source_delta_to_sidecar(
        conn,
        vault_id=vault_id,
        snapshot=snapshot,
        removed_chunk_ids=[str(row["id"]) for row in chunk_rows],
        added_chunks=[],
        rebuild_reason=rebuild_reason,
    )


def _semantic_search_exact(
    conn,
    vault_id: str,
    query_vector: list[float],
    *,
    snapshot: dict,
    cluster_id: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    rows = _hydrate_candidate_rows(
        conn,
        vault_id,
        snapshot=snapshot,
        cluster_id=cluster_id,
        chunk_ids=None,
    )
    scored = _score_rows(rows, query_vector)
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:limit]


def _semantic_search_turbovec(
    conn,
    vault_id: str,
    query_vector: list[float],
    *,
    snapshot: dict,
    cluster_id: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    manifest, manifest_error = _read_manifest_with_validation(conn, vault_id, snapshot["epoch"])
    if manifest is None:
        raise TurbovecSidecarUnavailable("sidecar_missing")
    if manifest_error:
        raise TurbovecSidecarUnavailable(f"sidecar_corrupt:{manifest_error}")
    if manifest.get("status") != "published":
        raise TurbovecSidecarUnhealthy(f"sidecar_{manifest.get('status') or 'unknown'}")
    if not _manifest_matches_snapshot(manifest, snapshot):
        raise TurbovecSidecarUnavailable("sidecar_snapshot_mismatch")
    allowlist_chunk_ids = _eligible_chunk_ids(conn, vault_id, snapshot=snapshot, cluster_id=cluster_id)
    if not allowlist_chunk_ids:
        return []
    try:
        index = _load_index(manifest)
        candidate_k = min(
            len(allowlist_chunk_ids),
            max(limit * TURBOVEC_CANDIDATE_MULTIPLIER, TURBOVEC_MIN_CANDIDATES),
        )
        query = np.ascontiguousarray(np.array([query_vector], dtype=np.float32))
        allowlist = np.ascontiguousarray(np.array([stable_u64(chunk_id) for chunk_id in allowlist_chunk_ids], dtype=np.uint64))
        _scores, ids = index.search(query, k=candidate_k, allowlist=allowlist)
    except Exception as exc:
        _mark_manifest_unhealthy(conn, vault_id, snapshot["epoch"], error=str(exc))
        raise TurbovecSidecarUnhealthy("sidecar_search_failed") from exc
    candidate_ids = [chunk_id for chunk_id in (_stable_id_lookup(allowlist_chunk_ids).get(int(value)) for value in ids[0].tolist()) if chunk_id]
    if not candidate_ids:
        return []
    rows = _hydrate_candidate_rows(
        conn,
        vault_id,
        snapshot=snapshot,
        cluster_id=cluster_id,
        chunk_ids=candidate_ids,
    )
    found_ids = {str(row["chunk_id"]) for row in rows}
    missing = [chunk_id for chunk_id in candidate_ids if chunk_id not in found_ids]
    if missing:
        _mark_manifest_unhealthy(conn, vault_id, snapshot["epoch"], error="sidecar_candidate_drift")
        raise TurbovecSidecarUnhealthy("sidecar_candidate_drift")
    scored = _score_rows(rows, query_vector)
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:limit]


def _score_rows(rows: list[dict[str, Any]], query_vector: list[float]) -> list[dict[str, Any]]:
    scored = []
    for row in rows:
        raw_score = _cosine_similarity(query_vector, _decode_embedding(str(row["embedding"] or "")))
        score = raw_score * trust_weight(row)
        if score <= 0:
            continue
        scored.append(
            {
                "source_id": row["source_id"],
                "source_title": row["source_title"],
                "source_type": row["source_type"],
                "cluster_id": row["cluster_id"],
                "chunk_id": row["chunk_id"],
                "page_id": row["page_id"],
                "page_number": row["page_number"],
                "chunk_index": row["chunk_index"],
                "snippet": row["text"],
                "provenance": row["provenance"],
                "trust_tier": row["trust_tier"],
                "security_labels": row["security_labels"],
                "low_trust": is_low_trust(row),
                "raw_score": round(raw_score, 4),
                "score": round(score, 4),
            }
        )
    return scored


def _eligible_chunk_count(conn, vault_id: str, snapshot: dict, *, cluster_id: str | None) -> int:
    params: list[Any] = [vault_id]
    cluster_clause = ""
    if cluster_id:
        cluster_clause = "AND chunks.cluster_id = ?"
        params.append(cluster_id)
    tuple_clause, tuple_params = chunk_eligibility_sql("chunks", snapshot)
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM source_chunks chunks
        JOIN sources ON sources.id = chunks.source_id
        WHERE chunks.vault_id = ?
          AND sources.deleted_at IS NULL
          {cluster_clause}
          {tuple_clause}
        """,
        [*params, *tuple_params],
    ).fetchone()
    return int(row["count"] if row is not None else 0)


def _eligible_chunk_ids(conn, vault_id: str, *, snapshot: dict, cluster_id: str | None) -> list[str]:
    params: list[Any] = [vault_id]
    cluster_clause = ""
    if cluster_id:
        cluster_clause = "AND chunks.cluster_id = ?"
        params.append(cluster_id)
    tuple_clause, tuple_params = chunk_eligibility_sql("chunks", snapshot)
    rows = conn.execute(
        f"""
        SELECT chunks.id
        FROM source_chunks chunks
        JOIN sources ON sources.id = chunks.source_id
        WHERE chunks.vault_id = ?
          AND sources.deleted_at IS NULL
          {cluster_clause}
          {tuple_clause}
        """,
        [*params, *tuple_params],
    ).fetchall()
    return [str(row["id"]) for row in rows]


def _hydrate_candidate_rows(
    conn,
    vault_id: str,
    *,
    snapshot: dict,
    cluster_id: str | None,
    chunk_ids: list[str] | None,
) -> list[dict[str, Any]]:
    params: list[Any] = [vault_id]
    cluster_clause = ""
    if cluster_id:
        cluster_clause = "AND chunks.cluster_id = ?"
        params.append(cluster_id)
    tuple_clause, tuple_params = chunk_eligibility_sql("chunks", snapshot)
    chunk_filter = ""
    if chunk_ids is not None:
        if not chunk_ids:
            return []
        placeholders = ", ".join("?" for _ in chunk_ids)
        chunk_filter = f"AND chunks.id IN ({placeholders})"
        params.extend(chunk_ids)
    rows = conn.execute(
        f"""
        SELECT
            chunks.id AS chunk_id,
            chunks.source_id,
            chunks.vault_id,
            chunks.page_id,
            chunks.cluster_id,
            chunks.chunk_index,
            chunks.text,
            chunks.embedding,
            sources.title AS source_title,
            sources.source_type,
            sources.provenance,
            sources.trust_tier,
            sources.security_labels,
            pages.page_number
        FROM source_chunks chunks
        JOIN sources ON sources.id = chunks.source_id
        LEFT JOIN source_pages pages ON pages.id = chunks.page_id
        WHERE chunks.vault_id = ?
          AND sources.deleted_at IS NULL
          {cluster_clause}
          {chunk_filter}
          {tuple_clause}
        """,
        [*params, *tuple_params],
    ).fetchall()
    return [chunk_from_encrypted_row(conn, row) for row in rows]


def _build_turbovec_sidecar_conn(
    conn,
    vault_id: str,
    *,
    snapshot: dict,
    rebuild_reason: str,
) -> dict[str, Any]:
    if not turbovec_runtime_available():
        raise TurbovecSidecarUnavailable("turbovec_runtime_unavailable")
    epoch_dir = _epoch_dir(conn, vault_id, snapshot["epoch"])
    epoch_dir.mkdir(parents=True, exist_ok=True)
    index_path = epoch_dir / INDEX_NAME
    manifest_path = epoch_dir / MANIFEST_NAME
    bit_width = int(get_settings().turbovec_bit_width)
    chunk_rows = _chunk_vector_rows(conn, vault_id, snapshot=snapshot)
    manifest = _base_manifest(vault_id, snapshot, index_path=index_path, bit_width=bit_width, rebuild_reason=rebuild_reason)
    manifest["status"] = "staging"
    manifest["chunk_count"] = len(chunk_rows)
    manifest["allocated_slot_count"] = len(chunk_rows)
    _write_manifest(manifest_path, manifest)
    try:
        vectors = np.ascontiguousarray(
            np.array([_decode_embedding(str(row["embedding"] or "")) for row in chunk_rows], dtype=np.float32)
        )
        if chunk_rows and (vectors.shape[1] <= 0 or vectors.shape[1] % 8 != 0):
            raise TurbovecSidecarError(f"invalid_embedding_dimensions_for_turbovec:{vectors.shape[1]}")
        if chunk_rows:
            ids = np.ascontiguousarray(np.array([stable_u64(str(row["id"])) for row in chunk_rows], dtype=np.uint64))
            index = IdMapIndex(dim=vectors.shape[1], bit_width=bit_width)
            index.add_with_ids(vectors, ids)
        else:
            index = IdMapIndex(dim=int(get_settings().embedding_dimensions), bit_width=bit_width)
        index.prepare()
        _write_index_atomically(index, index_path)
        load_started = time.perf_counter()
        IdMapIndex.load(str(index_path))
        cold_load_seconds = round(time.perf_counter() - load_started, 4)
        published = dict(manifest)
        published["status"] = "published"
        published["updated_at"] = utc_now()
        published["chunk_count"] = int(len(index))
        published["allocated_slot_count"] = int(len(index))
        published["tvim_size_bytes"] = int(index_path.stat().st_size if index_path.exists() else 0)
        published["cold_load_seconds"] = cold_load_seconds
        _write_manifest(manifest_path, published)
        return {
            "vault_id": vault_id,
            "derived_state_epoch": snapshot["epoch"],
            "chunk_count": published["chunk_count"],
            "allocated_slot_count": published["allocated_slot_count"],
            "status": published["status"],
            "tvim_path": str(index_path),
            "tvim_size_bytes": published["tvim_size_bytes"],
            "cold_load_seconds": cold_load_seconds,
            "rebuild_reason": rebuild_reason,
        }
    except Exception as exc:
        failed = dict(manifest)
        failed["status"] = "unhealthy"
        failed["last_error"] = str(exc)[:4000]
        failed["last_error_at"] = utc_now()
        failed["updated_at"] = failed["last_error_at"]
        _write_manifest(manifest_path, failed)
        if isinstance(exc, TurbovecSidecarError):
            raise
        raise TurbovecSidecarError(str(exc)) from exc


def _chunk_vector_rows(conn, vault_id: str, *, snapshot: dict) -> list[dict[str, Any]]:
    tuple_clause, tuple_params = chunk_eligibility_sql("chunks", snapshot)
    rows = conn.execute(
        f"""
        SELECT chunks.id, chunks.embedding
        FROM source_chunks chunks
        JOIN sources ON sources.id = chunks.source_id
        WHERE chunks.vault_id = ?
          AND sources.deleted_at IS NULL
          {tuple_clause}
        ORDER BY chunks.created_at ASC
        """,
        [vault_id, *tuple_params],
    ).fetchall()
    return [dict_from_row(row) for row in rows]


def _sidecar_status_for_snapshot(conn, vault_id: str, snapshot: dict) -> dict[str, Any]:
    manifest, manifest_error = _read_manifest_with_validation(conn, vault_id, snapshot["epoch"])
    if manifest is None:
        return {
            "vault_id": vault_id,
            "derived_state_epoch": snapshot["epoch"],
            "status": "missing",
            "manifest_path": str(_manifest_path(conn, vault_id, snapshot["epoch"])),
        }
    index_path = Path(str(manifest.get("tvim_path") or ""))
    if manifest_error:
        status = "corrupt"
    elif manifest.get("status") == "unhealthy":
        status = "unhealthy"
    elif not _manifest_matches_snapshot(manifest, snapshot):
        status = "stale"
    elif not index_path.exists():
        status = "corrupt"
    else:
        status = str(manifest.get("status") or "unknown")
    return {
        "vault_id": vault_id,
        "derived_state_epoch": snapshot["epoch"],
        "status": status,
        "manifest_path": str(_manifest_path(conn, vault_id, snapshot["epoch"])),
        "tvim_path": str(index_path),
        "chunk_count": int(manifest.get("chunk_count") or 0),
        "allocated_slot_count": int(manifest.get("allocated_slot_count") or 0),
        "last_error": str(manifest_error or manifest.get("last_error") or ""),
        "last_error_at": str(manifest.get("last_error_at") or ""),
    }


def _load_index(manifest: dict[str, Any]):
    if IdMapIndex is None:
        raise TurbovecSidecarUnavailable("turbovec_runtime_unavailable")
    index_path = Path(str(manifest["tvim_path"]))
    if not index_path.exists():
        raise TurbovecSidecarUnavailable("sidecar_index_missing")
    return IdMapIndex.load(str(index_path))


def _write_index_atomically(index, index_path: Path) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = index_path.with_suffix(index_path.suffix + ".tmp")
    if temp_path.exists():
        temp_path.unlink()
    index.write(str(temp_path))
    temp_path.replace(index_path)


def _mark_manifest_unhealthy(conn, vault_id: str, epoch: int, *, error: str) -> None:
    manifest, manifest_error = _read_manifest_with_validation(conn, vault_id, epoch)
    if manifest is None:
        return
    manifest["status"] = "unhealthy"
    manifest["last_error"] = str(manifest_error or error)[:4000]
    manifest["last_error_at"] = utc_now()
    manifest["updated_at"] = manifest["last_error_at"]
    _write_manifest(_manifest_path(conn, vault_id, epoch), manifest)


def _active_snapshot(conn, vault_id: str) -> dict:
    return query_epoch_snapshot_conn(
        conn,
        vault_id,
        embedding_model_id=_active_embedding_model_id(),
        index_version="v1",
    )


def _active_embedding_model_id() -> str:
    from backend.app.core.embeddings import active_embedding_model_id

    return active_embedding_model_id()


def _decode_embedding(raw: str) -> list[float]:
    from backend.app.core.embeddings import decode_embedding

    return decode_embedding(raw)


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    from backend.app.core.embeddings import cosine_similarity

    return cosine_similarity(left, right)


def _resolve_backend(conn, vault_id: str, *, eligible_count: int) -> str:
    settings = get_settings()
    mode = str(settings.vector_search_backend or "exact").lower()
    if mode == "exact":
        return "exact"
    if mode == "turbovec":
        snapshot = _active_snapshot(conn, vault_id)
        status = _sidecar_status_for_snapshot(conn, vault_id, snapshot)
        return "turbovec" if status["status"] == "published" else "exact"
    if mode == "auto":
        if eligible_count < int(settings.turbovec_min_chunk_count):
            return "exact"
        snapshot = _active_snapshot(conn, vault_id)
        status = _sidecar_status_for_snapshot(conn, vault_id, snapshot)
        return "turbovec" if status["status"] == "published" else "exact"
    return "exact"


def _epoch_dir(conn, vault_id: str, epoch: int) -> Path:
    return _sidecar_root(conn, vault_id) / f"epoch-{int(epoch)}"


def _manifest_path(conn, vault_id: str, epoch: int) -> Path:
    return _epoch_dir(conn, vault_id, epoch) / MANIFEST_NAME


def _sidecar_root(conn, vault_id: str) -> Path:
    row = conn.execute("SELECT path FROM vaults WHERE id = ?", (vault_id,)).fetchone()
    if row is None:
        raise TurbovecSidecarUnavailable("vault_not_found")
    root = Path(str(row["path"] or get_settings().data_dir))
    return root / SIDECAR_DIR_NAME


def _read_manifest_with_validation(conn, vault_id: str, epoch: int) -> tuple[dict[str, Any] | None, str | None]:
    path = _manifest_path(conn, vault_id, epoch)
    if not path.exists():
        return None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "manifest_json_invalid"
    if not isinstance(payload, dict):
        return None, "manifest_not_object"
    error = _manifest_validation_error(conn, vault_id, epoch, payload)
    return payload, error


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _base_manifest(
    vault_id: str,
    snapshot: dict,
    *,
    index_path: Path,
    bit_width: int,
    rebuild_reason: str,
) -> dict[str, Any]:
    now = utc_now()
    return {
        "manifest_version": VECTOR_MANIFEST_VERSION,
        "vault_id": vault_id,
        "derived_state_epoch": int(snapshot["epoch"]),
        "embedding_model_id": str(snapshot["embedding_model_id"]),
        "index_version": str(snapshot["index_version"]),
        "normalization_version": str(snapshot["normalization_version"]),
        "extraction_version": str(snapshot["extraction_version"]),
        "created_at": now,
        "updated_at": now,
        "chunk_count": 0,
        "allocated_slot_count": 0,
        "status": "staging",
        "tvim_path": str(index_path),
        "tvim_size_bytes": 0,
        "bit_width": int(bit_width),
        "rebuild_reason": str(rebuild_reason),
        "last_error": "",
        "last_error_at": "",
    }


def _manifest_validation_error(conn, vault_id: str, epoch: int, manifest: dict[str, Any]) -> str | None:
    if int(manifest.get("manifest_version") or 0) != VECTOR_MANIFEST_VERSION:
        return "manifest_version_mismatch"
    if str(manifest.get("vault_id") or "") != vault_id:
        return "manifest_vault_id_mismatch"
    if int(manifest.get("derived_state_epoch") or 0) != int(epoch):
        return "manifest_epoch_mismatch"
    if str(manifest.get("status") or "") not in MANIFEST_STATUSES:
        return "manifest_status_invalid"
    if int(manifest.get("bit_width") or 0) not in ALLOWED_BIT_WIDTHS:
        return "manifest_bit_width_invalid"
    if int(manifest.get("chunk_count") or 0) < 0:
        return "manifest_chunk_count_invalid"
    if int(manifest.get("allocated_slot_count") or 0) < 0:
        return "manifest_allocated_slot_count_invalid"
    if not str(manifest.get("embedding_model_id") or "").strip():
        return "manifest_embedding_model_missing"
    if not str(manifest.get("index_version") or "").strip():
        return "manifest_index_version_missing"
    if not str(manifest.get("normalization_version") or "").strip():
        return "manifest_normalization_version_missing"
    if not str(manifest.get("extraction_version") or "").strip():
        return "manifest_extraction_version_missing"
    raw_index_path = str(manifest.get("tvim_path") or "").strip()
    if not raw_index_path:
        return "manifest_tvim_path_missing"
    try:
        resolved_index_path = Path(raw_index_path).resolve()
    except OSError:
        return "manifest_tvim_path_invalid"
    expected_index_path = (_epoch_dir(conn, vault_id, epoch) / INDEX_NAME).resolve()
    if resolved_index_path != expected_index_path:
        return "manifest_tvim_path_outside_epoch_dir"
    return None


def _manifest_matches_snapshot(manifest: dict[str, Any], snapshot: dict) -> bool:
    return (
        str(manifest.get("vault_id") or "") != ""
        and int(manifest.get("derived_state_epoch") or 0) == int(snapshot["epoch"])
        and str(manifest.get("embedding_model_id") or "") == str(snapshot["embedding_model_id"])
        and str(manifest.get("index_version") or "") == str(snapshot["index_version"])
        and str(manifest.get("normalization_version") or "") == str(snapshot["normalization_version"])
        and str(manifest.get("extraction_version") or "") == str(snapshot["extraction_version"])
        and str(manifest.get("status") or "") in MANIFEST_STATUSES
    )


def _stable_id_lookup(chunk_ids: list[str]) -> dict[int, str]:
    return {stable_u64(chunk_id): chunk_id for chunk_id in chunk_ids}
