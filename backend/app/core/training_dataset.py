import json
from pathlib import Path

from backend.app.core.database import connect, dict_from_row
from backend.app.core.embeddings import content_hash


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

        text = source.get("extracted_text") or ""
        if not text.strip() or source.get("deleted_at"):
            continue
        documents.append(
            {
                "source_id": source["id"],
                "title": source["title"],
                "summary": source.get("summary") or "",
                "text": text,
                "content_hash": content_hash(text),
            }
        )

    dataset_hash = content_hash(
        "\n".join(f"{doc['source_id']}:{doc['content_hash']}" for doc in sorted(documents, key=lambda item: item["source_id"]))
    )
    return {
        "cluster_id": cluster["id"],
        "cluster_name": cluster["name"],
        "source_count": len(documents),
        "dataset_hash": dataset_hash,
        "documents": documents,
    }


def write_cluster_training_dataset(dataset: dict, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    records = _training_records(dataset)
    split_at = max(1, int(len(records) * 0.8)) if len(records) > 1 else len(records)
    train_records = records[:split_at]
    validation_records = records[split_at:] or records[-1:]
    train_path = output_dir / "train.jsonl"
    validation_path = output_dir / "validation.jsonl"
    manifest_path = output_dir / "dataset-manifest.json"
    _write_jsonl(train_path, train_records)
    _write_jsonl(validation_path, validation_records)
    manifest = {
        "cluster_id": dataset["cluster_id"],
        "cluster_name": dataset["cluster_name"],
        "source_count": dataset["source_count"],
        "dataset_hash": dataset["dataset_hash"],
        "train_count": len(train_records),
        "validation_count": len(validation_records),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {
        "dataset_dir": str(output_dir),
        "train_path": str(train_path),
        "validation_path": str(validation_path),
        "manifest_path": str(manifest_path),
        **manifest,
    }


def _training_records(dataset: dict) -> list[dict]:
    records = []
    seen_hashes = set()
    for doc in dataset.get("documents", []):
        doc_hash = doc.get("content_hash")
        if doc_hash in seen_hashes:
            continue
        seen_hashes.add(doc_hash)
        records.append(
            {
                "instruction": f"Summarize the local context source titled {doc['title']}.",
                "input": doc["text"][:6000],
                "output": doc.get("summary") or f"This source belongs to {dataset['cluster_name']}.",
                "source_id": doc["source_id"],
                "content_hash": doc_hash,
            }
        )
    return records


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )
