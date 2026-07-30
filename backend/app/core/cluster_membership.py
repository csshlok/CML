from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from backend.app.core.cluster_lifecycle import (
    mark_cluster_needs_update,
    prune_empty_auto_cluster,
)
from backend.app.core.context_memory import (
    rebuild_source_memory,
    refresh_bootstrap_memory_map,
    refresh_working_memory,
)
from backend.app.core.database import dict_from_row, utc_now
from backend.app.core.retrieval_cache import invalidate_caches_for_source


@dataclass(frozen=True)
class ClusterMembershipResult:
    source_id: str
    vault_id: str
    previous_cluster_id: str | None
    cluster_id: str | None
    source_updated: bool
    chunks_updated: int
    facts_updated: int
    old_cluster_pruned: bool


class ClusterMembershipError(ValueError):
    pass


def move_source_cluster_membership(
    conn,
    *,
    source_id: str,
    target_cluster_id: str | None,
    reason: str,
    actor: str,
    expected_vault_id: str | None = None,
    allowed_project_snapshot_id: str | None = None,
    only_if_unclustered: bool = False,
    update_source_timestamp: bool = True,
    prune_empty_cluster: bool = True,
    refresh_derived_memory: bool = True,
) -> ClusterMembershipResult:
    """Atomically align one source and every active derived membership projection."""
    source_row = conn.execute(
        """
        SELECT id, vault_id, cluster_id, project_id, project_snapshot_id,
               activation_state, deleted_at
        FROM sources
        WHERE id = ?
        """,
        (source_id,),
    ).fetchone()
    if source_row is None or source_row["deleted_at"] is not None:
        raise ClusterMembershipError("source_not_found")
    source = dict_from_row(source_row)
    vault_id = str(source["vault_id"])
    if expected_vault_id is not None and vault_id != expected_vault_id:
        raise ClusterMembershipError("source_vault_mismatch")

    if target_cluster_id is not None:
        target = conn.execute(
            "SELECT id, vault_id FROM clusters WHERE id = ?",
            (target_cluster_id,),
        ).fetchone()
        if target is None:
            raise ClusterMembershipError("target_cluster_not_found")
        if str(target["vault_id"]) != vault_id:
            raise ClusterMembershipError("target_cluster_vault_mismatch")

    project_id = source.get("project_id")
    if project_id:
        project = conn.execute(
            """
            SELECT id, vault_id, primary_cluster_id, active_snapshot_id,
                   candidate_snapshot_id
            FROM projects
            WHERE id = ? AND deleted_at IS NULL
            """,
            (project_id,),
        ).fetchone()
        if project is None or str(project["vault_id"]) != vault_id:
            raise ClusterMembershipError("source_project_invalid")
        if target_cluster_id != project["primary_cluster_id"]:
            raise ClusterMembershipError("project_source_cluster_mismatch")
        source_snapshot_id = allowed_project_snapshot_id or source.get("project_snapshot_id")
        valid_snapshots = {
            str(value)
            for value in (project["active_snapshot_id"], project["candidate_snapshot_id"])
            if value
        }
        if source_snapshot_id and str(source_snapshot_id) not in valid_snapshots:
            raise ClusterMembershipError("project_snapshot_not_active_or_candidate")

    previous_cluster_id = source.get("cluster_id")
    now = utc_now()
    source_updated = False
    if not only_if_unclustered or previous_cluster_id is None:
        timestamp_assignment = ", updated_at = ?" if update_source_timestamp else ""
        params: list[object] = [target_cluster_id]
        if update_source_timestamp:
            params.append(now)
        params.append(source_id)
        unclustered_clause = " AND cluster_id IS NULL" if only_if_unclustered else ""
        result = conn.execute(
            f"""
            UPDATE sources
            SET cluster_id = ?{timestamp_assignment}
            WHERE id = ? AND deleted_at IS NULL{unclustered_clause}
            """,
            params,
        )
        source_updated = result.rowcount == 1

    effective_cluster_id = target_cluster_id if source_updated else previous_cluster_id
    chunks_result = conn.execute(
        """
        UPDATE source_chunks
        SET cluster_id = ?
        WHERE source_id = ? AND activation_state = 'active'
          AND NOT (cluster_id IS ?)
        """,
        (effective_cluster_id, source_id, effective_cluster_id),
    )
    facts_result = conn.execute(
        """
        UPDATE temporal_facts
        SET cluster_id = ?
        WHERE source_id = ? AND NOT (cluster_id IS ?)
        """,
        (effective_cluster_id, source_id, effective_cluster_id),
    )

    conn.execute(
        "DELETE FROM cluster_suggestion_decisions WHERE source_id = ?",
        (source_id,),
    )
    conn.execute(
        """
        UPDATE cluster_suggestion_candidates
        SET decision = 'stale', decided_at = ?
        WHERE source_id = ? AND decision IS NULL
        """,
        (now, source_id),
    )
    invalidate_caches_for_source(source_id, conn=conn)

    membership_changed = previous_cluster_id != effective_cluster_id
    if refresh_derived_memory and (
        membership_changed or chunks_result.rowcount or facts_result.rowcount
    ):
        rebuild_source_memory(conn, source_id=source_id)
        if previous_cluster_id != effective_cluster_id:
            refresh_working_memory(conn, vault_id=vault_id, cluster_id=previous_cluster_id)
            refresh_bootstrap_memory_map(conn, vault_id=vault_id, cluster_id=previous_cluster_id)

    old_cluster_pruned = False
    if membership_changed:
        mark_cluster_needs_update(
            conn,
            effective_cluster_id,
            reason,
        )
        if prune_empty_cluster:
            old_cluster_pruned = prune_empty_auto_cluster(conn, previous_cluster_id)
        if not old_cluster_pruned:
            mark_cluster_needs_update(
                conn,
                previous_cluster_id,
                reason,
            )

    conn.execute(
        """
        INSERT INTO cluster_membership_events (
            id, vault_id, source_id, previous_cluster_id, target_cluster_id,
            reason, actor, source_updated, chunks_updated, facts_updated,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"cluster-membership-{uuid4()}",
            vault_id,
            source_id,
            previous_cluster_id,
            effective_cluster_id,
            reason[:240],
            actor[:120],
            1 if source_updated else 0,
            max(0, int(chunks_result.rowcount)),
            max(0, int(facts_result.rowcount)),
            now,
        ),
    )
    return ClusterMembershipResult(
        source_id=source_id,
        vault_id=vault_id,
        previous_cluster_id=previous_cluster_id,
        cluster_id=effective_cluster_id,
        source_updated=source_updated,
        chunks_updated=max(0, int(chunks_result.rowcount)),
        facts_updated=max(0, int(facts_result.rowcount)),
        old_cluster_pruned=old_cluster_pruned,
    )


def inspect_cluster_membership_batch(
    conn,
    *,
    vault_id: str,
    after_source_id: str | None = None,
    limit: int = 100,
) -> dict:
    safe_limit = max(1, min(int(limit), 500))
    rows = conn.execute(
        """
        SELECT sources.id, sources.cluster_id,
               COUNT(chunks.id) AS active_chunk_count,
               SUM(
                   CASE
                       WHEN chunks.id IS NOT NULL
                        AND NOT (chunks.cluster_id IS sources.cluster_id)
                       THEN 1 ELSE 0
                   END
               ) AS mismatched_chunk_count
        FROM sources
        LEFT JOIN source_chunks chunks
          ON chunks.source_id = sources.id
         AND chunks.activation_state = 'active'
        WHERE sources.vault_id = ?
          AND sources.deleted_at IS NULL
          AND sources.activation_state = 'active'
          AND (? IS NULL OR sources.id > ?)
        GROUP BY sources.id, sources.cluster_id
        ORDER BY sources.id ASC
        LIMIT ?
        """,
        (vault_id, after_source_id, after_source_id, safe_limit),
    ).fetchall()
    items = [
        {
            "source_id": str(row["id"]),
            "cluster_id": row["cluster_id"],
            "active_chunk_count": int(row["active_chunk_count"] or 0),
            "mismatched_chunk_count": int(row["mismatched_chunk_count"] or 0),
        }
        for row in rows
    ]
    return {
        "vault_id": vault_id,
        "items": items,
        "sources_checked": len(items),
        "sources_mismatched": sum(1 for item in items if item["mismatched_chunk_count"]),
        "chunks_mismatched": sum(item["mismatched_chunk_count"] for item in items),
        "next_cursor": items[-1]["source_id"] if len(items) == safe_limit else None,
    }


def summarize_cluster_membership(conn, *, vault_id: str) -> dict:
    row = conn.execute(
        """
        WITH source_membership AS (
            SELECT sources.id,
                   COUNT(chunks.id) AS active_chunk_count,
                   SUM(
                       CASE
                           WHEN chunks.id IS NOT NULL
                            AND NOT (chunks.cluster_id IS sources.cluster_id)
                           THEN 1 ELSE 0
                       END
                   ) AS mismatched_chunk_count
            FROM sources
            LEFT JOIN source_chunks chunks
              ON chunks.source_id = sources.id
             AND chunks.activation_state = 'active'
            WHERE sources.vault_id = ?
              AND sources.deleted_at IS NULL
              AND sources.activation_state = 'active'
            GROUP BY sources.id, sources.cluster_id
        )
        SELECT COUNT(*) AS sources_checked,
               SUM(CASE WHEN mismatched_chunk_count > 0 THEN 1 ELSE 0 END) AS sources_mismatched,
               SUM(mismatched_chunk_count) AS chunks_mismatched,
               SUM(CASE WHEN active_chunk_count = 0 THEN 1 ELSE 0 END) AS sources_without_active_chunks
        FROM source_membership
        """,
        (vault_id,),
    ).fetchone()
    return {
        "vault_id": vault_id,
        "sources_checked": int(row["sources_checked"] or 0),
        "sources_mismatched": int(row["sources_mismatched"] or 0),
        "chunks_mismatched": int(row["chunks_mismatched"] or 0),
        "sources_without_active_chunks": int(row["sources_without_active_chunks"] or 0),
        "consistent": int(row["chunks_mismatched"] or 0) == 0,
    }


def preflight_scoped_cluster_membership(
    conn,
    *,
    vault_id: str,
    cluster_id: str,
    repair_limit: int = 10,
) -> dict:
    rows = conn.execute(
        """
        SELECT sources.id,
               COUNT(chunks.id) AS active_chunk_count,
               SUM(CASE WHEN chunks.cluster_id IS sources.cluster_id THEN 1 ELSE 0 END) AS matching_chunk_count
        FROM sources
        LEFT JOIN source_chunks chunks
          ON chunks.source_id = sources.id
         AND chunks.activation_state = 'active'
        WHERE sources.vault_id = ?
          AND sources.cluster_id = ?
          AND sources.state = 'indexed'
          AND sources.deleted_at IS NULL
          AND sources.activation_state = 'active'
          AND sources.source_type <> 'chat_transcript'
        GROUP BY sources.id
        ORDER BY sources.id
        """,
        (vault_id, cluster_id),
    ).fetchall()
    mismatched = [
        str(row["id"])
        for row in rows
        if int(row["active_chunk_count"] or 0) > int(row["matching_chunk_count"] or 0)
    ]
    without_chunks = [
        str(row["id"])
        for row in rows
        if int(row["active_chunk_count"] or 0) == 0
    ]
    repaired = 0
    if mismatched and len(mismatched) <= max(0, int(repair_limit)):
        for source_id in mismatched:
            move_source_cluster_membership(
                conn,
                source_id=source_id,
                target_cluster_id=cluster_id,
                reason="Scoped retrieval repaired cluster membership.",
                actor="scoped_retrieval_preflight",
                expected_vault_id=vault_id,
                update_source_timestamp=False,
                prune_empty_cluster=False,
            )
            repaired += 1
    return {
        "source_count": len(rows),
        "mismatched_source_count": len(mismatched),
        "sources_without_active_chunks": len(without_chunks),
        "sources_repaired": repaired,
        "repair_pending": len(mismatched) > repaired,
    }


def repair_cluster_membership_batch(
    conn,
    *,
    vault_id: str,
    after_source_id: str | None = None,
    limit: int = 100,
    dry_run: bool = False,
    actor: str = "system_repair",
) -> dict:
    inspection = inspect_cluster_membership_batch(
        conn,
        vault_id=vault_id,
        after_source_id=after_source_id,
        limit=limit,
    )
    repaired_sources = 0
    repaired_chunks = 0
    if not dry_run:
        for item in inspection["items"]:
            if not item["mismatched_chunk_count"]:
                continue
            result = move_source_cluster_membership(
                conn,
                source_id=item["source_id"],
                target_cluster_id=item["cluster_id"],
                reason="Cluster membership repair synchronized source chunks.",
                actor=actor,
                expected_vault_id=vault_id,
                update_source_timestamp=False,
                prune_empty_cluster=False,
            )
            repaired_sources += 1
            repaired_chunks += result.chunks_updated
    return {
        **inspection,
        "dry_run": bool(dry_run),
        "sources_repaired": repaired_sources,
        "chunks_repaired": repaired_chunks,
    }
