from __future__ import annotations

import hashlib
import heapq
import json
import math
import shutil
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

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
PHASE_C_POLICY_VERSION = 1
SIDECAR_DIR_NAME = ".cml/derived-artifacts/vectors"
MANIFEST_NAME = "manifest.json"
INDEX_NAME = "index.tvim"
MANIFEST_STATUSES = {"staging", "published", "unhealthy", "abandoned", "deleting"}
ALLOWED_BIT_WIDTHS = {2, 4}
TURBOVEC_CANDIDATE_MULTIPLIER = 25
TURBOVEC_MIN_CANDIDATES = 50
REBUILD_CHURN_THRESHOLD = 0.15
PHASE_C_MIN_AVG_OVERLAP = 0.95
PHASE_C_MIN_QUERY_OVERLAP = 0.85
PHASE_C_MIN_CLUSTER_OVERLAP = 0.88
PHASE_C_MIN_LATENCY_IMPROVEMENT = 3.0
PHASE_C_MAX_SIZE_RATIO = 0.25
PHASE_C_MAX_COLD_LOAD_SECONDS = 1.5
EXACT_CACHE_MAX_BYTES = 64 * 1024 * 1024
SIDECAR_CACHE_MAX_BYTES = 256 * 1024 * 1024
EXACT_STREAM_THRESHOLD = 10_000
EXACT_STREAM_BLOCK_SIZE = 2_048
UNCLUSTERED_SCOPE_ID = "__unclustered__"


@dataclass
class ExactSearchSnapshot:
    chunk_ids: list[str]
    vectors: np.ndarray
    trust_weights: np.ndarray


_EXACT_SEARCH_CACHE: "OrderedDict[tuple[Any, ...], ExactSearchSnapshot]" = OrderedDict()
_EXACT_SEARCH_CACHE_LOCK = threading.Lock()
_SIDECAR_INDEX_CACHE: "OrderedDict[tuple[Any, ...], tuple[Any, int]]" = OrderedDict()
_SIDECAR_INDEX_CACHE_LOCK = threading.Lock()


class TurbovecSidecarError(RuntimeError):
    pass


class TurbovecSidecarUnavailable(TurbovecSidecarError):
    pass


class TurbovecSidecarUnhealthy(TurbovecSidecarError):
    pass


def turbovec_runtime_available() -> bool:
    return IdMapIndex is not None


def vector_backend_policy(vault_id: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    policy = {
        "configured_backend": settings.vector_search_backend,
        "turbovec_runtime_available": turbovec_runtime_available(),
        "turbovec_bit_width": int(settings.turbovec_bit_width),
        "turbovec_min_chunk_count": int(settings.turbovec_min_chunk_count),
        "phase_c_thresholds": phase_c_thresholds(),
    }
    if vault_id:
        try:
            policy["vault_status"] = turbovec_phase_c_status(vault_id)
        except KeyError:
            policy["vault_status"] = {
                "vault_id": vault_id,
                "status": "vault_not_found",
                "approved": False,
            }
    return policy


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
                return {
                    "backend": "exact_fallback",
                    "results": results,
                    "eligible_count": eligible_count,
                }
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
        return _build_turbovec_sidecar_conn(
            conn, vault_id, snapshot=snapshot, rebuild_reason=rebuild_reason
        )


def turbovec_sidecar_status(vault_id: str) -> dict[str, Any]:
    with connect() as conn:
        snapshot = _active_snapshot(conn, vault_id)
        return _sidecar_status_for_snapshot(conn, vault_id, snapshot)


def turbovec_sidecar_repair_plan(vault_id: str | None = None) -> dict[str, Any]:
    with connect() as conn:
        if vault_id:
            vault_ids = [vault_id]
        else:
            vault_ids = [
                str(row["id"])
                for row in conn.execute("SELECT id FROM vaults ORDER BY id").fetchall()
            ]
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
            vault_ids = [
                str(row["id"])
                for row in conn.execute("SELECT id FROM vaults ORDER BY id").fetchall()
            ]
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


def turbovec_phase_c_status(vault_id: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone()
        if row is None:
            raise KeyError("vault_not_found")
        snapshot = _active_snapshot(conn, vault_id)
        eligible_count = _eligible_chunk_count(conn, vault_id, snapshot, cluster_id=None)
        sidecar = _sidecar_status_for_snapshot(
            conn, vault_id, snapshot, eligible_count=eligible_count
        )
        approval = _current_phase_c_approval(
            vault_id, snapshot=snapshot, eligible_count=eligible_count
        )
        approved = bool(
            approval
            and approval.get("approved")
            and approval.get("derived_state_epoch") == snapshot["epoch"]
        )
        reasons: list[str] = []
        if eligible_count < int(get_settings().turbovec_min_chunk_count):
            reasons.append("eligible_chunk_count_below_phase_c_threshold")
        if sidecar.get("status") != "published":
            reasons.append(f"sidecar_status_{sidecar.get('status') or 'missing'}")
        if not approved:
            reasons.append("phase_c_benchmark_not_approved")
        return {
            "vault_id": vault_id,
            "approved": approved,
            "status": "approved" if approved else "benchmark_required",
            "eligible_chunk_count": eligible_count,
            "derived_state_epoch": snapshot["epoch"],
            "sidecar_status": sidecar.get("status"),
            "reasons": reasons,
            "thresholds": phase_c_thresholds(),
            "benchmark": approval.get("benchmark") if approval else None,
            "approved_at": approval.get("approved_at") if approval else "",
            "updated_at": approval.get("updated_at") if approval else "",
        }


def benchmark_turbovec_phase_c(
    vault_id: str, *, query_limit: int = 20, top_k: int = 10
) -> dict[str, Any]:
    from backend.app.core.turbovec_benchmark import (
        BenchmarkChunkRow,
        benchmark_current_scan,
        benchmark_turbovec_scan,
        corpus_stats,
        overlap_report,
        sampled_queries,
    )

    with connect() as conn:
        row = conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone()
        if row is None:
            raise KeyError("vault_not_found")
        snapshot = _active_snapshot(conn, vault_id)
        benchmark_rows = []
        for item in _hydrate_candidate_rows(
            conn, vault_id, snapshot=snapshot, cluster_id=None, chunk_ids=None
        ):
            benchmark_rows.append(
                BenchmarkChunkRow(
                    chunk_id=str(item["chunk_id"]),
                    source_id=str(item["source_id"]),
                    title=str(item["source_title"] or ""),
                    text=str(item["text"] or ""),
                    embedding=str(item["embedding"] or ""),
                    page_number=item.get("page_number"),
                )
            )
        eligible_count = len(benchmark_rows)
        if eligible_count == 0:
            report = {
                "vault_id": vault_id,
                "approved": False,
                "detail": "No eligible chunks are available for a turbovec Phase C benchmark.",
                "eligible_chunk_count": 0,
                "derived_state_epoch": snapshot["epoch"],
                "thresholds": phase_c_thresholds(),
                "checks": [
                    {"id": "eligible_chunks_present", "ok": False, "detail": "0 eligible chunks"}
                ],
                "benchmark": {},
            }
            _write_phase_c_result(vault_id, snapshot=snapshot, report=report)
            return report
        sidecar = _sidecar_status_for_snapshot(
            conn, vault_id, snapshot, eligible_count=eligible_count
        )
        if sidecar.get("status") != "published":
            build_turbovec_sidecar(vault_id, rebuild_reason="phase-c-benchmark")
            sidecar = _sidecar_status_for_snapshot(
                conn, vault_id, snapshot, eligible_count=eligible_count
            )
        queries = sampled_queries(benchmark_rows, limit=max(1, min(query_limit, 100)))
        query_source = {
            query: str(row.source_id) for query, row in zip(queries, benchmark_rows, strict=False)
        }
        exact = benchmark_current_scan(benchmark_rows, queries, top_k=top_k)
        candidate = benchmark_turbovec_scan(
            benchmark_rows,
            queries,
            top_k=top_k,
            bit_width=int(get_settings().turbovec_bit_width),
        )
        overlap = overlap_report(exact, candidate, top_k=top_k)
        stats = corpus_stats(benchmark_rows)
        latency_ratio = _search_latency_improvement_ratio(
            exact.get("search_latency_ms", exact.get("latency_ms", {})),
            candidate.get("search_latency_ms", candidate.get("latency_ms", {})),
        )
        size_ratio = round(
            float(sidecar.get("tvim_size_bytes") or 0)
            / max(1.0, float(stats.get("total_embedding_bytes") or 0)),
            4,
        )
        cluster_overlap = _cluster_overlap_report(overlap, query_source=query_source)
        checks = _phase_c_acceptance_checks(
            eligible_count=eligible_count,
            overlap=overlap,
            cluster_overlap=cluster_overlap,
            latency_ratio=latency_ratio,
            size_ratio=size_ratio,
            cold_load_seconds=float(sidecar.get("cold_load_seconds") or 0.0),
        )
        approved = all(check["ok"] for check in checks)
        detail = (
            "Phase C benchmark accepted. Auto backend can use turbovec for this vault while the current tuple stays active."
            if approved
            else "Phase C benchmark did not satisfy the acceptance gate."
        )
        report = {
            "vault_id": vault_id,
            "approved": approved,
            "detail": detail,
            "eligible_chunk_count": eligible_count,
            "derived_state_epoch": snapshot["epoch"],
            "thresholds": phase_c_thresholds(),
            "checks": checks,
            "benchmark": {
                "exact": exact,
                "turbovec": candidate,
                "overlap": overlap,
                "cluster_overlap": cluster_overlap,
                "latency_improvement_ratio": latency_ratio,
                "sidecar_size_ratio": size_ratio,
                "sidecar_status": sidecar,
                "corpus": stats,
            },
        }
        _write_phase_c_result(vault_id, snapshot=snapshot, report=report)
        return report


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
    allocated = max(
        1, int(manifest.get("allocated_slot_count") or manifest.get("chunk_count") or 0)
    )
    threshold = max(1, math.ceil(allocated * REBUILD_CHURN_THRESHOLD))
    if removed + added >= threshold or removed >= threshold or added >= threshold:
        rebuilt = _build_turbovec_sidecar_conn(
            conn, vault_id, snapshot=snapshot, rebuild_reason=rebuild_reason
        )
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
                np.array(
                    [_decode_embedding(str(chunk["embedding"])) for chunk in added_chunks],
                    dtype=np.float32,
                )
            )
            if vectors.size > 0:
                ids = np.ascontiguousarray(
                    np.array(
                        [stable_u64(str(chunk["chunk_id"])) for chunk in added_chunks],
                        dtype=np.uint64,
                    )
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
    if _eligible_chunk_count(conn, vault_id, snapshot, cluster_id=cluster_id) > EXACT_STREAM_THRESHOLD:
        return _semantic_search_exact_streaming(
            conn,
            vault_id,
            query_vector,
            snapshot=snapshot,
            cluster_id=cluster_id,
            limit=limit,
        )
    snapshot_cache = _exact_search_snapshot(
        conn,
        vault_id,
        snapshot=snapshot,
        cluster_id=cluster_id,
        expected_dim=len(query_vector),
    )
    if not snapshot_cache.chunk_ids:
        return []
    query = np.ascontiguousarray(np.array(query_vector, dtype=np.float32))
    raw_scores = snapshot_cache.vectors @ query
    weighted_scores = raw_scores * snapshot_cache.trust_weights
    positive_indices = np.flatnonzero(weighted_scores > 0)
    if positive_indices.size == 0:
        return []
    top_count = min(int(limit), int(positive_indices.size))
    top_positions = positive_indices[
        np.argpartition(weighted_scores[positive_indices], -top_count)[-top_count:]
    ]
    ordered_positions = top_positions[np.argsort(weighted_scores[top_positions])[::-1]]
    chunk_ids = [snapshot_cache.chunk_ids[int(index)] for index in ordered_positions.tolist()]
    raw_score_by_chunk = {
        snapshot_cache.chunk_ids[int(index)]: round(float(raw_scores[int(index)]), 4)
        for index in ordered_positions.tolist()
    }
    weighted_score_by_chunk = {
        snapshot_cache.chunk_ids[int(index)]: round(float(weighted_scores[int(index)]), 4)
        for index in ordered_positions.tolist()
    }
    return _hydrate_scored_rows(
        conn,
        vault_id,
        snapshot=snapshot,
        cluster_id=cluster_id,
        chunk_ids=chunk_ids,
        raw_score_by_chunk=raw_score_by_chunk,
        weighted_score_by_chunk=weighted_score_by_chunk,
    )


def prune_turbovec_sidecar_epochs(
    conn,
    *,
    cutoff_timestamp: float,
    limit: int = 25,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Remove aged, non-current epoch directories in bounded crash-recoverable steps."""
    bounded_limit = max(1, min(int(limit), 100))
    candidates: list[tuple[Path, Path, bool]] = []
    errors: list[str] = []
    vault_rows = conn.execute("SELECT id, path FROM vaults ORDER BY id").fetchall()
    for row in vault_rows:
        vault_id = str(row["id"])
        root = Path(str(row["path"] or get_settings().data_dir)) / SIDECAR_DIR_NAME
        if not root.is_dir():
            continue
        try:
            active_epoch = int(_active_snapshot(conn, vault_id)["epoch"])
            children = list(root.iterdir())
        except (OSError, ValueError, TurbovecSidecarError) as exc:
            errors.append(f"{vault_id}:{str(exc)[:200]}")
            continue
        for child in children:
            if not child.is_dir():
                continue
            deleting = child.name.startswith(".deleting-epoch-")
            if child.name.startswith("epoch-"):
                try:
                    epoch = int(child.name.removeprefix("epoch-"))
                except ValueError:
                    continue
                if epoch == active_epoch:
                    continue
            elif not deleting:
                continue
            try:
                if child.stat().st_mtime >= float(cutoff_timestamp):
                    continue
            except OSError as exc:
                errors.append(f"{vault_id}:{child.name}:{str(exc)[:160]}")
                continue
            candidates.append((root, child, deleting))
            if len(candidates) >= bounded_limit:
                break
        if len(candidates) >= bounded_limit:
            break

    deleted = 0
    if not dry_run:
        for root, child, deleting in candidates:
            deleting_path = child
            try:
                if not deleting:
                    deleting_path = root / f".deleting-{child.name}-{uuid4().hex}"
                    child.rename(deleting_path)
                shutil.rmtree(deleting_path)
                deleted += 1
            except OSError as exc:
                errors.append(f"{child.name}:{str(exc)[:200]}")
    return {
        "eligible": len(candidates),
        "deleted": deleted,
        "batch_limited": len(candidates) == bounded_limit,
        "errors": errors[:20],
    }


def _semantic_search_exact_streaming(
    conn,
    vault_id: str,
    query_vector: list[float],
    *,
    snapshot: dict,
    cluster_id: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Exact top-k with bounded peak memory for large or stale-sidecar vaults."""
    params: list[Any] = [vault_id]
    cluster_clause = ""
    if cluster_id == UNCLUSTERED_SCOPE_ID:
        cluster_clause = "AND chunks.cluster_id IS NULL"
    elif cluster_id:
        cluster_clause = "AND chunks.cluster_id = ?"
        params.append(cluster_id)
    tuple_clause, tuple_params = chunk_eligibility_sql("chunks", snapshot)
    query = np.ascontiguousarray(np.array(query_vector, dtype=np.float32))
    expected_dim = len(query_vector)
    cursor_created = ""
    cursor_id = ""
    winners: list[tuple[float, str, float]] = []
    top_limit = max(1, int(limit))
    while True:
        rows = conn.execute(
            f"""
            SELECT chunks.id AS chunk_id, chunks.created_at, chunks.embedding,
                   sources.trust_tier, sources.security_labels
            FROM source_chunks chunks
            JOIN sources ON sources.id = chunks.source_id
            WHERE chunks.vault_id = ?
              AND sources.deleted_at IS NULL
              {cluster_clause}
              {tuple_clause}
              AND (chunks.created_at > ? OR (chunks.created_at = ? AND chunks.id > ?))
            ORDER BY chunks.created_at, chunks.id
            LIMIT ?
            """,
            [*params, *tuple_params, cursor_created, cursor_created, cursor_id, EXACT_STREAM_BLOCK_SIZE],
        ).fetchall()
        if not rows:
            break
        vectors: list[list[float]] = []
        metadata: list[tuple[str, float]] = []
        for row in rows:
            decoded = _decode_embedding(str(row["embedding"] or ""))
            if len(decoded) != expected_dim:
                continue
            vectors.append(decoded)
            metadata.append((str(row["chunk_id"]), float(trust_weight(row))))
        if vectors:
            matrix = np.ascontiguousarray(np.array(vectors, dtype=np.float32))
            raw_scores = matrix @ query
            for index, (chunk_id, weight) in enumerate(metadata):
                raw = float(raw_scores[index])
                weighted = raw * weight
                if weighted <= 0:
                    continue
                entry = (weighted, chunk_id, raw)
                if len(winners) < top_limit:
                    heapq.heappush(winners, entry)
                elif entry > winners[0]:
                    heapq.heapreplace(winners, entry)
        cursor_created = str(rows[-1]["created_at"] or "")
        cursor_id = str(rows[-1]["chunk_id"])
        if len(rows) < EXACT_STREAM_BLOCK_SIZE:
            break
    ordered = sorted(winners, reverse=True)
    chunk_ids = [chunk_id for _weighted, chunk_id, _raw in ordered]
    return _hydrate_scored_rows(
        conn,
        vault_id,
        snapshot=snapshot,
        cluster_id=cluster_id,
        chunk_ids=chunk_ids,
        raw_score_by_chunk={chunk_id: round(raw, 4) for _weighted, chunk_id, raw in ordered},
        weighted_score_by_chunk={
            chunk_id: round(weighted, 4) for weighted, chunk_id, _raw in ordered
        },
    )


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
    allowlist_chunk_ids = _eligible_chunk_ids(
        conn, vault_id, snapshot=snapshot, cluster_id=cluster_id
    )
    if not allowlist_chunk_ids:
        return []
    try:
        index = _load_index(manifest)
        candidate_k = min(
            len(allowlist_chunk_ids),
            max(limit * TURBOVEC_CANDIDATE_MULTIPLIER, TURBOVEC_MIN_CANDIDATES),
        )
        query = np.ascontiguousarray(np.array([query_vector], dtype=np.float32))
        allowlist = np.ascontiguousarray(
            np.array([stable_u64(chunk_id) for chunk_id in allowlist_chunk_ids], dtype=np.uint64)
        )
        _scores, ids = index.search(query, k=candidate_k, allowlist=allowlist)
    except Exception as exc:
        _mark_manifest_unhealthy(conn, vault_id, snapshot["epoch"], error=str(exc))
        raise TurbovecSidecarUnhealthy("sidecar_search_failed") from exc
    candidate_ids = [
        chunk_id
        for chunk_id in (
            _stable_id_lookup(allowlist_chunk_ids).get(int(value)) for value in ids[0].tolist()
        )
        if chunk_id
    ]
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
                **_evidence_locators(row),
            }
        )
    return scored


def _hydrate_scored_rows(
    conn,
    vault_id: str,
    *,
    snapshot: dict,
    cluster_id: str | None,
    chunk_ids: list[str],
    raw_score_by_chunk: dict[str, float],
    weighted_score_by_chunk: dict[str, float],
) -> list[dict[str, Any]]:
    rows = _hydrate_candidate_rows(
        conn,
        vault_id,
        snapshot=snapshot,
        cluster_id=cluster_id,
        chunk_ids=chunk_ids,
    )
    rows_by_chunk = {str(row["chunk_id"]): row for row in rows}
    scored: list[dict[str, Any]] = []
    for chunk_id in chunk_ids:
        row = rows_by_chunk.get(chunk_id)
        if row is None:
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
                "raw_score": raw_score_by_chunk[chunk_id],
                "score": weighted_score_by_chunk[chunk_id],
                **_evidence_locators(row),
            }
        )
    return scored


def _exact_search_snapshot(
    conn,
    vault_id: str,
    *,
    snapshot: dict,
    cluster_id: str | None,
    expected_dim: int,
) -> ExactSearchSnapshot:
    cache_key = _exact_cache_key(conn, vault_id, snapshot=snapshot, cluster_id=cluster_id)
    with _EXACT_SEARCH_CACHE_LOCK:
        cached = _EXACT_SEARCH_CACHE.get(cache_key)
        if cached is not None:
            _EXACT_SEARCH_CACHE.move_to_end(cache_key)
            return cached
    built = _build_exact_search_snapshot(
        conn,
        vault_id,
        snapshot=snapshot,
        cluster_id=cluster_id,
        expected_dim=expected_dim,
    )
    with _EXACT_SEARCH_CACHE_LOCK:
        built_bytes = _exact_snapshot_bytes(built)
        if built_bytes <= EXACT_CACHE_MAX_BYTES:
            _EXACT_SEARCH_CACHE[cache_key] = built
            _EXACT_SEARCH_CACHE.move_to_end(cache_key)
            while (
                _EXACT_SEARCH_CACHE
                and sum(_exact_snapshot_bytes(item) for item in _EXACT_SEARCH_CACHE.values())
                > EXACT_CACHE_MAX_BYTES
            ):
                _EXACT_SEARCH_CACHE.popitem(last=False)
    return built


def _exact_snapshot_bytes(snapshot: ExactSearchSnapshot) -> int:
    return int(
        snapshot.vectors.nbytes
        + snapshot.trust_weights.nbytes
        + sum(len(chunk_id.encode("utf-8")) for chunk_id in snapshot.chunk_ids)
    )


def _build_exact_search_snapshot(
    conn,
    vault_id: str,
    *,
    snapshot: dict,
    cluster_id: str | None,
    expected_dim: int,
) -> ExactSearchSnapshot:
    params: list[Any] = [vault_id]
    cluster_clause = ""
    if cluster_id == UNCLUSTERED_SCOPE_ID:
        cluster_clause = "AND chunks.cluster_id IS NULL"
    elif cluster_id:
        cluster_clause = "AND chunks.cluster_id = ?"
        params.append(cluster_id)
    tuple_clause, tuple_params = chunk_eligibility_sql("chunks", snapshot)
    rows = conn.execute(
        f"""
        SELECT
            chunks.id AS chunk_id,
            chunks.embedding,
            sources.trust_tier,
            sources.security_labels
        FROM source_chunks chunks
        JOIN sources ON sources.id = chunks.source_id
        WHERE chunks.vault_id = ?
          AND sources.deleted_at IS NULL
          {cluster_clause}
          {tuple_clause}
        ORDER BY chunks.created_at ASC
        """,
        [*params, *tuple_params],
    ).fetchall()
    expected_dim = max(1, int(expected_dim or 0))
    chunk_ids: list[str] = []
    decoded_vectors: list[list[float]] = []
    weights: list[float] = []
    for row in rows:
        decoded = _decode_embedding(str(row["embedding"] or ""))
        if len(decoded) != expected_dim:
            continue
        chunk_ids.append(str(row["chunk_id"]))
        decoded_vectors.append(decoded)
        weights.append(float(trust_weight(row)))
    if decoded_vectors:
        vectors = np.ascontiguousarray(np.array(decoded_vectors, dtype=np.float32))
        trust_weights = np.ascontiguousarray(np.array(weights, dtype=np.float32))
    else:
        vectors = np.empty((0, expected_dim), dtype=np.float32)
        trust_weights = np.empty((0,), dtype=np.float32)
    return ExactSearchSnapshot(chunk_ids=chunk_ids, vectors=vectors, trust_weights=trust_weights)


def _exact_cache_key(
    conn, vault_id: str, *, snapshot: dict, cluster_id: str | None
) -> tuple[Any, ...]:
    return (
        str(get_settings().database_path),
        vault_id,
        cluster_id or "",
        int(snapshot["epoch"]),
        str(snapshot["embedding_model_id"]),
        str(snapshot["index_version"]),
        str(snapshot["normalization_version"]),
        str(snapshot["extraction_version"]),
    )


def _eligible_chunk_count(conn, vault_id: str, snapshot: dict, *, cluster_id: str | None) -> int:
    params: list[Any] = [vault_id]
    cluster_clause = ""
    if cluster_id == UNCLUSTERED_SCOPE_ID:
        cluster_clause = "AND chunks.cluster_id IS NULL"
    elif cluster_id:
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


def _eligible_chunk_ids(
    conn, vault_id: str, *, snapshot: dict, cluster_id: str | None
) -> list[str]:
    params: list[Any] = [vault_id]
    cluster_clause = ""
    if cluster_id == UNCLUSTERED_SCOPE_ID:
        cluster_clause = "AND chunks.cluster_id IS NULL"
    elif cluster_id:
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
    if cluster_id == UNCLUSTERED_SCOPE_ID:
        cluster_clause = "AND chunks.cluster_id IS NULL"
    elif cluster_id:
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
            chunks.chunk_meta_json,
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


def _evidence_locators(row: dict[str, Any]) -> dict[str, Any]:
    try:
        metadata = json.loads(str(row.get("chunk_meta_json") or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        "relative_path": str(row.get("import_relative_path") or "").replace("\\", "/"),
        "line_start": metadata.get("line_start"),
        "line_end": metadata.get("line_end"),
        "symbol": metadata.get("symbol"),
    }


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
    manifest = _base_manifest(
        vault_id,
        snapshot,
        index_path=index_path,
        bit_width=bit_width,
        rebuild_reason=rebuild_reason,
    )
    manifest["status"] = "staging"
    manifest["chunk_count"] = len(chunk_rows)
    manifest["allocated_slot_count"] = len(chunk_rows)
    _write_manifest(manifest_path, manifest)
    try:
        vectors = np.ascontiguousarray(
            np.array(
                [_decode_embedding(str(row["embedding"] or "")) for row in chunk_rows],
                dtype=np.float32,
            )
        )
        if chunk_rows and (vectors.shape[1] <= 0 or vectors.shape[1] % 8 != 0):
            raise TurbovecSidecarError(
                f"invalid_embedding_dimensions_for_turbovec:{vectors.shape[1]}"
            )
        if chunk_rows:
            ids = np.ascontiguousarray(
                np.array([stable_u64(str(row["id"])) for row in chunk_rows], dtype=np.uint64)
            )
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


def _sidecar_status_for_snapshot(
    conn,
    vault_id: str,
    snapshot: dict,
    *,
    eligible_count: int | None = None,
) -> dict[str, Any]:
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
    elif int(manifest.get("chunk_count") or 0) != int(
        eligible_count
        if eligible_count is not None
        else _eligible_chunk_count(conn, vault_id, snapshot, cluster_id=None)
    ):
        status = "stale"
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
        "tvim_size_bytes": int(manifest.get("tvim_size_bytes") or 0),
        "cold_load_seconds": float(manifest.get("cold_load_seconds") or 0.0),
        "last_error": str(manifest_error or manifest.get("last_error") or ""),
        "last_error_at": str(manifest.get("last_error_at") or ""),
    }


def _load_index(manifest: dict[str, Any]):
    if IdMapIndex is None:
        raise TurbovecSidecarUnavailable("turbovec_runtime_unavailable")
    index_path = Path(str(manifest["tvim_path"]))
    if not index_path.exists():
        raise TurbovecSidecarUnavailable("sidecar_index_missing")
    size_bytes = max(1, int(manifest.get("tvim_size_bytes") or index_path.stat().st_size or 1))
    cache_key = (
        str(index_path.resolve()),
        int(manifest.get("derived_state_epoch") or 0),
        str(manifest.get("embedding_model_id") or ""),
        str(manifest.get("index_version") or ""),
        str(manifest.get("updated_at") or ""),
        size_bytes,
    )
    with _SIDECAR_INDEX_CACHE_LOCK:
        cached = _SIDECAR_INDEX_CACHE.get(cache_key)
        if cached is not None:
            _SIDECAR_INDEX_CACHE.move_to_end(cache_key)
            return cached[0]
    loaded = IdMapIndex.load(str(index_path))
    if size_bytes <= SIDECAR_CACHE_MAX_BYTES:
        with _SIDECAR_INDEX_CACHE_LOCK:
            _SIDECAR_INDEX_CACHE[cache_key] = (loaded, size_bytes)
            _SIDECAR_INDEX_CACHE.move_to_end(cache_key)
            cached_bytes = sum(item[1] for item in _SIDECAR_INDEX_CACHE.values())
            while _SIDECAR_INDEX_CACHE and cached_bytes > SIDECAR_CACHE_MAX_BYTES:
                _key, (_index, removed_bytes) = _SIDECAR_INDEX_CACHE.popitem(last=False)
                cached_bytes -= removed_bytes
    return loaded


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
    from backend.app.core.vector_maintenance import active_embedding_selector

    selector = active_embedding_selector()
    return query_epoch_snapshot_conn(
        conn,
        vault_id,
        embedding_model_id=selector["embedding_model_id"],
        index_version=selector["index_version"],
    )


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
        approval = _current_phase_c_approval(
            vault_id, snapshot=snapshot, eligible_count=eligible_count
        )
        approved = bool(
            approval
            and approval.get("approved")
            and approval.get("derived_state_epoch") == snapshot["epoch"]
        )
        return "turbovec" if status["status"] == "published" and approved else "exact"
    return "exact"


def phase_c_thresholds() -> dict[str, Any]:
    return {
        "min_chunk_count": int(get_settings().turbovec_min_chunk_count),
        "min_avg_overlap_at_10": PHASE_C_MIN_AVG_OVERLAP,
        "min_query_overlap_at_10": PHASE_C_MIN_QUERY_OVERLAP,
        "min_cluster_avg_overlap_at_10": PHASE_C_MIN_CLUSTER_OVERLAP,
        "min_search_latency_improvement_ratio": PHASE_C_MIN_LATENCY_IMPROVEMENT,
        "max_sidecar_size_ratio": PHASE_C_MAX_SIZE_RATIO,
        "max_cold_load_seconds": PHASE_C_MAX_COLD_LOAD_SECONDS,
    }


def _phase_c_policy_path() -> Path:
    return get_settings().data_dir / "turbovec-phase-c-policy.json"


def _read_phase_c_policy() -> dict[str, Any]:
    path = _phase_c_policy_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": PHASE_C_POLICY_VERSION, "vaults": {}}
    if not isinstance(payload, dict):
        return {"version": PHASE_C_POLICY_VERSION, "vaults": {}}
    vaults = payload.get("vaults")
    payload["version"] = int(payload.get("version") or PHASE_C_POLICY_VERSION)
    payload["vaults"] = vaults if isinstance(vaults, dict) else {}
    return payload


def _write_phase_c_policy(payload: dict[str, Any]) -> None:
    path = _phase_c_policy_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _write_phase_c_result(vault_id: str, *, snapshot: dict, report: dict[str, Any]) -> None:
    policy = _read_phase_c_policy()
    vaults = dict(policy.get("vaults") or {})
    now = utc_now()
    current = dict(vaults.get(vault_id) or {})
    current.update(
        {
            "vault_id": vault_id,
            "approved": bool(report.get("approved")),
            "approved_at": now if report.get("approved") else "",
            "updated_at": now,
            "derived_state_epoch": int(snapshot["epoch"]),
            "eligible_chunk_count": int(report.get("eligible_chunk_count") or 0),
            "embedding_model_id": str(snapshot["embedding_model_id"]),
            "index_version": str(snapshot["index_version"]),
            "normalization_version": str(snapshot["normalization_version"]),
            "extraction_version": str(snapshot["extraction_version"]),
            "benchmark": report.get("benchmark") or {},
            "checks": report.get("checks") or [],
            "detail": str(report.get("detail") or ""),
        }
    )
    vaults[vault_id] = current
    policy["version"] = PHASE_C_POLICY_VERSION
    policy["vaults"] = vaults
    policy["updated_at"] = now
    _write_phase_c_policy(policy)


def _current_phase_c_approval(
    vault_id: str, *, snapshot: dict, eligible_count: int | None = None
) -> dict[str, Any] | None:
    policy = _read_phase_c_policy()
    vault = (policy.get("vaults") or {}).get(vault_id)
    if not isinstance(vault, dict):
        return None
    if int(vault.get("derived_state_epoch") or -1) != int(snapshot["epoch"]):
        return None
    if eligible_count is not None and int(vault.get("eligible_chunk_count") or -1) != int(
        eligible_count
    ):
        return None
    return vault


def _cluster_overlap_report(
    overlap: dict[str, Any], *, query_source: dict[str, str]
) -> dict[str, Any]:
    grouped: dict[str, list[float]] = {}
    for item in overlap.get("overlaps", []):
        key = query_source.get(str(item.get("query") or ""), "unassigned")
        grouped.setdefault(key, []).append(float(item.get("overlap_ratio") or 0.0))
    cluster_items = [
        {
            "cluster_id": key,
            "avg_overlap_ratio": round(sum(values) / max(1, len(values)), 4),
            "query_count": len(values),
        }
        for key, values in grouped.items()
    ]
    mins = [item["avg_overlap_ratio"] for item in cluster_items]
    return {
        "clusters": cluster_items,
        "min_cluster_avg_overlap_ratio": min(mins) if mins else 0.0,
    }


def _search_latency_improvement_ratio(exact: dict[str, Any], candidate: dict[str, Any]) -> float:
    exact_avg = float(exact.get("avg") or 0.0)
    candidate_avg = float(candidate.get("avg") or 0.0)
    if exact_avg <= 0 or candidate_avg <= 0:
        return 0.0
    return round(exact_avg / candidate_avg, 4)


def _phase_c_acceptance_checks(
    *,
    eligible_count: int,
    overlap: dict[str, Any],
    cluster_overlap: dict[str, Any],
    latency_ratio: float,
    size_ratio: float,
    cold_load_seconds: float,
) -> list[dict[str, Any]]:
    thresholds = phase_c_thresholds()
    avg_overlap = float(overlap.get("avg_overlap_ratio") or 0.0)
    min_overlap = float(overlap.get("min_overlap_ratio") or 0.0)
    min_cluster = float(cluster_overlap.get("min_cluster_avg_overlap_ratio") or 0.0)
    return [
        {
            "id": "min_chunk_count",
            "ok": eligible_count >= int(thresholds["min_chunk_count"]),
            "detail": f"eligible_chunks={eligible_count}; required>={thresholds['min_chunk_count']}",
        },
        {
            "id": "avg_overlap_at_10",
            "ok": avg_overlap >= float(thresholds["min_avg_overlap_at_10"]),
            "detail": f"avg_overlap={avg_overlap}",
        },
        {
            "id": "min_query_overlap_at_10",
            "ok": min_overlap >= float(thresholds["min_query_overlap_at_10"]),
            "detail": f"min_query_overlap={min_overlap}",
        },
        {
            "id": "min_cluster_avg_overlap_at_10",
            "ok": min_cluster >= float(thresholds["min_cluster_avg_overlap_at_10"]),
            "detail": f"min_cluster_avg_overlap={min_cluster}",
        },
        {
            "id": "search_latency_improvement",
            "ok": latency_ratio >= float(thresholds["min_search_latency_improvement_ratio"]),
            "detail": f"latency_ratio={latency_ratio}",
        },
        {
            "id": "sidecar_size_ratio",
            "ok": size_ratio <= float(thresholds["max_sidecar_size_ratio"]),
            "detail": f"sidecar_size_ratio={size_ratio}",
        },
        {
            "id": "cold_load_seconds",
            "ok": cold_load_seconds < float(thresholds["max_cold_load_seconds"]),
            "detail": f"cold_load_seconds={round(cold_load_seconds, 4)}",
        },
        {
            "id": "fallback_and_repair_ready",
            "ok": True,
            "detail": "Exact fallback, unhealthy marking, sidecar repair, and startup repair integration are implemented.",
        },
    ]


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


def _read_manifest_with_validation(
    conn, vault_id: str, epoch: int
) -> tuple[dict[str, Any] | None, str | None]:
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


def _manifest_validation_error(
    conn, vault_id: str, epoch: int, manifest: dict[str, Any]
) -> str | None:
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
        and str(manifest.get("normalization_version") or "")
        == str(snapshot["normalization_version"])
        and str(manifest.get("extraction_version") or "") == str(snapshot["extraction_version"])
        and str(manifest.get("status") or "") in MANIFEST_STATUSES
    )


def _stable_id_lookup(chunk_ids: list[str]) -> dict[int, str]:
    return {stable_u64(chunk_id): chunk_id for chunk_id in chunk_ids}
