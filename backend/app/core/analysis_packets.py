from backend.app.core.database import connect
from backend.app.core.derived_state import chunk_eligibility_sql, query_epoch_snapshot_conn
from backend.app.core.embeddings import cosine_similarity, decode_embedding, embed_text
from backend.app.core.encrypted_storage import chunk_from_encrypted_row
from backend.app.core.retrieval_trust import is_low_trust, trust_weight
from backend.app.core.vector_maintenance import active_embedding_selector
from backend.app.core.turbovec_runtime import UNCLUSTERED_SCOPE_ID

ANALYSIS_RELEVANCE_FLOOR = 0.12
ANALYSIS_SCAN_PAGE_SIZE = 500


def build_analysis_packets(
    *,
    vault_id: str,
    query: str,
    cluster_id: str | None = None,
    include_chat_transcripts: bool = False,
    limit: int | None = None,
    full_scope: bool = False,
) -> dict:
    query_vector = embed_text(query)
    selector = active_embedding_selector()
    params: list[str] = [vault_id]
    cluster_clause = ""
    if cluster_id == UNCLUSTERED_SCOPE_ID:
        cluster_clause = "AND chunks.cluster_id IS NULL"
    elif cluster_id:
        cluster_clause = "AND chunks.cluster_id = ?"
        params.append(cluster_id)

    best_by_source: dict[str, dict] = {}
    with connect() as conn:
        snapshot = query_epoch_snapshot_conn(
            conn,
            vault_id,
            embedding_model_id=selector["embedding_model_id"],
            index_version=selector["index_version"],
        )
        tuple_clause, tuple_params = chunk_eligibility_sql("chunks", snapshot)
        cursor = ""
        while True:
            rows = conn.execute(
                f"""
                SELECT
                    chunks.id AS chunk_id,
                    chunks.source_id,
                    chunks.page_id,
                    chunks.vault_id,
                    chunks.text,
                    chunks.embedding,
                    sources.title,
                    sources.source_type,
                    sources.tags,
                    sources.provenance,
                    sources.trust_tier,
                    sources.security_labels,
                    pages.page_number
                FROM source_chunks chunks
                JOIN sources ON sources.id = chunks.source_id
                LEFT JOIN source_pages pages ON pages.id = chunks.page_id
                WHERE chunks.vault_id = ?
                  AND sources.state = 'indexed'
                  AND sources.deleted_at IS NULL
                  {tuple_clause}
                  {cluster_clause}
                  AND chunks.id > ?
                ORDER BY chunks.id
                LIMIT ?
                """,
                [params[0], *tuple_params, *params[1:], cursor, ANALYSIS_SCAN_PAGE_SIZE],
            ).fetchall()
            if not rows:
                break
            cursor = str(rows[-1]["chunk_id"])
            for encrypted_row in rows:
                row = chunk_from_encrypted_row(conn, encrypted_row)
                if not include_chat_transcripts and _is_chat_transcript_row(row):
                    continue
                raw_score = (
                    cosine_similarity(query_vector, decode_embedding(row["embedding"]))
                    * trust_weight(row)
                )
                score = max(0.0, float(raw_score))
                packet = {
                    "source_id": row["source_id"],
                    "source_title": row["title"],
                    "chunk_id": row["chunk_id"],
                    "page_id": row["page_id"],
                    "page_number": row["page_number"],
                    "excerpt": row["text"],
                    "score": round(score, 4),
                    "provenance": row.get("provenance") or "local_import",
                    "trust_tier": row.get("trust_tier") or "trusted_local",
                    "security_labels": row.get("security_labels") or "[]",
                    "low_trust": is_low_trust(row),
                    "_raw_score": raw_score,
                }
                current = best_by_source.get(packet["source_id"])
                if current is None or raw_score > current["_raw_score"]:
                    best_by_source[packet["source_id"]] = packet
            if len(rows) < ANALYSIS_SCAN_PAGE_SIZE:
                break

    packets = sorted(best_by_source.values(), key=lambda item: item["_raw_score"], reverse=True)
    relevant_packets = [item for item in packets if float(item["score"]) >= ANALYSIS_RELEVANCE_FLOOR]
    selected = packets if full_scope else relevant_packets
    if limit is not None:
        selected = selected[: max(1, int(limit))]

    materialized = []
    for item in selected:
        packet = dict(item)
        packet["status"] = (
            "ready" if float(packet["score"]) >= ANALYSIS_RELEVANCE_FLOOR else "low_relevance"
        )
        packet["evidence_excerpt"] = str(packet["excerpt"] or "")[:1200]
        packet.pop("_raw_score", None)
        materialized.append(packet)

    return {
        "packets": materialized,
        "analyzed_source_ids": [str(item["source_id"]) for item in packets],
        "relevant_source_count": len(relevant_packets),
        "low_relevance_source_count": max(len(packets) - len(relevant_packets), 0),
        "sources_considered": len(packets),
    }


def _is_chat_transcript_row(row) -> bool:
    source_type = row["source_type"] if "source_type" in row.keys() else ""
    source_id = row["source_id"] if "source_id" in row.keys() else row["id"]
    tags = row["tags"] if "tags" in row.keys() else ""
    return (
        str(source_type or "") == "chat_transcript"
        or str(source_id or "").startswith("chat-source-")
        or "TRANSCRIPT" in str(tags or "")
    )
