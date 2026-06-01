from backend.app.core.database import connect, dict_from_row


def build_cluster_dataset(cluster_id: str) -> dict:
    with connect() as conn:
        cluster_row = conn.execute(
            """
            SELECT *
            FROM clusters
            WHERE id = ?
            """,
            (cluster_id,),
        ).fetchone()

        if cluster_row is None:
            raise ValueError(f"Cluster not found: {cluster_id}")

        cluster = dict_from_row(cluster_row)

        source_rows = conn.execute(
            """
            SELECT *
            FROM sources
            WHERE cluster_id = ?
            ORDER BY updated_at DESC
            """,
            (cluster_id,),
        ).fetchall()

    documents = []

    for row in source_rows:
        source = dict_from_row(row)

        documents.append(
            {
                "source_id": source["id"],
                "title": source["title"],
                "summary": source.get("summary") or "",
                "text": source.get("extracted_text") or "",
            }
        )

    return {
        "cluster_id": cluster["id"],
        "cluster_name": cluster["name"],
        "source_count": len(documents),
        "documents": documents,
    }