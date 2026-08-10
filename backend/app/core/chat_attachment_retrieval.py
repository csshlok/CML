from __future__ import annotations

import re

from backend.app.core.database import connect, dict_from_row
from backend.app.core.derived_state import chunk_eligibility_sql, query_epoch_snapshot_conn
from backend.app.core.embeddings import cosine_similarity, decode_embedding, embed_text
from backend.app.core.encrypted_storage import chunk_from_encrypted_row
from backend.app.core.retrieval_trust import is_low_trust, trust_weight
from backend.app.core.vector_maintenance import active_embedding_selector


MAX_ATTACHMENT_SOURCES = 12
MAX_ATTACHMENT_CANDIDATES_PER_SOURCE = 256
MAX_ATTACHMENT_CANDIDATE_CHUNKS = MAX_ATTACHMENT_SOURCES * MAX_ATTACHMENT_CANDIDATES_PER_SOURCE
MAX_ATTACHMENT_SELECTED_CHUNKS = 12


def session_attachment_source_ids(
    conn,
    *,
    vault_id: str,
    session_id: str,
    prompt: str,
) -> list[str]:
    rows = conn.execute(
        """
        SELECT attachments.source_id, attachments.file_name, sources.title
        FROM chat_attachments attachments
        JOIN sources ON sources.id = attachments.source_id
        WHERE attachments.session_id = ?
          AND sources.vault_id = ?
          AND sources.state = 'indexed'
          AND sources.deleted_at IS NULL
        ORDER BY attachments.created_at DESC, attachments.rowid DESC
        """,
        (session_id, vault_id),
    ).fetchall()
    if not rows:
        return []
    normalized_prompt = set(re.findall(r"[a-z0-9]{4,}", prompt.lower()))
    explicitly_references_files = prompt_references_chat_attachments(prompt)
    selected: list[str] = []
    for row in rows:
        title_tokens = set(
            re.findall(
                r"[a-z0-9]{4,}",
                f"{row['file_name'] or ''} {row['title'] or ''}".lower(),
            )
        ) - {"file", "document", "pdf"}
        title_overlap = normalized_prompt.intersection(title_tokens)
        distinctive_title_match = (
            len(title_overlap) >= 2
            or any(len(token) >= 7 for token in title_overlap)
        )
        if explicitly_references_files or distinctive_title_match:
            source_id = str(row["source_id"])
            if source_id not in selected:
                selected.append(source_id)
    return selected[:12]


def build_attachment_bundle(
    *,
    vault_id: str,
    query: str,
    source_ids: list[str],
    limit: int,
) -> dict:
    unique_source_ids = list(
        dict.fromkeys(str(item) for item in source_ids if str(item).strip())
    )[:MAX_ATTACHMENT_SOURCES]
    if not unique_source_ids:
        return _empty_attachment_bundle()

    query_vector = embed_text(query)
    selector = active_embedding_selector()
    with connect() as conn:
        snapshot = query_epoch_snapshot_conn(
            conn,
            vault_id,
            embedding_model_id=selector["embedding_model_id"],
            index_version=selector["index_version"],
        )
        tuple_clause, tuple_params = chunk_eligibility_sql("chunks", snapshot)
        placeholders = ",".join("?" for _ in unique_source_ids)
        candidate_rows = conn.execute(
            f"""
            WITH bounded_candidates AS (
                SELECT
                    chunks.id AS chunk_id,
                    chunks.source_id,
                    chunks.vault_id,
                    chunks.page_id,
                    chunks.chunk_index,
                    chunks.embedding,
                    chunks.cluster_id,
                    sources.title AS source_title,
                    sources.source_type,
                    sources.provenance,
                    sources.trust_tier,
                    sources.security_labels,
                    pages.page_number,
                    ROW_NUMBER() OVER (
                        PARTITION BY chunks.source_id ORDER BY chunks.chunk_index, chunks.id
                    ) AS source_rank
                FROM source_chunks chunks
                JOIN sources ON sources.id = chunks.source_id
                LEFT JOIN source_pages pages ON pages.id = chunks.page_id
                WHERE chunks.vault_id = ?
                  AND chunks.source_id IN ({placeholders})
                  AND sources.state = 'indexed'
                  AND sources.deleted_at IS NULL
                  {tuple_clause}
            )
            SELECT
                chunk_id, source_id, vault_id, page_id, chunk_index, embedding,
                cluster_id, source_title, source_type, provenance, trust_tier,
                security_labels, page_number
            FROM bounded_candidates
            WHERE source_rank <= ?
            ORDER BY source_id, chunk_index, chunk_id
            LIMIT ?
            """,
            [
                vault_id,
                *unique_source_ids,
                *tuple_params,
                MAX_ATTACHMENT_CANDIDATES_PER_SOURCE,
                MAX_ATTACHMENT_CANDIDATE_CHUNKS,
            ],
        ).fetchall()
        scored = [_citation_from_chunk_metadata(dict_from_row(row), query_vector) for row in candidate_rows]
        scored.sort(key=lambda item: item["score"], reverse=True)
        selected_metadata = _select_diverse_citations(
            scored,
            source_ids=unique_source_ids,
            limit=min(limit, MAX_ATTACHMENT_SELECTED_CHUNKS),
        )
        selected_ids = [str(item["chunk_id"]) for item in selected_metadata]
        hydrated_by_id: dict[str, dict] = {}
        if selected_ids:
            selected_placeholders = ",".join("?" for _ in selected_ids)
            selected_rows = conn.execute(
                f"""
                SELECT
                    chunks.id AS chunk_id, chunks.source_id, chunks.vault_id,
                    chunks.page_id, chunks.chunk_index, chunks.text, chunks.embedding,
                    chunks.cluster_id, sources.title AS source_title,
                    sources.source_type, sources.provenance, sources.trust_tier,
                    sources.security_labels, pages.page_number
                FROM source_chunks chunks
                JOIN sources ON sources.id = chunks.source_id
                LEFT JOIN source_pages pages ON pages.id = chunks.page_id
                WHERE chunks.vault_id = ? AND chunks.id IN ({selected_placeholders})
                """,
                [vault_id, *selected_ids],
            ).fetchall()
            hydrated_by_id = {
                str(row["chunk_id"]): chunk_from_encrypted_row(conn, row)
                for row in selected_rows
            }
        selected = [
            {**item, "snippet": hydrated_by_id[str(item["chunk_id"])]["text"]}
            for item in selected_metadata
            if str(item["chunk_id"]) in hydrated_by_id
        ]
        cluster_ids = list(
            dict.fromkeys(
                str(row["cluster_id"])
                for row in selected
                if str(row.get("cluster_id") or "").strip()
            )
        )
        clusters = (
            conn.execute(
                f"""
                SELECT * FROM clusters
                WHERE vault_id = ? AND id IN ({','.join('?' for _ in cluster_ids)})
                """,
                [vault_id, *cluster_ids],
            ).fetchall()
            if cluster_ids
            else []
        )

    represented_sources = {str(item["source_id"]) for item in selected}
    return {
        "citations": selected,
        "selected_clusters": [dict_from_row(row) for row in clusters],
        "memory_items": [],
        "working_memory": {},
        "warnings": [
            f"Used {len(represented_sources)} attached "
            f"{'file' if len(represented_sources) == 1 else 'files'} as the answer source."
        ],
        "bundle_status": {
            "mode": "attachments",
            "sources_considered": len(unique_source_ids),
            "sources_analyzed": len(represented_sources),
            "sources_low_relevance": max(
                len(unique_source_ids) - len(represented_sources),
                0,
            ),
            "candidate_chunks_considered": len(candidate_rows),
            "candidate_limit": MAX_ATTACHMENT_CANDIDATE_CHUNKS,
        },
        "retrieval_authority": True,
        "cluster_profile": {},
        "token_estimate": {},
    }


def prompt_references_chat_attachments(prompt: str) -> bool:
    cleaned = " ".join(prompt.lower().split()).strip(" .!?")
    if cleaned in {"tell me more", "go deeper", "continue", "what else"}:
        return True
    normalized = f" {cleaned} "
    return any(
        phrase in normalized
        for phrase in (
            " attachment ",
            " attachments ",
            " attached ",
            " document ",
            " documents ",
            " pdf ",
            " pdfs ",
            " file ",
            " files ",
            " syllabus ",
            " these ",
            " those ",
            " both ",
            " them ",
            " they ",
            " their ",
            " which one ",
            " the first ",
            " the second ",
        )
    )


def _citation_from_chunk_metadata(row: dict, query_vector: list[float]) -> dict:
    raw_score = cosine_similarity(query_vector, decode_embedding(row["embedding"]))
    return {
        "source_id": row["source_id"],
        "source_title": row["source_title"],
        "source_type": row["source_type"],
        "cluster_id": row["cluster_id"],
        "chunk_id": row["chunk_id"],
        "page_id": row["page_id"],
        "page_number": row["page_number"],
        "score": round(max(raw_score * trust_weight(row), 0.0001), 4),
        "provenance": row["provenance"],
        "trust_tier": row["trust_tier"],
        "security_labels": row["security_labels"],
        "low_trust": is_low_trust(row),
        "state": "current",
    }


def _select_diverse_citations(
    scored: list[dict],
    *,
    source_ids: list[str],
    limit: int,
) -> list[dict]:
    selected: list[dict] = []
    selected_chunks: set[str] = set()
    for source_id in source_ids:
        best = next(
            (item for item in scored if str(item["source_id"]) == source_id),
            None,
        )
        if best is not None:
            selected.append(best)
            selected_chunks.add(str(best["chunk_id"]))
    target_limit = max(
        len(selected),
        min(MAX_ATTACHMENT_SELECTED_CHUNKS, max(1, limit)),
    )
    for item in scored:
        if len(selected) >= target_limit:
            break
        if str(item["chunk_id"]) in selected_chunks:
            continue
        selected.append(item)
        selected_chunks.add(str(item["chunk_id"]))
    return selected


def _empty_attachment_bundle() -> dict:
    return {
        "citations": [],
        "selected_clusters": [],
        "memory_items": [],
        "working_memory": {},
        "warnings": ["No readable attached sources were available."],
        "bundle_status": {
            "mode": "attachments",
            "sources_considered": 0,
            "sources_analyzed": 0,
            "sources_low_relevance": 0,
        },
        "retrieval_authority": True,
        "cluster_profile": {},
        "token_estimate": {},
    }
