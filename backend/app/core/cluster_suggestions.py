from collections import defaultdict

from backend.app.core.derived_state import chunk_eligibility_sql, query_epoch_snapshot_conn
from backend.app.core.embeddings import cosine_similarity, decode_embedding
from backend.app.core.vector_maintenance import active_embedding_selector


def suggest_source_cluster_moves(conn, vault_id: str, limit: int = 12) -> list[dict]:
    vectors = _vector_aggregates(conn, vault_id)
    source_vectors = vectors["source_vectors"]
    if not source_vectors:
        return []

    rows = conn.execute(
        """
        SELECT sources.id, sources.title, sources.cluster_id, sources.updated_at,
               clusters.name AS current_cluster_name,
               decisions.source_updated_at AS decision_source_updated_at
        FROM sources
        LEFT JOIN clusters ON clusters.id = sources.cluster_id
        LEFT JOIN cluster_suggestion_decisions decisions ON decisions.source_id = sources.id
        WHERE sources.vault_id = ? AND sources.state = 'indexed' AND sources.deleted_at IS NULL
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
        if row["decision_source_updated_at"] == row["updated_at"]:
            continue
        source_id = row["id"]
        source_vector = source_vectors.get(source_id)
        if source_vector is None:
            continue
        cluster_vectors = _cluster_vectors_excluding_source(
            vectors,
            source_id=source_id,
            source_cluster_id=row["cluster_id"],
        )
        if not cluster_vectors:
            continue

        scored = [
            (cosine_similarity(source_vector, cluster_vector), cluster_id)
            for cluster_id, cluster_vector in cluster_vectors.items()
        ]
        best_score, best_cluster_id = max(scored)
        current_cluster_id = row["cluster_id"]
        current_score = next(
            (score for score, cluster_id in scored if cluster_id == current_cluster_id),
            0.0,
        )
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


def _vector_aggregates(conn, vault_id: str) -> dict:
    selector = active_embedding_selector()
    snapshot = query_epoch_snapshot_conn(
        conn,
        vault_id,
        embedding_model_id=selector["embedding_model_id"],
        index_version=selector["index_version"],
    )
    tuple_clause, tuple_params = chunk_eligibility_sql("source_chunks", snapshot)
    rows = conn.execute(
        f"""
        SELECT source_id, cluster_id, embedding
        FROM source_chunks
        WHERE vault_id = ? {tuple_clause}
        """,
        (vault_id, *tuple_params),
    ).fetchall()
    source_sums: dict[str, list[float]] = {}
    source_counts: dict[str, int] = defaultdict(int)
    source_cluster_ids: dict[str, str | None] = {}
    cluster_sums: dict[str, list[float]] = {}
    cluster_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        vector = decode_embedding(row["embedding"])
        if not vector:
            continue
        source_id = str(row["source_id"])
        cluster_id = str(row["cluster_id"]) if row["cluster_id"] else None
        source_cluster_ids[source_id] = cluster_id
        _add_vector(source_sums, source_id, vector)
        source_counts[source_id] += 1
        if cluster_id:
            _add_vector(cluster_sums, cluster_id, vector)
            cluster_counts[cluster_id] += 1
    return {
        "source_vectors": {
            source_id: _divide(vector_sum, source_counts[source_id])
            for source_id, vector_sum in source_sums.items()
        },
        "source_sums": source_sums,
        "source_counts": source_counts,
        "source_cluster_ids": source_cluster_ids,
        "cluster_sums": cluster_sums,
        "cluster_counts": cluster_counts,
    }


def _cluster_vectors_excluding_source(
    vectors: dict,
    *,
    source_id: str,
    source_cluster_id: str | None,
) -> dict[str, list[float]]:
    result: dict[str, list[float]] = {}
    for cluster_id, cluster_sum in vectors["cluster_sums"].items():
        count = vectors["cluster_counts"][cluster_id]
        if cluster_id == source_cluster_id:
            count -= vectors["source_counts"].get(source_id, 0)
            if count <= 0:
                continue
            source_sum = vectors["source_sums"].get(source_id, [])
            result[cluster_id] = _divide(
                [value - source_sum[index] for index, value in enumerate(cluster_sum)],
                count,
            )
        else:
            result[cluster_id] = _divide(cluster_sum, count)
    return result


def _add_vector(target: dict[str, list[float]], key: str, vector: list[float]) -> None:
    if key not in target:
        target[key] = [0.0] * len(vector)
    for index, value in enumerate(vector[: len(target[key])]):
        target[key][index] += value


def _divide(vector: list[float], count: int) -> list[float]:
    return [value / count for value in vector] if count > 0 else []
