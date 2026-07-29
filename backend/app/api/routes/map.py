from __future__ import annotations

from itertools import combinations
import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from backend.app.core.database import connect, dict_from_row

router = APIRouter(prefix="/map", tags=["map"])
UNCLUSTERED_PREFIX = "unclustered:"
MapConnectionMode = Literal["current", "similar"]
MIN_CLUSTER_SIMILARITY = 0.72
MAX_SIMILAR_NEIGHBORS = 3
MAX_SIMILARITY_EDGES = 240


def _cluster_node(row, source_count: int, fact_count: int) -> dict:
    return {
        "id": row["id"],
        "kind": "cluster",
        "label": row["name"],
        "summary": row["cluster_summary"] or row["description"] or "",
        "color": row["color"],
        "state": row["profile_status"],
        "source_count": source_count,
        "fact_count": fact_count,
        "updated_at": row["updated_at"],
    }


def _unclustered_id(vault_id: str) -> str:
    return f"{UNCLUSTERED_PREFIX}{vault_id}"


def _unclustered_node(vault_id: str, source_count: int, updated_at: str) -> dict:
    return {
        "id": _unclustered_id(vault_id),
        "kind": "collection",
        "label": "Unclustered sources",
        "summary": "Sources that have not been organized into a cluster yet.",
        "color": "muted",
        "state": "needs_organization",
        "source_count": source_count,
        "fact_count": 0,
        "updated_at": updated_at,
    }


@router.get("/overview")
def map_overview(
    vault_id: str,
    limit: int = Query(default=120, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    connections: MapConnectionMode = "current",
) -> dict:
    """Return the current graph, optionally augmented with bounded semantic links."""
    with connect() as conn:
        vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone()
        if vault is None:
            raise HTTPException(status_code=404, detail="Vault not found")
        rows = conn.execute(
            """
            SELECT
                c.*,
                COUNT(DISTINCT s.id) AS source_count,
                COUNT(DISTINCT tf.id) AS fact_count
            FROM clusters c
            LEFT JOIN sources s
              ON s.cluster_id = c.id AND s.deleted_at IS NULL
            LEFT JOIN temporal_facts tf
              ON tf.cluster_id = c.id AND tf.status = 'current'
            WHERE c.vault_id = ?
            GROUP BY c.id
            ORDER BY c.updated_at DESC, c.id DESC
            LIMIT ? OFFSET ?
            """,
            (vault_id, limit, offset),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) AS total FROM clusters WHERE vault_id = ?",
            (vault_id,),
        ).fetchone()["total"]
        unclustered = conn.execute(
            """
            SELECT COUNT(*) AS total, COALESCE(MAX(updated_at), '') AS updated_at
            FROM sources
            WHERE vault_id = ? AND cluster_id IS NULL AND deleted_at IS NULL
            """,
            (vault_id,),
        ).fetchone()
        nodes = [
            _cluster_node(row, int(row["source_count"] or 0), int(row["fact_count"] or 0))
            for row in rows
        ]
        if int(unclustered["total"] or 0) > 0:
            nodes.append(
                _unclustered_node(
                    vault_id,
                    int(unclustered["total"]),
                    unclustered["updated_at"] or max((row["updated_at"] for row in rows), default=""),
                )
            )
        visible_cluster_ids = {
            node["id"]
            for node in nodes
            if node["kind"] == "cluster"
        }
        edges = _overview_cluster_edges(conn, vault_id, visible_cluster_ids)
        if connections == "similar":
            authoritative_pairs = {
                tuple(sorted((str(edge["source"]), str(edge["target"]))))
                for edge in edges
            }
            edges.extend(
                _semantic_cluster_edges(
                    conn,
                    vault_id,
                    visible_cluster_ids,
                    excluded_pairs=authoritative_pairs,
                )
            )
        node_total = int(total) + (1 if int(unclustered["total"] or 0) > 0 else 0)
    return {
        "vault_id": vault_id,
        "nodes": nodes,
        "edges": edges,
        "total": node_total,
        "cluster_total": int(total),
        "unclustered_count": int(unclustered["total"] or 0),
        "limit": limit,
        "offset": offset,
        "truncated": offset + len(rows) < int(total),
        "connection_mode": connections,
        "relationship_policy": (
            "evidence_and_similarity"
            if connections == "similar"
            else "authoritative_only"
        ),
    }


@router.get("/neighborhood")
def map_neighborhood(
    vault_id: str,
    root_id: str,
    limit: int = Query(default=80, ge=5, le=200),
) -> dict:
    """Expand one provenance-backed hop from a cluster or source."""
    with connect() as conn:
        is_unclustered = root_id == _unclustered_id(vault_id)
        cluster = conn.execute(
            "SELECT * FROM clusters WHERE id = ? AND vault_id = ?",
            (root_id, vault_id),
        ).fetchone() if not is_unclustered else None
        source = None if cluster or is_unclustered else conn.execute(
            "SELECT * FROM sources WHERE id = ? AND vault_id = ? AND deleted_at IS NULL",
            (root_id, vault_id),
        ).fetchone()
        if cluster is None and source is None and not is_unclustered:
            raise HTTPException(status_code=404, detail="Map item not found")

        nodes: list[dict] = []
        edges: list[dict] = []
        truncated = False
        if is_unclustered:
            source_rows = conn.execute(
                """
                SELECT *
                FROM sources
                WHERE vault_id = ? AND cluster_id IS NULL AND deleted_at IS NULL
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (vault_id, limit),
            ).fetchall()
            total_sources = conn.execute(
                "SELECT COUNT(*) AS total FROM sources WHERE vault_id = ? AND cluster_id IS NULL AND deleted_at IS NULL",
                (vault_id,),
            ).fetchone()["total"]
            updated_at = max((row["updated_at"] for row in source_rows), default="")
            nodes.append(_unclustered_node(vault_id, int(total_sources), updated_at))
            for row in source_rows:
                nodes.append(_source_node(row))
                edges.append(_edge(root_id, row["id"], "contains", [row["id"]], row["updated_at"]))
            truncated = int(total_sources) > len(source_rows)
        elif cluster is not None:
            source_rows = conn.execute(
                """
                SELECT *
                FROM sources
                WHERE vault_id = ? AND cluster_id = ? AND deleted_at IS NULL
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (vault_id, root_id, limit),
            ).fetchall()
            total_sources = conn.execute(
                "SELECT COUNT(*) AS total FROM sources WHERE vault_id = ? AND cluster_id = ? AND deleted_at IS NULL",
                (vault_id, root_id),
            ).fetchone()["total"]
            fact_total = conn.execute(
                "SELECT COUNT(*) AS total FROM temporal_facts WHERE vault_id = ? AND cluster_id = ? AND status = 'current'",
                (vault_id, root_id),
            ).fetchone()["total"]
            nodes.append(_cluster_node(cluster, int(total_sources), int(fact_total)))
            for row in source_rows:
                nodes.append(_source_node(row))
                edges.append(_edge(cluster["id"], row["id"], "contains", [row["id"]], row["updated_at"]))
            truncated = int(total_sources) > len(source_rows)
        else:
            nodes.append(_source_node(source))
            if source["cluster_id"]:
                parent = conn.execute("SELECT * FROM clusters WHERE id = ?", (source["cluster_id"],)).fetchone()
                if parent:
                    parent_counts = conn.execute(
                        """
                        SELECT
                            (SELECT COUNT(*) FROM sources WHERE cluster_id = ? AND deleted_at IS NULL) AS source_count,
                            (SELECT COUNT(*) FROM temporal_facts WHERE cluster_id = ? AND status = 'current') AS fact_count
                        """,
                        (parent["id"], parent["id"]),
                    ).fetchone()
                    nodes.append(_cluster_node(parent, int(parent_counts["source_count"]), int(parent_counts["fact_count"])))
                    edges.append(_edge(parent["id"], source["id"], "contains", [source["id"]], source["updated_at"]))
            fact_rows = conn.execute(
                """
                SELECT *
                FROM temporal_facts
                WHERE vault_id = ? AND source_id = ?
                ORDER BY observed_at DESC, id DESC
                LIMIT ?
                """,
                (vault_id, root_id, max(0, limit - len(nodes))),
            ).fetchall()
            for row in fact_rows:
                nodes.append(_fact_node(row))
                edges.append(_edge(source["id"], row["id"], "establishes", [source["id"]], row["observed_at"]))

    return {
        "vault_id": vault_id,
        "root_id": root_id,
        "nodes": nodes,
        "edges": edges,
        "limit": limit,
        "truncated": truncated,
        "depth": 1,
        "relationship_policy": "authoritative_only",
    }


@router.get("/items/{item_id}")
def map_item(item_id: str, vault_id: str) -> dict:
    with connect() as conn:
        if item_id == _unclustered_id(vault_id):
            row = conn.execute(
                """
                SELECT COUNT(*) AS total, COALESCE(MAX(updated_at), '') AS updated_at
                FROM sources
                WHERE vault_id = ? AND cluster_id IS NULL AND deleted_at IS NULL
                """,
                (vault_id,),
            ).fetchone()
            return {
                **_unclustered_node(vault_id, int(row["total"] or 0), row["updated_at"]),
                "provenance": [],
            }
        cluster = conn.execute(
            "SELECT * FROM clusters WHERE id = ? AND vault_id = ?",
            (item_id, vault_id),
        ).fetchone()
        if cluster:
            sources = conn.execute(
                """
                SELECT id, title, source_type, state, updated_at
                FROM sources
                WHERE cluster_id = ? AND deleted_at IS NULL
                ORDER BY updated_at DESC LIMIT 8
                """,
                (item_id,),
            ).fetchall()
            counts = conn.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM sources WHERE cluster_id = ? AND deleted_at IS NULL) AS source_count,
                    (SELECT COUNT(*) FROM temporal_facts WHERE cluster_id = ? AND status = 'current') AS fact_count
                """,
                (item_id, item_id),
            ).fetchone()
            return {
                **_cluster_node(cluster, int(counts["source_count"]), int(counts["fact_count"])),
                "provenance": [dict_from_row(row) for row in sources],
            }
        source = conn.execute(
            "SELECT * FROM sources WHERE id = ? AND vault_id = ? AND deleted_at IS NULL",
            (item_id, vault_id),
        ).fetchone()
        if source:
            return {
                **_source_node(source),
                "path": source["original_path"],
                "url": source["url"],
                "provenance": [{"id": source["id"], "title": source["title"]}],
            }
        fact = conn.execute(
            "SELECT * FROM temporal_facts WHERE id = ? AND vault_id = ?",
            (item_id, vault_id),
        ).fetchone()
        if fact:
            origin = conn.execute(
                "SELECT id, title, source_type, updated_at FROM sources WHERE id = ?",
                (fact["source_id"],),
            ).fetchone()
            return {
                **_fact_node(fact),
                "citation_excerpt": fact["citation_excerpt"],
                "provenance": [dict_from_row(origin)] if origin else [],
            }
    raise HTTPException(status_code=404, detail="Map item not found")


def _source_node(row) -> dict:
    return {
        "id": row["id"],
        "kind": "source",
        "label": row["title"],
        "summary": row["summary"] or "",
        "source_type": row["source_type"],
        "state": row["state"],
        "cluster_id": row["cluster_id"],
        "updated_at": row["updated_at"],
    }


def _fact_node(row) -> dict:
    return {
        "id": row["id"],
        "kind": "fact",
        "label": f"{row['subject_key']} {row['predicate_key']} {row['object_text']}",
        "summary": row["citation_excerpt"] or "",
        "state": row["status"],
        "valid_from": row["valid_from"],
        "valid_until": row["valid_until"],
        "source_id": row["source_id"],
        "updated_at": row["observed_at"],
    }


def _edge(source: str, target: str, kind: str, provenance_ids: list[str], updated_at: str) -> dict:
    return {
        "id": f"{kind}:{source}:{target}",
        "source": source,
        "target": target,
        "kind": kind,
        "label": kind,
        "direction": "outbound",
        "temporal_state": "current",
        "provenance_ids": provenance_ids,
        "updated_at": updated_at,
    }


def _overview_cluster_edges(conn, vault_id: str, visible_cluster_ids: set[str]) -> list[dict]:
    """Build bounded cluster links from persisted, inspectable relationships only."""
    relationships: dict[tuple[str, str], dict] = {}

    entity_rows = conn.execute(
        """
        SELECT
            object_type,
            object_text,
            GROUP_CONCAT(DISTINCT cluster_id) AS cluster_ids,
            GROUP_CONCAT(DISTINCT source_id) AS provenance_ids,
            MAX(observed_at) AS updated_at
        FROM temporal_facts
        WHERE vault_id = ?
          AND status = 'current'
          AND cluster_id IS NOT NULL
          AND object_type != 'text'
          AND TRIM(object_text) != ''
        GROUP BY object_type, LOWER(TRIM(object_text))
        HAVING COUNT(DISTINCT cluster_id) > 1
        ORDER BY updated_at DESC
        LIMIT 160
        """,
        (vault_id,),
    ).fetchall()
    for row in entity_rows:
        cluster_ids = sorted(
            cluster_id
            for cluster_id in (row["cluster_ids"] or "").split(",")
            if cluster_id in visible_cluster_ids
        )
        if len(cluster_ids) < 2:
            continue
        label = f"Shared {str(row['object_type']).replace('_', ' ')}: {row['object_text']}"
        for source_id, target_id in combinations(cluster_ids, 2):
            if len(relationships) >= 240 and (source_id, target_id) not in relationships:
                break
            _merge_relationship(
                relationships,
                source_id,
                target_id,
                label,
                (row["provenance_ids"] or "").split(","),
                row["updated_at"],
            )

    project_rows = conn.execute(
        """
        WITH project_memberships AS (
            SELECT id AS project_id, primary_cluster_id AS cluster_id
            FROM projects
            WHERE vault_id = ? AND deleted_at IS NULL
            UNION
            SELECT links.project_id, links.cluster_id
            FROM project_cluster_links links
            JOIN projects ON projects.id = links.project_id
            WHERE projects.vault_id = ? AND projects.deleted_at IS NULL
        )
        SELECT
            p.id,
            p.name,
            p.updated_at,
            GROUP_CONCAT(DISTINCT memberships.cluster_id) AS cluster_ids
        FROM projects p
        JOIN project_memberships memberships ON memberships.project_id = p.id
        WHERE p.vault_id = ? AND p.deleted_at IS NULL
        GROUP BY p.id
        HAVING COUNT(DISTINCT memberships.cluster_id) > 1
        ORDER BY p.updated_at DESC
        LIMIT 80
        """,
        (vault_id, vault_id, vault_id),
    ).fetchall()
    for row in project_rows:
        cluster_ids = sorted(
            cluster_id
            for cluster_id in (row["cluster_ids"] or "").split(",")
            if cluster_id in visible_cluster_ids
        )
        for source_id, target_id in combinations(cluster_ids, 2):
            if len(relationships) >= 320 and (source_id, target_id) not in relationships:
                break
            _merge_relationship(
                relationships,
                source_id,
                target_id,
                f"Shared project: {row['name']}",
                [f"project:{row['id']}"],
                row["updated_at"],
            )

    edges: list[dict] = []
    for (source_id, target_id), relationship in list(relationships.items())[:320]:
        labels = relationship["labels"]
        edge = _edge(
            source_id,
            target_id,
            "related",
            relationship["provenance_ids"],
            relationship["updated_at"],
        )
        edge.update(
            {
                "label": labels[0] if len(labels) == 1 else f"{len(labels)} shared relationships",
                "direction": "undirected",
                "evidence_labels": labels,
            }
        )
        edges.append(edge)
    return edges


def _semantic_cluster_edges(
    conn,
    vault_id: str,
    visible_cluster_ids: set[str],
    *,
    excluded_pairs: set[tuple[str, str]],
) -> list[dict]:
    """Return a sparse nearest-neighbor graph from ready cluster profiles."""
    import numpy as np

    if len(visible_cluster_ids) < 2:
        return []
    ordered_ids = sorted(visible_cluster_ids)
    placeholders = ",".join("?" for _ in ordered_ids)
    rows = conn.execute(
        f"""
        SELECT
            cluster_id, centroid, lexical_terms, representative_source_ids,
            cohesion, updated_at
        FROM cluster_candidate_profiles
        WHERE vault_id = ?
          AND cluster_id IN ({placeholders})
          AND status = 'ready'
          AND TRIM(centroid) != ''
        ORDER BY cluster_id
        """,
        (vault_id, *ordered_ids),
    ).fetchall()
    profiles: list[dict] = []
    for row in rows:
        centroid = _json_float_list(row["centroid"])
        if not centroid:
            continue
        profiles.append(
            {
                "cluster_id": str(row["cluster_id"]),
                "centroid": centroid,
                "terms": _json_float_dict(row["lexical_terms"]),
                "representative_ids": _json_string_list(row["representative_source_ids"]),
                "cohesion": float(row["cohesion"] or 0),
                "updated_at": str(row["updated_at"] or ""),
            }
        )

    candidates: list[tuple[float, str, str, dict, dict]] = []
    by_dimensions: dict[int, list[dict]] = {}
    for profile in profiles:
        by_dimensions.setdefault(len(profile["centroid"]), []).append(profile)
    for dimension_profiles in by_dimensions.values():
        if len(dimension_profiles) < 2:
            continue
        matrix = np.asarray(
            [profile["centroid"] for profile in dimension_profiles],
            dtype=np.float32,
        )
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        valid = norms[:, 0] > 0
        matrix[valid] = matrix[valid] / norms[valid]
        scores = matrix @ matrix.T
        for first_index, second_index in combinations(range(len(dimension_profiles)), 2):
            first = dimension_profiles[first_index]
            second = dimension_profiles[second_index]
            pair = tuple(sorted((first["cluster_id"], second["cluster_id"])))
            if pair in excluded_pairs:
                continue
            score = float(scores[first_index, second_index])
            if score < MIN_CLUSTER_SIMILARITY:
                continue
            candidates.append((score, pair[0], pair[1], first, second))

    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    degrees: dict[str, int] = {}
    edges: list[dict] = []
    for score, source_id, target_id, first, second in candidates:
        if len(edges) >= MAX_SIMILARITY_EDGES:
            break
        if (
            degrees.get(source_id, 0) >= MAX_SIMILAR_NEIGHBORS
            or degrees.get(target_id, 0) >= MAX_SIMILAR_NEIGHBORS
        ):
            continue
        shared_terms = sorted(
            set(first["terms"]).intersection(second["terms"]),
            key=lambda term: (
                -min(first["terms"][term], second["terms"][term]),
                term,
            ),
        )[:4]
        similarity = round(max(0.0, min(1.0, score)), 3)
        edge = _edge(
            source_id,
            target_id,
            "similarity",
            list(
                dict.fromkeys(
                    [
                        *first["representative_ids"],
                        *second["representative_ids"],
                    ]
                )
            )[:10],
            max(first["updated_at"], second["updated_at"]),
        )
        edge.update(
            {
                "label": f"{round(similarity * 100)}% similar",
                "direction": "undirected",
                "relationship_basis": "semantic_similarity",
                "similarity_score": similarity,
                "shared_terms": shared_terms,
                "evidence_labels": (
                    [f"Shared topics: {', '.join(shared_terms)}"]
                    if shared_terms
                    else []
                ),
            }
        )
        edges.append(edge)
        degrees[source_id] = degrees.get(source_id, 0) + 1
        degrees[target_id] = degrees.get(target_id, 0) + 1
    return edges


def _json_float_list(raw: str) -> list[float]:
    try:
        value = json.loads(raw or "[]")
        return [float(item) for item in value] if isinstance(value, list) else []
    except (json.JSONDecodeError, TypeError, ValueError):
        return []


def _json_float_dict(raw: str) -> dict[str, float]:
    try:
        value = json.loads(raw or "{}")
        if not isinstance(value, dict):
            return {}
        return {
            str(key): float(weight)
            for key, weight in value.items()
        }
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def _json_string_list(raw: str) -> list[str]:
    try:
        value = json.loads(raw or "[]")
        return [str(item) for item in value if str(item)] if isinstance(value, list) else []
    except (json.JSONDecodeError, TypeError, ValueError):
        return []


def _merge_relationship(
    relationships: dict[tuple[str, str], dict],
    source_id: str,
    target_id: str,
    label: str,
    provenance_ids: list[str],
    updated_at: str,
) -> None:
    key = tuple(sorted((source_id, target_id)))
    current = relationships.setdefault(
        key,
        {"labels": [], "provenance_ids": [], "updated_at": updated_at},
    )
    if label not in current["labels"]:
        current["labels"].append(label)
    for provenance_id in provenance_ids:
        if provenance_id and provenance_id not in current["provenance_ids"]:
            current["provenance_ids"].append(provenance_id)
    if updated_at > current["updated_at"]:
        current["updated_at"] = updated_at
