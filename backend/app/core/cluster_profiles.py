from __future__ import annotations

from collections import Counter, defaultdict
import json
import re

from backend.app.core.database import utc_now
from backend.app.core.derived_state import query_epoch_snapshot_conn
from backend.app.core.embeddings import cosine_similarity, decode_embedding, encode_embedding
from backend.app.core.vector_maintenance import active_embedding_selector


PROFILE_VERSION = 1
MAX_CANDIDATES = 32
MAX_TERMS = 32

_STOPWORDS = {
    "about", "after", "also", "and", "are", "attachment", "before", "chat",
    "document", "documents", "file", "files", "for", "from", "have", "into",
    "page", "pages", "source", "sources", "stored", "that", "the", "their",
    "this", "user", "vault", "what", "with",
}


def terms_for_text(text: str, *, limit: int = MAX_TERMS) -> list[str]:
    counts = Counter(
        token
        for token in re.findall(r"[a-z][a-z0-9+'-]{2,}", str(text or "").casefold())
        if token not in _STOPWORDS and not token.startswith(("http", "www"))
    )
    return [term for term, _count in counts.most_common(limit)]


def publish_cluster_candidate_profile(
    conn,
    *,
    cluster_id: str,
    source_hash: str,
    sources: list[dict],
) -> None:
    cluster = conn.execute(
        "SELECT vault_id FROM clusters WHERE id = ?",
        (cluster_id,),
    ).fetchone()
    if cluster is None:
        return
    vault_id = str(cluster["vault_id"])
    selector = active_embedding_selector()
    snapshot = query_epoch_snapshot_conn(
        conn,
        vault_id,
        embedding_model_id=selector["embedding_model_id"],
        index_version=selector["index_version"],
    )
    source_ids = [str(source.get("id") or "") for source in sources if source.get("id")]
    source_types = Counter(str(source.get("source_type") or "unknown") for source in sources)
    term_counts: Counter[str] = Counter()
    for source in sources:
        title = str(source.get("title") or "")
        summary = str(source.get("summary") or "")
        tags = str(source.get("tags") or "")
        for term in terms_for_text(f"{title} {title} {summary} {tags}"):
            term_counts[term] += 1
    weighted_terms = {
        term: round(count / max(1, len(sources)), 6)
        for term, count in term_counts.most_common(MAX_TERMS)
    }
    centroid, cohesion = _cluster_centroid(conn, cluster_id=cluster_id, snapshot=snapshot)
    representatives = sorted(
        sources,
        key=lambda source: (
            -len(str(source.get("summary") or "")),
            str(source.get("title") or "").casefold(),
            str(source.get("id") or ""),
        ),
    )[:5]
    representative_ids = [str(source["id"]) for source in representatives if source.get("id")]
    now = utc_now()
    conn.execute(
        """
        INSERT INTO cluster_candidate_profiles (
            cluster_id, vault_id, profile_version, source_hash, derived_state_tuple,
            centroid, lexical_terms, source_type_distribution, representative_source_ids,
            cohesion, status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?)
        ON CONFLICT(cluster_id) DO UPDATE SET
            vault_id = excluded.vault_id,
            profile_version = excluded.profile_version,
            source_hash = excluded.source_hash,
            derived_state_tuple = excluded.derived_state_tuple,
            centroid = excluded.centroid,
            lexical_terms = excluded.lexical_terms,
            source_type_distribution = excluded.source_type_distribution,
            representative_source_ids = excluded.representative_source_ids,
            cohesion = excluded.cohesion,
            status = 'ready',
            updated_at = excluded.updated_at
        """,
        (
            cluster_id,
            vault_id,
            PROFILE_VERSION,
            source_hash,
            json.dumps(snapshot, sort_keys=True, separators=(",", ":")),
            encode_embedding(centroid) if centroid else "",
            json.dumps(weighted_terms, sort_keys=True, separators=(",", ":")),
            json.dumps(source_types, sort_keys=True, separators=(",", ":")),
            json.dumps(representative_ids, separators=(",", ":")),
            cohesion,
            now,
            now,
        ),
    )
    conn.execute("DELETE FROM cluster_candidate_terms WHERE cluster_id = ?", (cluster_id,))
    conn.executemany(
        """
        INSERT INTO cluster_candidate_terms (cluster_id, vault_id, term, weight)
        VALUES (?, ?, ?, ?)
        """,
        [(cluster_id, vault_id, term, weight) for term, weight in weighted_terms.items()],
    )


def shortlist_cluster_candidates(
    conn,
    *,
    vault_id: str,
    text: str,
    limit: int = MAX_CANDIDATES,
) -> list[dict]:
    terms = terms_for_text(text, limit=12)
    if not terms:
        return []
    placeholders = ",".join("?" for _term in terms)
    rows = conn.execute(
        f"""
        SELECT profiles.*, SUM(candidate_terms.weight) AS lexical_score
        FROM cluster_candidate_terms candidate_terms
        JOIN cluster_candidate_profiles profiles
          ON profiles.cluster_id = candidate_terms.cluster_id
        WHERE candidate_terms.vault_id = ?
          AND candidate_terms.term IN ({placeholders})
          AND profiles.status = 'ready'
          AND profiles.profile_version = ?
          AND NOT EXISTS (
              SELECT 1 FROM project_cluster_links links
              WHERE links.cluster_id = profiles.cluster_id
          )
        GROUP BY profiles.cluster_id
        ORDER BY lexical_score DESC, profiles.cluster_id
        LIMIT ?
        """,
        (vault_id, *terms, PROFILE_VERSION, max(1, min(int(limit), MAX_CANDIDATES))),
    ).fetchall()
    return [
        {
            "cluster_id": str(row["cluster_id"]),
            "profile_hash": str(row["source_hash"]),
            "profile_version": int(row["profile_version"]),
            "lexical_score": float(row["lexical_score"] or 0),
            "cohesion": float(row["cohesion"] or 0),
            "centroid": decode_embedding(str(row["centroid"] or "")),
            "terms": json.loads(row["lexical_terms"] or "{}"),
            "source_types": json.loads(row["source_type_distribution"] or "{}"),
        }
        for row in rows
    ]


def _cluster_centroid(conn, *, cluster_id: str, snapshot: dict) -> tuple[list[float], float]:
    rows = conn.execute(
        """
        SELECT chunks.source_id, chunks.embedding
        FROM source_chunks chunks
        JOIN sources ON sources.id = chunks.source_id
        WHERE chunks.cluster_id = ?
          AND chunks.activation_state = 'active'
          AND sources.deleted_at IS NULL
          AND sources.source_type <> 'chat_transcript'
          AND chunks.embedding_model_id = ?
          AND chunks.index_version = ?
          AND chunks.normalization_version = ?
          AND chunks.extraction_version = ?
          AND chunks.derived_state_epoch = ?
        """,
        (
            cluster_id,
            snapshot["embedding_model_id"],
            snapshot["index_version"],
            snapshot["normalization_version"],
            snapshot["extraction_version"],
            snapshot["epoch"],
        ),
    ).fetchall()
    source_sums: dict[str, list[float]] = {}
    source_counts: defaultdict[str, int] = defaultdict(int)
    for row in rows:
        vector = decode_embedding(row["embedding"])
        if not vector:
            continue
        source_id = str(row["source_id"])
        if source_id not in source_sums:
            source_sums[source_id] = [0.0] * len(vector)
        for index, value in enumerate(vector[: len(source_sums[source_id])]):
            source_sums[source_id][index] += value
        source_counts[source_id] += 1
    source_vectors = [
        [value / source_counts[source_id] for value in vector]
        for source_id, vector in source_sums.items()
        if source_counts[source_id] > 0
    ]
    if not source_vectors:
        return [], 0.0
    dimensions = min(len(vector) for vector in source_vectors)
    centroid = [
        sum(vector[index] for vector in source_vectors) / len(source_vectors)
        for index in range(dimensions)
    ]
    cohesion = sum(cosine_similarity(vector[:dimensions], centroid) for vector in source_vectors)
    return centroid, round(cohesion / len(source_vectors), 6)
