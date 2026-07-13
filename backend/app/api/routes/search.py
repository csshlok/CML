from fastapi import APIRouter, HTTPException

from backend.app.core.background_jobs import enqueue_job
from backend.app.core.database import connect
from backend.app.core.embeddings import embed_text, require_embeddings_available
from backend.app.core.retrieval_scoring import (
    compare_source_classes,
    export_benchmark_report,
    retrieval_eval_fixtures,
    scoring_ledger,
    threshold_benchmark,
)
from backend.app.core.context_layer_eval import export_context_layer_report
from backend.app.core.retrieval_cache import list_query_cache, prune_query_cache, put_query_cache
from backend.app.core.vector_maintenance import (
    activate_embedding_index,
    begin_embedding_index_transition,
    compact_vectors,
    embedding_index_policy,
    repair_vectors,
    vector_repair_plan,
)
from backend.app.core.turbovec_runtime import (
    TurbovecSidecarUnavailable,
    benchmark_turbovec_phase_c,
    build_turbovec_sidecar,
    repair_turbovec_sidecars,
    semantic_search_results,
    turbovec_phase_c_status,
    turbovec_sidecar_repair_plan,
    turbovec_sidecar_status,
    vector_backend_policy,
)
from backend.app.schemas import SemanticSearchRequest, SemanticSearchResponse

router = APIRouter(prefix="/search", tags=["search"])


@router.post("/semantic", response_model=SemanticSearchResponse)
def semantic_search(payload: SemanticSearchRequest) -> dict:
    _ensure_vault_exists(payload.vault_id)
    try:
        require_embeddings_available("Semantic search")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    query_vector = embed_text(payload.query)
    try:
        search = semantic_search_results(
            payload.vault_id,
            query_vector,
            cluster_id=payload.cluster_id,
            limit=payload.limit,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Vault not found") from exc
    return {
        "query": payload.query,
        "backend": search["backend"],
        "eligible_count": search["eligible_count"],
        "results": search["results"],
    }


@router.get("/scoring-ledger")
def get_scoring_ledger(vault_id: str, query: str, cluster_id: str | None = None, limit: int = 20) -> dict:
    if not query.strip():
        raise HTTPException(status_code=400, detail="query is required")
    _ensure_vault_exists(vault_id)
    try:
        require_embeddings_available("Scoring ledger")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return scoring_ledger(vault_id, query.strip(), cluster_id=cluster_id, limit=limit)


@router.get("/eval-fixtures")
def get_retrieval_eval_fixtures() -> dict:
    return retrieval_eval_fixtures()


@router.get("/threshold-benchmark")
def get_threshold_benchmark(vault_id: str) -> dict:
    _ensure_vault_exists(vault_id)
    try:
        require_embeddings_available("Threshold benchmark")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return threshold_benchmark(vault_id)


@router.get("/compare-source-classes")
def get_compare_source_classes(vault_id: str, query: str, cluster_id: str | None = None) -> dict:
    if not query.strip():
        raise HTTPException(status_code=400, detail="query is required")
    _ensure_vault_exists(vault_id)
    try:
        require_embeddings_available("Source-class comparison")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return compare_source_classes(vault_id, query.strip(), cluster_id=cluster_id)


@router.post("/benchmark-report")
def create_benchmark_report(vault_id: str) -> dict:
    _ensure_vault_exists(vault_id)
    try:
        require_embeddings_available("Benchmark report")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return export_benchmark_report(vault_id)


@router.post("/context-layer-report")
def create_context_layer_report(vault_id: str, cluster_id: str | None = None, limit: int = 5) -> dict:
    _ensure_vault_exists(vault_id)
    try:
        require_embeddings_available("Context-layer report")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return export_context_layer_report(
        vault_id,
        cluster_id=cluster_id,
        limit=max(1, min(limit, 12)),
    )


@router.get("/query-cache")
def get_query_cache(vault_id: str | None = None) -> dict:
    _ensure_vault_exists(vault_id)
    return {"items": list_query_cache(vault_id)}


@router.post("/query-cache")
def create_query_cache(vault_id: str, query_fingerprint: str, source_ids: str = "") -> dict:
    contributing = [item.strip() for item in source_ids.split(",") if item.strip()]
    if not query_fingerprint.strip():
        raise HTTPException(status_code=400, detail="query_fingerprint is required")
    _ensure_vault_exists(vault_id)
    return put_query_cache(
        vault_id=vault_id,
        query_fingerprint=query_fingerprint.strip(),
        contributing_source_ids=contributing,
    )


@router.post("/query-cache/prune")
def prune_query_cache_route(
    vault_id: str | None = None,
    max_age_days: int = 30,
    max_items: int = 500,
    max_payload_bytes: int = 5_000_000,
) -> dict:
    _ensure_vault_exists(vault_id)
    return prune_query_cache(
        vault_id=vault_id,
        max_age_days=max_age_days,
        max_items=max_items,
        max_payload_bytes=max_payload_bytes,
    )


@router.post("/reindex/{vault_id}")
def reindex_vault(vault_id: str) -> dict:
    _ensure_vault_exists(vault_id)
    try:
        require_embeddings_available("Reindexing")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id FROM sources
            WHERE vault_id = ? AND state = 'indexed' AND deleted_at IS NULL
            """,
            (vault_id,),
        ).fetchall()
        queued = 0
        for row in rows:
            job = enqueue_job(
                conn,
                job_type="reindex_source",
                payload={"source_id": row["id"]},
                dedupe_key=f"reindex-source:{row['id']}",
                scope_id=row["id"],
                user_initiated=True,
            )
            if job["status"] in {"queued", "blocked_by_dependency", "running"}:
                queued += 1

    return {
        "vault_id": vault_id,
        "sources_matched": len(rows),
        "jobs_queued": queued,
        "status": "queued",
    }


@router.get("/vectors/policy")
def get_vector_policy() -> dict:
    return embedding_index_policy()


@router.get("/vectors/backend-policy")
def get_vector_backend_policy(vault_id: str | None = None) -> dict:
    return vector_backend_policy(vault_id)


@router.post("/vectors/policy/begin-transition")
def begin_vector_policy_transition(model_id: str) -> dict:
    if not model_id.strip():
        raise HTTPException(status_code=400, detail="model_id is required")
    return begin_embedding_index_transition(model_id.strip())


@router.post("/vectors/policy/activate")
def activate_vector_policy(model_id: str, index_version: str = "v1") -> dict:
    if not model_id.strip():
        raise HTTPException(status_code=400, detail="model_id is required")
    return activate_embedding_index(model_id.strip(), index_version.strip() or "v1")


@router.get("/vectors/repair-plan")
def get_vector_repair_plan(vault_id: str | None = None) -> dict:
    _ensure_vault_exists(vault_id)
    return vector_repair_plan(vault_id)


@router.post("/vectors/repair")
def repair_vector_index(vault_id: str | None = None, limit: int = 100) -> dict:
    _ensure_vault_exists(vault_id)
    try:
        require_embeddings_available("Vector repair")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return repair_vectors(vault_id, limit=max(1, min(limit, 1000)))


@router.post("/vectors/compact")
def compact_vector_index(vault_id: str | None = None) -> dict:
    _ensure_vault_exists(vault_id)
    return compact_vectors(vault_id)


@router.get("/vectors/sidecar/status")
def get_turbovec_sidecar_status(vault_id: str) -> dict:
    _ensure_vault_exists(vault_id)
    try:
        return turbovec_sidecar_status(vault_id)
    except TurbovecSidecarUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/vectors/sidecar/build")
def build_vector_sidecar(vault_id: str, rebuild_reason: str = "manual") -> dict:
    _ensure_vault_exists(vault_id)
    try:
        return build_turbovec_sidecar(vault_id, rebuild_reason=rebuild_reason.strip() or "manual")
    except TurbovecSidecarUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/vectors/sidecar/repair-plan")
def get_vector_sidecar_repair_plan(vault_id: str | None = None) -> dict:
    _ensure_vault_exists(vault_id)
    return turbovec_sidecar_repair_plan(vault_id)


@router.post("/vectors/sidecar/repair")
def repair_vector_sidecars(vault_id: str | None = None) -> dict:
    _ensure_vault_exists(vault_id)
    return repair_turbovec_sidecars(vault_id)


@router.get("/vectors/phase-c/status")
def get_turbovec_phase_c_gate_status(vault_id: str) -> dict:
    _ensure_vault_exists(vault_id)
    try:
        return turbovec_phase_c_status(vault_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Vault not found") from exc


@router.post("/vectors/phase-c/benchmark")
def run_turbovec_phase_c_benchmark(vault_id: str, query_limit: int = 20, top_k: int = 10) -> dict:
    _ensure_vault_exists(vault_id)
    try:
        require_embeddings_available("Turbovec Phase C benchmark")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        return benchmark_turbovec_phase_c(
            vault_id,
            query_limit=max(1, min(query_limit, 100)),
            top_k=max(1, min(top_k, 20)),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Vault not found") from exc
    except TurbovecSidecarUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _ensure_vault_exists(vault_id: str | None) -> None:
    if not vault_id:
        return
    with connect() as conn:
        row = conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Vault not found")
