import json
import re
from collections import OrderedDict
from hashlib import sha256

from backend.app.core.database import dict_from_row, utc_now
from backend.app.core.cluster_profiles import publish_cluster_candidate_profile
from backend.app.core.encrypted_storage import load_source_content_fields
from backend.app.core.semantic_metadata import enrich_cluster_metadata


def mark_cluster_needs_update(conn, cluster_id: str | None, detail: str) -> None:
    if not cluster_id:
        return
    row = conn.execute(
        "SELECT id, vault_id, index_status, profile_status FROM clusters WHERE id = ?",
        (cluster_id,),
    ).fetchone()
    if row is None:
        return
    lifecycle = _cluster_rag_lifecycle(conn, cluster_id)
    now = utc_now()
    conn.execute(
        """
        UPDATE clusters
        SET index_status = ?,
            profile_status = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            lifecycle["index_status"],
            lifecycle["profile_status"],
            now,
            cluster_id,
        ),
    )
    from backend.app.core.background_jobs import enqueue_job

    enqueue_job(
        conn,
        job_type="refresh_cluster_profile",
        payload={"cluster_id": cluster_id, "vault_id": row["vault_id"]},
        dedupe_key=f"refresh-cluster-profile:{cluster_id}",
        scope_id=cluster_id,
    )


def mark_cluster_metadata_pending(conn, cluster_id: str | None) -> None:
    """Expose fresh index state while semantic metadata waits for its serialized job."""
    if not cluster_id:
        return
    lifecycle = _cluster_rag_lifecycle(conn, cluster_id)
    conn.execute(
        """
        UPDATE clusters
        SET index_status = ?, profile_status = 'stale', updated_at = ?
        WHERE id = ?
        """,
        (lifecycle["index_status"], utc_now(), cluster_id),
    )


def prune_empty_auto_cluster(conn, cluster_id: str | None) -> bool:
    """Remove an abandoned generated cluster without touching user-created spaces."""
    if not cluster_id:
        return False
    cluster = conn.execute(
        "SELECT id, name_origin FROM clusters WHERE id = ?",
        (cluster_id,),
    ).fetchone()
    if cluster is None or str(cluster["name_origin"] or "user") != "auto":
        return False
    blockers = conn.execute(
        """
        SELECT
            EXISTS(
                SELECT 1 FROM sources
                WHERE cluster_id = ? AND deleted_at IS NULL
            ) AS has_sources,
            EXISTS(
                SELECT 1 FROM chat_sessions
                WHERE scope_cluster_id = ?
            ) AS has_chats,
            EXISTS(
                SELECT 1 FROM projects
                WHERE primary_cluster_id = ? AND deleted_at IS NULL
            ) AS has_primary_project,
            EXISTS(
                SELECT 1 FROM project_cluster_links
                WHERE cluster_id = ?
            ) AS has_project_link
        """,
        (cluster_id, cluster_id, cluster_id, cluster_id),
    ).fetchone()
    if any(int(blockers[key] or 0) for key in blockers.keys()):
        return False
    conn.execute(
        "DELETE FROM cluster_suggestion_decisions WHERE suggested_cluster_id = ?",
        (cluster_id,),
    )
    conn.execute("DELETE FROM clusters WHERE id = ?", (cluster_id,))
    return True


def refresh_cluster_profile(
    conn,
    cluster_id: str,
    *,
    require_model: bool = False,
) -> dict[str, str]:
    lifecycle = _cluster_rag_lifecycle(conn, cluster_id)
    row = conn.execute(
        """
        SELECT
            id,
            name,
            name_origin,
            description,
            cluster_summary,
            cluster_glossary,
            profile_source_hash,
            profile_updated_at
        FROM clusters
        WHERE id = ?
        """,
        (cluster_id,),
    ).fetchone()
    if row is None:
        return lifecycle
    if lifecycle["index_status"] == "empty":
        summary = ""
        glossary = "[]"
        profile_status = "missing"
        profile_updated_at = None
        profile_source_hash = ""
        indexed_source_count = 0
        conn.execute("DELETE FROM cluster_candidate_profiles WHERE cluster_id = ?", (cluster_id,))
    elif lifecycle["index_status"] == "error":
        summary = ""
        glossary = "[]"
        profile_status = "error"
        profile_updated_at = None
        profile_source_hash = ""
        indexed_source_count = 0
        conn.execute("DELETE FROM cluster_candidate_profiles WHERE cluster_id = ?", (cluster_id,))
    else:
        source_metadata = conn.execute(
            """
            SELECT id, vault_id, checksum, updated_at
            FROM sources
            WHERE cluster_id = ? AND deleted_at IS NULL AND state = 'indexed'
            ORDER BY updated_at DESC, created_at DESC
            """,
            (cluster_id,),
        ).fetchall()
        metadata_rows = [dict_from_row(source) for source in source_metadata]
        indexed_source_count = len(metadata_rows)
        profile_source_hash = _compute_profile_source_hash(metadata_rows)
        previous_hash = str(row["profile_source_hash"] or "")
        previous_summary = str(row["cluster_summary"] or "")
        previous_glossary = str(row["cluster_glossary"] or "[]")
        previous_updated_at = row["profile_updated_at"]
        candidate_profile = conn.execute(
            "SELECT 1 FROM cluster_candidate_profiles WHERE cluster_id = ?",
            (cluster_id,),
        ).fetchone()
        if indexed_source_count == 0:
            summary = ""
            glossary = "[]"
            profile_status = "missing"
            profile_updated_at = None
            profile_source_hash = ""
        elif (
            profile_source_hash == previous_hash
            and previous_summary.strip()
            and previous_glossary.strip()
            and candidate_profile is not None
        ):
            summary = previous_summary
            glossary = previous_glossary
            profile_status = "ready"
            profile_updated_at = previous_updated_at or utc_now()
        else:
            sources = conn.execute(
                """
                SELECT id, vault_id, checksum, updated_at, title, source_type, summary, tags,
                       extracted_text, raw_text
                FROM sources
                WHERE cluster_id = ? AND deleted_at IS NULL AND state = 'indexed'
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 50
                """,
                (cluster_id,),
            ).fetchall()
            source_rows: list[dict] = []
            for source in sources:
                source_row = dict_from_row(source)
                encrypted_fields = load_source_content_fields(
                    conn,
                    vault_id=str(source_row["vault_id"]),
                    source_id=str(source_row["id"]),
                    fields=("summary", "extracted_text", "raw_text"),
                )
                source_row.update({key: value for key, value in encrypted_fields.items() if value})
                source_rows.append(source_row)
            generated_metadata = enrich_cluster_metadata(
                source_rows,
                require_model=require_model,
            )
            effective_name = str(row["name"] or "").strip()
            effective_description = str(row["description"] or "").strip()
            if str(row["name_origin"] or "user") == "auto":
                effective_name = generated_metadata["name"]
                effective_description = generated_metadata["description"]
                conn.execute(
                    "UPDATE clusters SET name = ?, description = ? WHERE id = ?",
                    (effective_name, effective_description, cluster_id),
                )
            summary = generated_metadata["summary"] or _build_cluster_summary(
                cluster_name=effective_name,
                description=effective_description,
                sources=source_rows,
            )
            glossary = json.dumps(_build_cluster_glossary(source_rows), separators=(",", ":"))
            profile_status = "ready"
            profile_updated_at = utc_now()
            publish_cluster_candidate_profile(
                conn,
                cluster_id=cluster_id,
                source_hash=profile_source_hash,
                sources=source_rows,
            )
    conn.execute(
        """
        UPDATE clusters
        SET index_status = ?,
            profile_status = ?,
            cluster_summary = ?,
            cluster_glossary = ?,
            profile_updated_at = ?,
            profile_source_hash = ?,
            indexed_source_count = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            lifecycle["index_status"],
            profile_status,
            summary,
            glossary,
            profile_updated_at,
            profile_source_hash,
            indexed_source_count,
            utc_now(),
            cluster_id,
        ),
    )
    return {
        "index_status": lifecycle["index_status"],
        "profile_status": profile_status,
        "cluster_summary": summary,
        "cluster_glossary": glossary,
    }


def _compute_profile_source_hash(sources: list[dict]) -> str:
    if not sources:
        return ""
    digest = sha256()
    for source in sorted(sources, key=lambda item: str(item.get("id") or "")):
        digest.update(str(source.get("id") or "").encode("utf-8"))
        digest.update(b"|")
        digest.update(str(source.get("checksum") or "").encode("utf-8"))
        digest.update(b"|")
        digest.update(str(source.get("updated_at") or "").encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _build_cluster_summary(*, cluster_name: str, description: str, sources: list[dict]) -> str:
    title_examples = [str(source.get("title") or "").strip() for source in sources if str(source.get("title") or "").strip()]
    source_summaries = [
        str(source.get("summary") or "").strip()
        for source in sources
        if str(source.get("summary") or "").strip()
    ]
    lead = source_summaries[0] if source_summaries else description
    if not lead:
        lead = f"Sources about {cluster_name}." if cluster_name else "Related sources."
    if not title_examples:
        return lead[:320]
    focus = ", ".join(title_examples[:3])
    return f"{lead} Includes {focus}."[:320]


def _build_cluster_glossary(sources) -> list[str]:
    token_counts: OrderedDict[str, None] = OrderedDict()
    for row in sources:
        for field in ("title", "summary", "extracted_text", "raw_text"):
            text = str(row[field] or "").strip()
            if not text:
                continue
            for token in re.findall(r"\b[A-Za-z][A-Za-z0-9_-]{3,}\b", text):
                lower = token.lower()
                if lower in {"source", "note", "page", "chunk", "with", "from", "this", "that"}:
                    continue
                token_counts.setdefault(token, None)
                if len(token_counts) >= 12:
                    return list(token_counts.keys())
    return list(token_counts.keys())


def _cluster_rag_lifecycle(conn, cluster_id: str) -> dict[str, str]:
    counts = conn.execute(
        """
        SELECT
            COUNT(*) AS total_count,
            SUM(CASE WHEN state = 'indexed' THEN 1 ELSE 0 END) AS indexed_count,
            SUM(CASE WHEN state IN ('waiting', 'processing', 'extracting') THEN 1 ELSE 0 END) AS indexing_count,
            SUM(CASE WHEN state = 'failed' THEN 1 ELSE 0 END) AS failed_count
        FROM sources
        WHERE cluster_id = ? AND deleted_at IS NULL
        """,
        (cluster_id,),
    ).fetchone()
    total_count = int(counts["total_count"] or 0)
    indexed_count = int(counts["indexed_count"] or 0)
    indexing_count = int(counts["indexing_count"] or 0)
    failed_count = int(counts["failed_count"] or 0)
    if total_count == 0:
        return {"index_status": "empty", "profile_status": "missing"}
    if failed_count:
        return {"index_status": "error", "profile_status": "error"}
    if indexing_count:
        return {"index_status": "indexing", "profile_status": "refreshing" if indexed_count == 0 else "stale"}
    if indexed_count:
        return {"index_status": "ready", "profile_status": "stale"}
    return {"index_status": "empty", "profile_status": "missing"}
