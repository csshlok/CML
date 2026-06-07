from collections import defaultdict

from backend.app.core.derived_state import chunk_eligibility_sql, query_epoch_snapshot_conn
from backend.app.core.embeddings import cosine_similarity, decode_embedding
from backend.app.core.vector_maintenance import active_embedding_selector


def suggest_source_cluster_moves(conn, vault_id: str, limit: int = 12) -> list[dict]:
    source_vectors = _source_vectors(conn, vault_id)
    if not source_vectors:
        return []

    rows = conn.execute(
        """
        SELECT sources.id, sources.title, sources.cluster_id, clusters.name AS current_cluster_name
        FROM sources
        LEFT JOIN clusters ON clusters.id = sources.cluster_id
        WHERE sources.vault_id = ? AND sources.state = 'indexed'
        """,
        (vault_id,),
    ).fetchall()
    clusters = {
        row["id"]: row["name"]
        for row in conn.execute(
            "SELECT id, name FROM clusters WHERE vault_id = ?",
            (vault_id,),
        ).fetchall()
    }

    suggestions: list[dict] = []
    for row in rows:
        source_id = row["id"]
        source_vector = source_vectors.get(source_id)
        if source_vector is None:
            continue
        cluster_vectors = _cluster_vectors(conn, vault_id, exclude_source_id=source_id)
        if len(cluster_vectors) < 1:
            continue

        scored = []
        for cluster_id, cluster_vector in cluster_vectors.items():
            score = cosine_similarity(source_vector, cluster_vector)
            scored.append((score, cluster_id))
        scored.sort(reverse=True)
        if not scored:
            continue

        best_score, best_cluster_id = scored[0]
        current_cluster_id = row["cluster_id"]
        current_score = next((score for score, cluster_id in scored if cluster_id == current_cluster_id), 0.0)

        if best_cluster_id == current_cluster_id:
            continue
        if best_score < 0.2 or best_score - current_score < 0.08:
            continue

        suggestions.append(
            {
                "source_id": source_id,
                "source_title": row["title"],
                "current_cluster_id": current_cluster_id,
                "suggested_cluster_id": best_cluster_id,
                "suggested_cluster_name": clusters.get(best_cluster_id, "Suggested cluster"),
                "confidence": round(min(0.99, max(0.0, best_score)), 3),
                "reason": "Source text is closer to this cluster's indexed context.",
            }
        )

    suggestions.sort(key=lambda item: item["confidence"], reverse=True)
    return suggestions[:limit]


def _source_vectors(conn, vault_id: str) -> dict[str, list[float]]:
    selector = active_embedding_selector()
    snapshot = query_epoch_snapshot_conn(
        conn,
        vault_id,
        embedding_model_id=selector["embedding_model_id"],
        index_version=selector["index_version"],
    )
    tuple_clause, tuple_params = chunk_eligibility_sql("", snapshot)
    grouped: dict[str, list[list[float]]] = defaultdict(list)
    rows = conn.execute(
        f"""
        SELECT source_id, embedding
        FROM source_chunks
        WHERE vault_id = ? {tuple_clause}
        """,
        (vault_id, *tuple_params),
    ).fetchall()
    for row in rows:
        vector = decode_embedding(row["embedding"])
        if vector:
            grouped[row["source_id"]].append(vector)
    return {source_id: _average(vectors) for source_id, vectors in grouped.items()}


def _cluster_vectors(conn, vault_id: str, exclude_source_id: str) -> dict[str, list[float]]:
    selector = active_embedding_selector()
    snapshot = query_epoch_snapshot_conn(
        conn,
        vault_id,
        embedding_model_id=selector["embedding_model_id"],
        index_version=selector["index_version"],
    )
    tuple_clause, tuple_params = chunk_eligibility_sql("", snapshot)
    grouped: dict[str, list[list[float]]] = defaultdict(list)
    rows = conn.execute(
        f"""
        SELECT cluster_id, embedding
        FROM source_chunks
        WHERE vault_id = ? AND source_id != ? AND cluster_id IS NOT NULL
          {tuple_clause}
        """,
        (vault_id, exclude_source_id, *tuple_params),
    ).fetchall()
    for row in rows:
        vector = decode_embedding(row["embedding"])
        if vector:
            grouped[row["cluster_id"]].append(vector)
    return {cluster_id: _average(vectors) for cluster_id, vectors in grouped.items()}


def _average(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    dimensions = len(vectors[0])
    averaged = [0.0] * dimensions
    for vector in vectors:
        for index, value in enumerate(vector[:dimensions]):
            averaged[index] += value
    return [value / len(vectors) for value in averaged]
