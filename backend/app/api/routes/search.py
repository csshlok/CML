from fastapi import APIRouter, HTTPException

from backend.app.core.database import connect, dict_from_row
from backend.app.core.embeddings import cosine_similarity, decode_embedding, embed_text, reindex_source_chunks, require_embeddings_available
from backend.app.core.retrieval_scoring import (
    compare_source_classes,
    export_benchmark_report,
    retrieval_eval_fixtures,
    scoring_ledger,
    threshold_benchmark,
)
from backend.app.core.vector_maintenance import (
    activate_embedding_index,
    begin_embedding_index_transition,
    compact_vectors,
    embedding_index_policy,
    repair_vectors,
    vector_repair_plan,
)
from backend.app.schemas import SemanticSearchRequest, SemanticSearchResponse

router = APIRouter(prefix="/search", tags=["search"])


@router.post("/semantic", response_model=SemanticSearchResponse)
def semantic_search(payload: SemanticSearchRequest) -> dict:
    try:
        require_embeddings_available("Semantic search")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    query_vector = embed_text(payload.query)
    params: list[str] = [payload.vault_id]
    cluster_clause = ""
    if payload.cluster_id:
        cluster_clause = "AND chunks.cluster_id = ?"
        params.append(payload.cluster_id)

    with connect() as conn:
        vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (payload.vault_id,)).fetchone()
        if vault is None:
            raise HTTPException(status_code=404, detail="Vault not found")

        rows = conn.execute(
            f"""
            SELECT
                chunks.id AS chunk_id,
                chunks.source_id,
                chunks.page_id,
                chunks.cluster_id,
                chunks.chunk_index,
                chunks.text,
                chunks.embedding,
                sources.title AS source_title,
                sources.source_type,
                pages.page_number
            FROM source_chunks chunks
            JOIN sources ON sources.id = chunks.source_id
            LEFT JOIN source_pages pages ON pages.id = chunks.page_id
            WHERE chunks.vault_id = ? AND sources.deleted_at IS NULL {cluster_clause}
            """,
            params,
        ).fetchall()

    scored = []
    for row in rows:
        score = cosine_similarity(query_vector, decode_embedding(row["embedding"]))
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
                "score": round(score, 4),
            }
        )

    scored.sort(key=lambda item: item["score"], reverse=True)
    return {
        "query": payload.query,
        "results": scored[: payload.limit],
    }


@router.get("/scoring-ledger")
def get_scoring_ledger(vault_id: str, query: str, cluster_id: str | None = None, limit: int = 20) -> dict:
    if not query.strip():
        raise HTTPException(status_code=400, detail="query is required")
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
    try:
        require_embeddings_available("Threshold benchmark")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return threshold_benchmark(vault_id)


@router.get("/compare-source-classes")
def get_compare_source_classes(vault_id: str, query: str, cluster_id: str | None = None) -> dict:
    if not query.strip():
        raise HTTPException(status_code=400, detail="query is required")
    try:
        require_embeddings_available("Source-class comparison")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return compare_source_classes(vault_id, query.strip(), cluster_id=cluster_id)


@router.post("/benchmark-report")
def create_benchmark_report(vault_id: str) -> dict:
    try:
        require_embeddings_available("Benchmark report")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return export_benchmark_report(vault_id)


@router.post("/reindex/{vault_id}")
def reindex_vault(vault_id: str) -> dict:
    try:
        require_embeddings_available("Reindexing")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    with connect() as conn:
        vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone()
        if vault is None:
            raise HTTPException(status_code=404, detail="Vault not found")

        rows = conn.execute(
            """
            SELECT * FROM sources
            WHERE vault_id = ? AND state = 'indexed' AND deleted_at IS NULL
            """,
            (vault_id,),
        ).fetchall()
        chunk_count = 0
        for row in rows:
            chunk_count += reindex_source_chunks(conn, dict_from_row(row))

    return {
        "vault_id": vault_id,
        "sources_indexed": len(rows),
        "chunks_indexed": chunk_count,
    }


@router.get("/vectors/policy")
def get_vector_policy() -> dict:
    return embedding_index_policy()


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
    return vector_repair_plan(vault_id)


@router.post("/vectors/repair")
def repair_vector_index(vault_id: str | None = None, limit: int = 100) -> dict:
    try:
        require_embeddings_available("Vector repair")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return repair_vectors(vault_id, limit=max(1, min(limit, 1000)))


@router.post("/vectors/compact")
def compact_vector_index(vault_id: str | None = None) -> dict:
    return compact_vectors(vault_id)
