import sqlite3
from uuid import uuid4

from backend.app.core.cluster_profiles import shortlist_cluster_candidates, terms_for_text
from backend.app.core.database import utc_now
from backend.app.core.derived_state import chunk_eligibility_sql, query_epoch_snapshot_conn
from backend.app.core.embeddings import cosine_similarity, decode_embedding
from backend.app.core.vector_maintenance import active_embedding_selector

MAX_SOURCES_PER_REVIEW = 240
MIN_SUGGESTION_SCORE = 0.58
MIN_SUGGESTION_MARGIN = 0.12
MIN_TARGET_COHESION = 0.45


def list_or_create_source_cluster_move_batch(
    conn,
    vault_id: str,
    *,
    limit: int = 12,
    refresh: bool = False,
) -> list[dict]:
    """Return one stable review batch until the user explicitly requests another."""
    safe_limit = max(1, min(int(limit), 30))
    if refresh:
        _complete_active_batches(conn, vault_id)

    active_batch = conn.execute(
        """
        SELECT id
        FROM cluster_suggestion_batches
        WHERE vault_id = ? AND status = 'active'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (vault_id,),
    ).fetchone()
    if active_batch is not None:
        suggestions = _pending_batch_suggestions(
            conn,
            vault_id=vault_id,
            batch_id=str(active_batch["id"]),
            limit=safe_limit,
        )
        if suggestions:
            return suggestions
        _complete_batch(conn, str(active_batch["id"]))
        return []

    has_previous_batch = conn.execute(
        "SELECT 1 FROM cluster_suggestion_batches WHERE vault_id = ? LIMIT 1",
        (vault_id,),
    ).fetchone()
    if has_previous_batch is not None and not refresh:
        return []

    computed = suggest_source_cluster_moves(conn, vault_id, limit=12)
    now = utc_now()
    batch_id = f"cluster-suggestion-batch-{uuid4()}"
    try:
        conn.execute(
            """
            INSERT INTO cluster_suggestion_batches (
                id, vault_id, status, created_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                vault_id,
                "active" if computed else "completed",
                now,
                None if computed else now,
            ),
        )
    except sqlite3.IntegrityError:
        concurrent_batch = conn.execute(
            """
            SELECT id FROM cluster_suggestion_batches
            WHERE vault_id = ? AND status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (vault_id,),
        ).fetchone()
        if concurrent_batch is None:
            raise
        return _pending_batch_suggestions(
            conn,
            vault_id=vault_id,
            batch_id=str(concurrent_batch["id"]),
            limit=safe_limit,
        )
    for suggestion in computed:
        source = conn.execute(
            "SELECT updated_at, checksum, metadata_version FROM sources WHERE id = ?",
            (suggestion["source_id"],),
        ).fetchone()
        if source is None:
            continue
        conn.execute(
            """
            INSERT INTO cluster_suggestion_candidates (
                id, batch_id, vault_id, source_id, current_cluster_id,
                suggested_cluster_id, confidence, reason, source_updated_at,
                source_content_hash, candidate_profile_hash, candidate_profile_version,
                decision, decided_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
            """,
            (
                f"cluster-suggestion-{uuid4()}",
                batch_id,
                vault_id,
                suggestion["source_id"],
                suggestion["current_cluster_id"],
                suggestion["suggested_cluster_id"],
                suggestion["confidence"],
                suggestion["reason"],
                source["updated_at"],
                suggestion.get("source_content_hash")
                or str(source["checksum"] or "")
                or f"meta:{int(source['metadata_version'] or 0)}:{source['updated_at']}",
                suggestion.get("candidate_profile_hash") or "",
                int(suggestion.get("candidate_profile_version") or 0),
                now,
            ),
        )
    return computed[:safe_limit]


def record_source_cluster_move_batch_decision(
    conn,
    *,
    vault_id: str,
    source_id: str,
    suggested_cluster_id: str,
    action: str,
    decided_at: str,
) -> None:
    candidate = conn.execute(
        """
        SELECT candidates.id, candidates.batch_id
        FROM cluster_suggestion_candidates candidates
        JOIN cluster_suggestion_batches batches ON batches.id = candidates.batch_id
        WHERE candidates.vault_id = ?
          AND candidates.source_id = ?
          AND candidates.suggested_cluster_id = ?
          AND candidates.decision IS NULL
          AND batches.status = 'active'
        ORDER BY candidates.created_at DESC
        LIMIT 1
        """,
        (vault_id, source_id, suggested_cluster_id),
    ).fetchone()
    if candidate is None:
        return
    conn.execute(
        """
        UPDATE cluster_suggestion_candidates
        SET decision = ?, decided_at = ?
        WHERE id = ?
        """,
        (action, decided_at, candidate["id"]),
    )
    remaining = conn.execute(
        """
        SELECT 1
        FROM cluster_suggestion_candidates
        WHERE batch_id = ? AND decision IS NULL
        LIMIT 1
        """,
        (candidate["batch_id"],),
    ).fetchone()
    if remaining is None:
        _complete_batch(conn, str(candidate["batch_id"]), completed_at=decided_at)


def suggest_source_cluster_moves(conn, vault_id: str, limit: int = 12) -> list[dict]:
    rows = conn.execute(
        """
        SELECT sources.id, sources.title, sources.summary, sources.source_type,
               sources.cluster_id, sources.updated_at, sources.checksum,
               sources.metadata_version,
               clusters.name AS current_cluster_name,
               decisions.source_content_hash AS decision_source_content_hash,
               decisions.candidate_profile_hash AS decision_profile_hash,
               decisions.candidate_profile_version AS decision_profile_version,
               decision_profile.source_hash AS current_decision_profile_hash,
               decision_profile.profile_version AS current_decision_profile_version
        FROM sources
        LEFT JOIN clusters ON clusters.id = sources.cluster_id
        LEFT JOIN cluster_suggestion_decisions decisions
          ON decisions.source_id = sources.id
        LEFT JOIN cluster_candidate_profiles decision_profile
          ON decision_profile.cluster_id = decisions.suggested_cluster_id
        WHERE sources.vault_id = ?
          AND sources.state = 'indexed'
          AND sources.deleted_at IS NULL
          AND sources.project_id IS NULL
          AND (
              decisions.source_id IS NULL
              OR decisions.source_content_hash <> (
                  CASE WHEN sources.checksum <> '' THEN sources.checksum
                       ELSE 'meta:' || sources.metadata_version || ':' || sources.updated_at END
              )
              OR decisions.candidate_profile_hash <> COALESCE(decision_profile.source_hash, '')
              OR decisions.candidate_profile_version <> COALESCE(decision_profile.profile_version, 0)
          )
        ORDER BY sources.updated_at DESC, sources.id
        LIMIT ?
        """,
        (vault_id, MAX_SOURCES_PER_REVIEW),
    ).fetchall()
    if not rows:
        return []
    source_vectors = _source_vectors(conn, vault_id, [str(row["id"]) for row in rows])

    suggestions: list[dict] = []
    for row in rows:
        source_id = row["id"]
        source_vector = source_vectors.get(source_id)
        if source_vector is None:
            continue
        evidence_text = f"{row['title']} {row['title']} {row['summary'] or ''}"
        candidates = shortlist_cluster_candidates(
            conn,
            vault_id=vault_id,
            text=evidence_text,
        )
        candidates = _include_current_profile(
            conn,
            candidates,
            current_cluster_id=str(row["cluster_id"]) if row["cluster_id"] else None,
        )
        if not candidates:
            continue
        source_terms = set(terms_for_text(evidence_text, limit=16))
        scored: list[tuple[float, dict]] = []
        for candidate in candidates:
            centroid = candidate["centroid"]
            if not centroid:
                continue
            semantic = max(0.0, cosine_similarity(source_vector, centroid))
            lexical_overlap = sum(
                float(candidate["terms"].get(term, 0.0)) for term in source_terms
            )
            lexical = min(1.0, lexical_overlap / max(1.0, len(source_terms) * 0.2))
            source_types = candidate["source_types"]
            total_types = sum(int(count) for count in source_types.values())
            type_compatibility = (
                int(source_types.get(str(row["source_type"] or "unknown"), 0)) / total_types
                if total_types
                else 0.0
            )
            cohesion = float(candidate["cohesion"])
            score = (
                (0.68 * semantic)
                + (0.20 * lexical)
                + (0.07 * type_compatibility)
                + (0.05 * max(0.0, cohesion))
            )
            scored.append((score, candidate))
        if not scored:
            continue
        scored.sort(key=lambda item: (item[0], item[1]["cluster_id"]), reverse=True)
        best_score, best_candidate = scored[0]
        best_cluster_id = str(best_candidate["cluster_id"])
        current_cluster_id = row["cluster_id"]
        current_score = next(
            (score for score, candidate in scored if candidate["cluster_id"] == current_cluster_id),
            0.0,
        )
        competing_score = max(
            (score for score, candidate in scored if candidate["cluster_id"] != best_cluster_id),
            default=0.0,
        )
        if best_cluster_id == current_cluster_id:
            continue
        if (
            best_score < MIN_SUGGESTION_SCORE
            or best_score - max(current_score, competing_score) < MIN_SUGGESTION_MARGIN
            or (
                float(best_candidate["cohesion"]) > 0
                and float(best_candidate["cohesion"]) < MIN_TARGET_COHESION
            )
        ):
            continue
        target = conn.execute(
            "SELECT name FROM clusters WHERE id = ? AND vault_id = ?",
            (best_cluster_id, vault_id),
        ).fetchone()
        if target is None:
            continue
        source_content_hash = str(row["checksum"] or "") or (
            f"meta:{int(row['metadata_version'] or 0)}:{row['updated_at']}"
        )
        suggestions.append(
            {
                "source_id": source_id,
                "source_title": row["title"],
                "current_cluster_id": current_cluster_id,
                "suggested_cluster_id": best_cluster_id,
                "suggested_cluster_name": str(target["name"]),
                "confidence": round(min(0.99, max(0.0, best_score)), 3),
                "reason": "Source text is closer to this cluster's indexed context.",
                "source_content_hash": source_content_hash,
                "candidate_profile_hash": str(best_candidate["profile_hash"]),
                "candidate_profile_version": int(best_candidate["profile_version"]),
            }
        )

    suggestions.sort(key=lambda item: item["confidence"], reverse=True)
    return suggestions[:limit]


def _pending_batch_suggestions(
    conn,
    *,
    vault_id: str,
    batch_id: str,
    limit: int,
) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            candidates.id,
            candidates.source_id,
            sources.title AS source_title,
            candidates.current_cluster_id,
            candidates.suggested_cluster_id,
            target.name AS suggested_cluster_name,
            candidates.confidence,
            candidates.reason,
            candidates.source_updated_at,
            candidates.source_content_hash,
            candidates.candidate_profile_hash,
            candidates.candidate_profile_version,
            sources.updated_at AS current_source_updated_at,
            sources.checksum AS current_source_content_hash,
            sources.metadata_version AS current_metadata_version,
            sources.cluster_id AS actual_cluster_id
        FROM cluster_suggestion_candidates candidates
        LEFT JOIN sources ON sources.id = candidates.source_id
        LEFT JOIN clusters target ON target.id = candidates.suggested_cluster_id
        WHERE candidates.batch_id = ?
          AND candidates.vault_id = ?
          AND candidates.decision IS NULL
        ORDER BY candidates.confidence DESC, candidates.created_at ASC
        """,
        (batch_id, vault_id),
    ).fetchall()
    suggestions: list[dict] = []
    stale_ids: list[str] = []
    for row in rows:
        if (
            row["source_title"] is None
            or row["suggested_cluster_name"] is None
            or row["actual_cluster_id"] != row["current_cluster_id"]
            or row["source_content_hash"] != (
                str(row["current_source_content_hash"] or "")
                or f"meta:{int(row['current_metadata_version'] or 0)}:{row['current_source_updated_at']}"
            )
            or not _candidate_profile_matches(conn, row)
        ):
            stale_ids.append(str(row["id"]))
            continue
        suggestions.append(
            {
                "source_id": row["source_id"],
                "source_title": row["source_title"],
                "current_cluster_id": row["current_cluster_id"],
                "suggested_cluster_id": row["suggested_cluster_id"],
                "suggested_cluster_name": row["suggested_cluster_name"],
                "confidence": float(row["confidence"]),
                "reason": row["reason"],
            }
        )
    if stale_ids:
        now = utc_now()
        conn.executemany(
            """
            UPDATE cluster_suggestion_candidates
            SET decision = 'stale', decided_at = ?
            WHERE id = ?
            """,
            [(now, candidate_id) for candidate_id in stale_ids],
        )
    return suggestions[:limit]


def _complete_active_batches(conn, vault_id: str) -> None:
    now = utc_now()
    conn.execute(
        """
        UPDATE cluster_suggestion_candidates
        SET decision = 'superseded', decided_at = ?
        WHERE decision IS NULL
          AND batch_id IN (
              SELECT id FROM cluster_suggestion_batches
              WHERE vault_id = ? AND status = 'active'
          )
        """,
        (now, vault_id),
    )
    conn.execute(
        """
        UPDATE cluster_suggestion_batches
        SET status = 'completed', completed_at = ?
        WHERE vault_id = ? AND status = 'active'
        """,
        (now, vault_id),
    )


def _complete_batch(conn, batch_id: str, *, completed_at: str | None = None) -> None:
    conn.execute(
        """
        UPDATE cluster_suggestion_batches
        SET status = 'completed', completed_at = ?
        WHERE id = ? AND status = 'active'
        """,
        (completed_at or utc_now(), batch_id),
    )


def _source_vectors(conn, vault_id: str, source_ids: list[str]) -> dict[str, list[float]]:
    if not source_ids:
        return {}
    selector = active_embedding_selector()
    snapshot = query_epoch_snapshot_conn(
        conn,
        vault_id,
        embedding_model_id=selector["embedding_model_id"],
        index_version=selector["index_version"],
    )
    tuple_clause, tuple_params = chunk_eligibility_sql("source_chunks", snapshot)
    placeholders = ",".join("?" for _source_id in source_ids)
    rows = conn.execute(
        f"""
        SELECT source_id, embedding
        FROM source_chunks
        WHERE vault_id = ? AND project_id IS NULL
          AND source_id IN ({placeholders}) {tuple_clause}
        """,
        (vault_id, *source_ids, *tuple_params),
    ).fetchall()
    source_sums: dict[str, list[float]] = {}
    source_counts: dict[str, int] = {}
    for row in rows:
        vector = decode_embedding(row["embedding"])
        if not vector:
            continue
        source_id = str(row["source_id"])
        _add_vector(source_sums, source_id, vector)
        source_counts[source_id] = source_counts.get(source_id, 0) + 1
    return {
        source_id: _divide(vector_sum, source_counts[source_id])
        for source_id, vector_sum in source_sums.items()
    }


def _include_current_profile(
    conn,
    candidates: list[dict],
    *,
    current_cluster_id: str | None,
) -> list[dict]:
    if not current_cluster_id or any(
        candidate["cluster_id"] == current_cluster_id for candidate in candidates
    ):
        return candidates
    row = conn.execute(
        """
        SELECT * FROM cluster_candidate_profiles
        WHERE cluster_id = ? AND status = 'ready'
          AND NOT EXISTS (
              SELECT 1 FROM project_cluster_links links
              WHERE links.cluster_id = cluster_candidate_profiles.cluster_id
          )
        """,
        (current_cluster_id,),
    ).fetchone()
    if row is None:
        return candidates
    import json

    return [
        *candidates,
        {
            "cluster_id": str(row["cluster_id"]),
            "profile_hash": str(row["source_hash"]),
            "profile_version": int(row["profile_version"]),
            "lexical_score": 0.0,
            "cohesion": float(row["cohesion"] or 0),
            "centroid": decode_embedding(str(row["centroid"] or "")),
            "terms": json.loads(row["lexical_terms"] or "{}"),
            "source_types": json.loads(row["source_type_distribution"] or "{}"),
        },
    ]


def _candidate_profile_matches(conn, candidate_row) -> bool:
    if (
        not str(candidate_row["candidate_profile_hash"] or "")
        and int(candidate_row["candidate_profile_version"] or 0) == 0
    ):
        return True
    profile = conn.execute(
        """
        SELECT source_hash, profile_version
        FROM cluster_candidate_profiles
        WHERE cluster_id = ? AND status = 'ready'
        """,
        (candidate_row["suggested_cluster_id"],),
    ).fetchone()
    return bool(
        profile is not None
        and str(profile["source_hash"]) == str(candidate_row["candidate_profile_hash"])
        and int(profile["profile_version"]) == int(candidate_row["candidate_profile_version"])
    )


def _add_vector(target: dict[str, list[float]], key: str, vector: list[float]) -> None:
    if key not in target:
        target[key] = [0.0] * len(vector)
    for index, value in enumerate(vector[: len(target[key])]):
        target[key][index] += value


def _divide(vector: list[float], count: int) -> list[float]:
    return [value / count for value in vector] if count > 0 else []
