from __future__ import annotations

import sqlite3


def retrieval_packing_diagnostics(conn: sqlite3.Connection, *, vault_id: str) -> dict:
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS query_count,
            COALESCE(SUM(candidate_citation_count), 0) AS candidate_citation_count,
            COALESCE(SUM(selected_citation_count), 0) AS selected_citation_count,
            COALESCE(SUM(raw_context_tokens_estimate), 0) AS raw_context_tokens,
            COALESCE(SUM(final_context_tokens_estimate), 0) AS final_context_tokens,
            COALESCE(SUM(raw_candidate_tokens_estimate), 0) AS raw_evidence_tokens,
            COALESCE(SUM(evidence_tokens_estimate), 0) AS selected_evidence_tokens,
            MAX(created_at) AS latest_query_at
        FROM retrieval_snapshots
        WHERE vault_id = ? AND context_strategy != ''
        """,
        (vault_id,),
    ).fetchone()
    query_count = int(row["query_count"] or 0)
    raw_context = int(row["raw_context_tokens"] or 0)
    final_context = int(row["final_context_tokens"] or 0)
    context_tokens_avoided = max(0, raw_context - final_context)
    raw_evidence = int(row["raw_evidence_tokens"] or 0)
    selected_evidence = int(row["selected_evidence_tokens"] or 0)
    return {
        "vault_id": vault_id,
        "query_count": query_count,
        "candidate_citation_count": int(row["candidate_citation_count"] or 0),
        "selected_citation_count": int(row["selected_citation_count"] or 0),
        "raw_context_tokens": raw_context,
        "final_context_tokens": final_context,
        "context_tokens_avoided": context_tokens_avoided,
        "context_reduction_percent": round(context_tokens_avoided * 100 / raw_context, 1) if raw_context else 0.0,
        "raw_evidence_tokens": raw_evidence,
        "selected_evidence_tokens": selected_evidence,
        "average_final_context_tokens": round(final_context / query_count) if query_count else 0,
        "latest_query_at": row["latest_query_at"],
    }
