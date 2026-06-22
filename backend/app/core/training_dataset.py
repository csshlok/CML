import json
from collections import Counter
from pathlib import Path

from backend.app.core.database import connect, dict_from_row
from backend.app.core.embeddings import content_hash
from backend.app.core.encrypted_storage import source_from_encrypted_row
from backend.app.core.expert_evaluation import EVALUATION_CATEGORIES, prompt_for_category


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

        source_rows = [
            source_from_encrypted_row(conn, row)
            for row in conn.execute(
            """
            SELECT *
            FROM sources
            WHERE cluster_id = ?
            ORDER BY updated_at DESC
            """,
            (cluster_id,),
            ).fetchall()
        ]

    documents = []
    total_text_chars = 0

    for source in source_rows:
        text = source.get("extracted_text") or ""
        if not text.strip() or source.get("deleted_at") or _exclude_from_training(source):
            continue

        total_text_chars += len(text)
        documents.append(
            {
                "source_id": source["id"],
                "title": source["title"],
                "summary": source.get("summary") or "",
                "text": text,
                "content_hash": content_hash(text),
            }
        )

    unique_hashes = {doc["content_hash"] for doc in documents}
    duplicate_content_count = max(0, len(documents) - len(unique_hashes))
    duplicate_content_ratio = duplicate_content_count / len(documents) if documents else 0.0

    dataset_hash = content_hash(
        "\n".join(
            f"{doc['source_id']}:{doc['content_hash']}"
            for doc in sorted(
                documents,
                key=lambda item: item["source_id"],
            )
        )
    )

    return {
        "cluster_id": cluster["id"],
        "cluster_name": cluster["name"],
        "source_count": len(documents),
        "unique_content_hash_count": len(unique_hashes),
        "duplicate_content_count": duplicate_content_count,
        "duplicate_content_ratio": round(duplicate_content_ratio, 4),
        "total_text_chars": total_text_chars,
        "estimated_token_count": _estimate_tokens(total_text_chars),
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
    record_accounting = _benchmark_record_accounting(
        train_records=train_records,
        validation_records=validation_records,
    )

    manifest = {
        "cluster_id": dataset["cluster_id"],
        "cluster_name": dataset["cluster_name"],
        "source_count": dataset["source_count"],
        "unique_content_hash_count": int(dataset.get("unique_content_hash_count") or 0),
        "duplicate_content_count": int(dataset.get("duplicate_content_count") or 0),
        "duplicate_content_ratio": float(dataset.get("duplicate_content_ratio") or 0.0),
        "total_text_chars": int(dataset.get("total_text_chars") or 0),
        "estimated_token_count": int(dataset.get("estimated_token_count") or 0),
        "dataset_hash": dataset["dataset_hash"],
        "train_count": len(train_records),
        "validation_count": len(validation_records),
        "benchmark_record_accounting": record_accounting,
    }

    manifest_path.write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )

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

        summary = (doc.get("summary") or "").strip()

        if len(summary) < 20:
            summary = (
                f"This document belongs to the cluster "
                f"'{dataset['cluster_name']}' and contains local knowledge."
            )

        for category in EVALUATION_CATEGORIES:
            records.append(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt_for_category(category, str(doc["title"])),
                        },
                        {
                            "role": "assistant",
                            "content": _category_answer(category, doc, summary),
                        },
                    ],
                    "source_id": doc["source_id"],
                    "content_hash": doc_hash,
                    "category": category,
                }
            )

    return records


def _category_answer(category: str, doc: dict, summary: str) -> str:
    title = str(doc.get("title") or "Untitled")
    evidence = _evidence_excerpt(summary, str(doc.get("text") or ""))
    source_prefix = f"According to source {title},"

    if category == "summarization":
        return (
            f"According to source {title}:\n"
            f"- {evidence}\n"
            f"- This answer is grounded in the local source titled {title}.\n"
            "- It should not rely on outside context beyond the local source."
        )
    if category == "citation_grounding":
        return f"{source_prefix} {evidence}"
    if category == "contradiction_handling":
        return (
            f"Trust the local evidence in source {title}. "
            f"If a new claim conflicts with it, treat the new claim as unverified unless it matches: {evidence}"
        )
    if category == "terminology_consistency":
        return (
            f"{source_prefix} use the preferred local terms: {_preferred_terms(title, summary, str(doc.get('text') or ''))}. "
            f"Keep the terminology consistent with the cluster notes. {evidence}"
        )
    if category == "reasoning_pattern":
        return (
            f"First, identify the local evidence from source {title}: {evidence} "
            "Then, interpret what it means for the cluster context. "
            "Therefore, the conclusion should follow the same reasoning pattern as the local notes."
        )
    if category == "style_transfer":
        return f"{source_prefix} the practical note is: {evidence}"
    if category == "out_of_scope_refusal":
        return (
            f"Source {title} does not provide enough evidence to answer an unrelated question. "
            "The missing evidence is explicit coverage in the local source, so the answer should say it is not covered."
        )
    return f"{source_prefix} key facts include: {evidence}"


def _evidence_excerpt(summary: str, text: str) -> str:
    candidate = (summary or text or "").strip()
    if not candidate:
        return "the local source contains project-specific evidence"
    words = candidate.replace("\r", " ").replace("\n", " ").split()
    excerpt = " ".join(words[:80]).strip()
    return excerpt.rstrip(".") + "."


def _preferred_terms(title: str, summary: str, text: str) -> str:
    seen = []
    for raw in f"{title} {summary} {text}".replace("_", " ").replace("-", " ").split():
        token = "".join(char for char in raw.lower() if char.isalnum())
        if len(token) < 5 or token in seen:
            continue
        seen.append(token)
        if len(seen) >= 3:
            break
    return ", ".join(seen) if seen else "local project vocabulary"


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def _estimate_tokens(text_chars: int) -> int:
    # Conservative language-agnostic estimate for graduation gates.
    return max(0, text_chars // 4)


def _benchmark_record_accounting(*, train_records: list[dict], validation_records: list[dict]) -> dict:
    combined_records = [*train_records, *validation_records]
    combined_source_ids = {str(row.get("source_id") or "") for row in combined_records if str(row.get("source_id") or "").strip()}
    combined_hashes = {str(row.get("content_hash") or "") for row in combined_records if str(row.get("content_hash") or "").strip()}
    return {
        "used_source_count": len(combined_source_ids),
        "used_unique_content_hash_count": len(combined_hashes),
        "train": _split_record_accounting(train_records),
        "validation": _split_record_accounting(validation_records),
    }


def _split_record_accounting(rows: list[dict]) -> dict:
    total = len(rows)
    source_counts = Counter(str(row.get("source_id") or "") for row in rows if str(row.get("source_id") or "").strip())
    category_counts = Counter(str(row.get("category") or "") for row in rows if str(row.get("category") or "").strip())
    content_hashes = [str(row.get("content_hash") or "") for row in rows if str(row.get("content_hash") or "").strip()]
    unique_hashes = set(content_hashes)
    # Benchmark exports intentionally fan one source out into multiple category-specific
    # records. Treat duplicate content at the source/hash level rather than the raw record
    # level so category fan-out does not look like corpus duplication.
    source_to_hash = {
        str(row.get("source_id") or ""): str(row.get("content_hash") or "")
        for row in rows
        if str(row.get("source_id") or "").strip() and str(row.get("content_hash") or "").strip()
    }
    unique_source_count = len(source_to_hash)
    duplicate_source_content_ratio = (
        max(0, unique_source_count - len(set(source_to_hash.values()))) / unique_source_count
        if unique_source_count
        else 0.0
    )
    per_category_source_counts: dict[str, Counter] = {}
    max_share_per_source_per_category: dict[str, float] = {}
    for category in category_counts:
        counter = Counter(
            str(row.get("source_id") or "")
            for row in rows
            if str(row.get("category") or "") == category and str(row.get("source_id") or "").strip()
        )
        per_category_source_counts[category] = counter
        denominator = category_counts[category]
        max_share_per_source_per_category[category] = (
            max((count / denominator) for count in counter.values())
            if denominator > 0 and counter
            else 0.0
        )
    return {
        "record_count": total,
        "unique_source_count": len(source_counts),
        "unique_content_hash_count": len(unique_hashes),
        "duplicate_content_ratio": duplicate_source_content_ratio,
        "category_counts": dict(category_counts),
        "source_record_counts": dict(source_counts),
        "max_record_share_per_source": (max((count / total) for count in source_counts.values()) if total and source_counts else 0.0),
        "source_record_counts_per_category": {
            category: dict(counter)
            for category, counter in per_category_source_counts.items()
        },
        "max_record_share_per_source_per_category": max_share_per_source_per_category,
    }


def _exclude_from_training(source: dict) -> bool:
    try:
        labels = json.loads(source.get("security_labels") or "[]")
    except json.JSONDecodeError:
        labels = []
    if not isinstance(labels, list):
        labels = []
    lowered = {str(label).lower() for label in labels}
    return (
        "lora_excluded" in lowered
        or "review_needed" in lowered
        or "ungrounded_external" in lowered
        or "partial_external" in lowered
    )
