from collections import Counter
from itertools import combinations
import re
from uuid import uuid4

from backend.app.core.database import utc_now
from backend.app.core.cluster_profiles import shortlist_cluster_candidates, terms_for_text


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
    "about",
    "document",
    "documents",
    "file",
    "files",
    "page",
    "pages",
    "pdf",
    "chat",
    "transcript",
    "user",
    "attachment",
    "stored",
    "source",
    "sources",
    "includes",
    "include",
    "what",
}

CLUSTER_COLORS = ["sage", "sky", "blush", "sand", "lavender", "terracotta"]


def keywords_for_text(text: str, limit: int = 6) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z'-]{3,}", str(text or "").casefold().replace("_", " "))
    cleaned = [
        word.strip("-'")
        for word in words
        if word.strip("-'") not in STOPWORDS
        and not word.casefold().endswith(("html", "http"))
    ]
    return [word for word, _count in Counter(cleaned).most_common(limit)]


AUTO_PLACE_MIN_SCORE = 0.72
AUTO_PLACE_MIN_MARGIN = 0.20
AUTO_PLACE_MIN_COHESION = 0.55


def assign_or_create_cluster(conn, *, vault_id: str, title: str, text: str) -> str | None:
    ordered_keywords = keywords_for_text(f"{title} {text}", limit=10)
    standalone_clusters = conn.execute(
        """
        SELECT clusters.id
        FROM clusters
        WHERE clusters.vault_id = ?
          AND NOT EXISTS (
              SELECT 1 FROM project_cluster_links links
              WHERE links.cluster_id = clusters.id
          )
        LIMIT 2
        """,
        (vault_id,),
    ).fetchall()
    candidates = shortlist_cluster_candidates(
        conn,
        vault_id=vault_id,
        text=f"{title} {text}",
    )
    source_terms = set(terms_for_text(f"{title} {title} {text}", limit=16))
    scored: list[tuple[float, str]] = []
    for candidate in candidates:
        candidate_terms = candidate["terms"]
        overlap = sum(float(candidate_terms.get(term, 0)) for term in source_terms)
        lexical_score = min(1.0, overlap / max(2.0, len(source_terms) * 0.25))
        cohesion = float(candidate["cohesion"])
        cohesion_factor = cohesion if cohesion > 0 else 0.5
        score = (0.82 * lexical_score) + (0.18 * cohesion_factor)
        scored.append((score, str(candidate["cluster_id"])))
    scored.sort(reverse=True)
    if scored:
        best_score, best_cluster_id = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0.0
        best_profile = next(
            candidate for candidate in candidates if candidate["cluster_id"] == best_cluster_id
        )
        profile_cohesion = float(best_profile["cohesion"])
        cohesion_ok = profile_cohesion == 0 or profile_cohesion >= AUTO_PLACE_MIN_COHESION
        if (
            best_score >= AUTO_PLACE_MIN_SCORE
            and best_score - second_score >= AUTO_PLACE_MIN_MARGIN
            and cohesion_ok
        ):
            return best_cluster_id

    # Bootstrap only the first standalone cluster. Ambiguous later imports stay
    # unclustered until a persisted profile supports a clear placement.
    if standalone_clusters:
        return None

    return create_auto_cluster(
        conn,
        vault_id=vault_id,
        title=title,
        keywords=ordered_keywords,
    )


def create_auto_cluster(
    conn,
    *,
    vault_id: str,
    title: str,
    keywords: list[str] | set[str],
) -> str:
    ordered_keywords = list(keywords)
    name = cluster_name_from_keywords(ordered_keywords, title)
    now = utc_now()
    cluster_id = f"cluster-{uuid4()}"
    total = conn.execute(
        "SELECT COUNT(*) AS total FROM clusters WHERE vault_id = ?",
        (vault_id,),
    ).fetchone()
    color = CLUSTER_COLORS[int(total["total"] or 0) % len(CLUSTER_COLORS)]
    description = cluster_description_from_keywords(ordered_keywords)
    conn.execute(
        """
        INSERT INTO clusters (
            id, vault_id, name, name_origin, description, color, index_status, profile_status,
            cluster_summary, cluster_glossary, created_at, updated_at
        )
        VALUES (
            :id, :vault_id, :name, 'auto', :description, :color, 'empty', 'missing',
            '', '[]', :created_at, :updated_at
        )
        """,
        {
            "id": cluster_id,
            "vault_id": vault_id,
            "name": name,
            "description": description,
            "color": color,
            "created_at": now,
            "updated_at": now,
        },
    )
    return cluster_id


def group_related_unclustered_sources(
    sources: list[dict],
    *,
    minimum_group_size: int = 2,
    maximum_sources: int = 1000,
) -> list[list[dict]]:
    """Create stable lexical groups without forcing unrelated singletons together."""
    candidates = list(sources[: max(1, maximum_sources)])
    if len(candidates) < minimum_group_size:
        return []
    term_sets = [
        set(
            terms_for_text(
                " ".join(
                    str(source.get(field) or "")
                    for field in ("title", "summary", "tags")
                ),
                limit=18,
            )
        )
        for source in candidates
    ]
    parents = list(range(len(candidates)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root != second_root:
            parents[second_root] = first_root

    postings: dict[str, list[int]] = {}
    for index, terms in enumerate(term_sets):
        for term in terms:
            postings.setdefault(term, []).append(index)
    pair_overlap: Counter[tuple[int, int]] = Counter()
    maximum_posting = max(40, int(len(candidates) * 0.20))
    for indices in postings.values():
        if len(indices) > maximum_posting:
            continue
        pair_overlap.update(combinations(indices, 2))
    for (first, second), overlap in pair_overlap.items():
        if overlap < 2:
            continue
        containment = overlap / max(1, min(len(term_sets[first]), len(term_sets[second])))
        if overlap >= 3 or containment >= 0.40:
            union(first, second)

    grouped: dict[int, list[dict]] = {}
    for index, source in enumerate(candidates):
        grouped.setdefault(find(index), []).append(source)
    return [
        group
        for group in grouped.values()
        if len(group) >= max(2, minimum_group_size)
    ]


def cluster_name_from_keywords(keywords: list[str] | set[str], title: str) -> str:
    if keywords:
        leading = list(keywords)[:2]
        return " ".join(word.capitalize() for word in leading)
    stem = re.sub(r"[_+]+", " ", title.rsplit(".", 1)[0]).strip()
    return stem[:60] or "New Cluster"


def cluster_description_from_keywords(keywords: list[str]) -> str:
    if not keywords:
        return ""
    topics = ", ".join(keywords[:3])
    return f"Documents about {topics}."


def cluster_identity_from_sources(sources: list[dict]) -> tuple[str, str]:
    combined = " ".join(
        str(source.get(field) or "")
        for source in sources
        for field in ("title", "summary")
    )
    keywords = keywords_for_text(combined, limit=8)
    title = str(sources[0].get("title") or "New Cluster") if sources else "New Cluster"
    return cluster_name_from_keywords(keywords, title), cluster_description_from_keywords(keywords)
