from collections import Counter
from uuid import uuid4

from backend.app.core.database import utc_now


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
}

CLUSTER_COLORS = ["sage", "sky", "blush", "sand", "lavender", "terracotta"]


def keywords_for_text(text: str, limit: int = 6) -> list[str]:
    words = [
        word
        for word in text.lower().replace("_", " ").split()
        if len(word) > 3 and word.strip(".,:;!?()[]{}\"'") not in STOPWORDS
    ]
    cleaned = [word.strip(".,:;!?()[]{}\"'") for word in words]
    return [word for word, _count in Counter(cleaned).most_common(limit)]


def assign_or_create_cluster(conn, *, vault_id: str, title: str, text: str) -> str:
    ordered_keywords = keywords_for_text(f"{title} {text}", limit=10)
    source_keywords = set(ordered_keywords)
    rows = conn.execute(
        "SELECT * FROM clusters WHERE vault_id = ? ORDER BY updated_at DESC",
        (vault_id,),
    ).fetchall()

    best_cluster_id: str | None = None
    best_score = 0
    for row in rows:
        cluster_words = set(
            keywords_for_text(f"{row['name']} {row['description']}", limit=12)
        )
        score = len(source_keywords.intersection(cluster_words))
        if score > best_score:
            best_score = score
            best_cluster_id = row["id"]

    if best_cluster_id and best_score >= 2:
        return best_cluster_id

    name = cluster_name_from_keywords(ordered_keywords, title)
    now = utc_now()
    cluster_id = f"cluster-{uuid4()}"
    color = CLUSTER_COLORS[len(rows) % len(CLUSTER_COLORS)]
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


def cluster_name_from_keywords(keywords: list[str] | set[str], title: str) -> str:
    if keywords:
        leading = list(keywords)[:2]
        return " ".join(word.capitalize() for word in leading)
    stem = title.rsplit(".", 1)[0].strip()
    return stem[:60] or "New Cluster"


def cluster_description_from_keywords(keywords: list[str]) -> str:
    if not keywords:
        return ""
    return f"Sources about {', '.join(keywords[:4])}."


def cluster_identity_from_sources(sources: list[dict]) -> tuple[str, str]:
    combined = " ".join(
        str(source.get(field) or "")
        for source in sources
        for field in ("title", "summary")
    )
    keywords = keywords_for_text(combined, limit=8)
    title = str(sources[0].get("title") or "New Cluster") if sources else "New Cluster"
    return cluster_name_from_keywords(keywords, title), cluster_description_from_keywords(keywords)
