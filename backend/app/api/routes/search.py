from fastapi import APIRouter, HTTPException

from backend.app.core.database import connect, dict_from_row
from backend.app.core.embeddings import cosine_similarity, decode_embedding, embed_text, reindex_source_chunks
from backend.app.schemas import SemanticSearchRequest, SemanticSearchResponse

router = APIRouter(prefix="/search", tags=["search"])


@router.post("/semantic", response_model=SemanticSearchResponse)
def semantic_search(payload: SemanticSearchRequest) -> dict:
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


@router.post("/reindex/{vault_id}")
def reindex_vault(vault_id: str) -> dict:
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
