import json
import re
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
    train_records, validation_records = _split_training_records(records)

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


def _split_training_records(records: list[dict]) -> tuple[list[dict], list[dict]]:
    if len(records) <= 1:
        return records, records[-1:] if records else []
    grouped_records: dict[str, list[dict]] = {}
    ordered_source_ids: list[str] = []
    for row in records:
        source_id = str(row.get("source_id") or "")
        if source_id not in grouped_records:
            grouped_records[source_id] = []
            ordered_source_ids.append(source_id)
        grouped_records[source_id].append(row)
    groups = [grouped_records[source_id] for source_id in ordered_source_ids]
    if len(groups) == 1:
        only_group = groups[0]
        split_at = max(1, len(only_group) - 1)
        return only_group[:split_at], only_group[split_at:] or only_group[-1:]
    split_at = max(1, int(len(groups) * 0.8))
    if split_at >= len(groups):
        split_at = len(groups) - 1
    train_records = [row for group in groups[:split_at] for row in group]
    validation_records = [row for group in groups[split_at:] for row in group]
    return train_records, validation_records


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
        bullets = _grounded_summary_bullets(summary, str(doc.get("text") or ""), title)
        return (
            f"According to source {title}:\n"
            f"- {bullets[0]}\n"
            f"- {bullets[1]}\n"
            f"- {bullets[2]}"
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
        reasoning_evidence = _evidence_excerpt(summary, str(doc.get("text") or ""), max_words=28)
        return (
            f"First, identify the local evidence from source {title}: {reasoning_evidence} "
            "Then, interpret what it means for the cluster context in plain language. "
            "Therefore, the conclusion should stay practical and follow only what the local notes support."
        )
    if category == "style_transfer":
        practical_note = _practical_note_excerpt(summary, str(doc.get("text") or ""))
        return (
            f"{source_prefix} practical note: {practical_note} "
            "Keep the wording concrete, local, and action-oriented."
        )
    if category == "out_of_scope_refusal":
        return (
            f"Source {title} does not provide enough evidence to answer an unrelated question. "
            "The missing evidence is explicit coverage in the local source, so the answer should say it is not covered."
        )
    return f"{source_prefix} key facts include: {evidence}"


def _evidence_excerpt(summary: str, text: str, *, max_words: int = 80) -> str:
    candidate = _normalized_source_text(summary or text or "")
    if not candidate:
        return "the local source contains project-specific evidence"
    words = candidate.split()
    excerpt = " ".join(words[:max_words]).strip()
    return excerpt.rstrip(".") + "."


def _grounded_summary_bullets(summary: str, text: str, title: str) -> list[str]:
    candidate = _normalized_source_text(summary or text or "")
    segments = _source_segments(candidate)
    concise_segments = [_truncate_words(segment, 20) for segment in segments if segment]
    while len(concise_segments) < 2:
        concise_segments.append("Grounded takeaway: the source contains local project-specific evidence.")
    return [
        f"Grounded takeaway: {concise_segments[0].rstrip('.')}.",
        f"Key detail: {concise_segments[1].rstrip('.')}.",
        f"Grounding stays inside the local source titled {title}.",
    ]


def _practical_note_excerpt(summary: str, text: str) -> str:
    candidate = _normalized_source_text(summary or text or "")
    segments = _source_segments(candidate)
    if not segments:
        return "the local source captures a cluster-specific practical detail."
    top_segments = [_truncate_words(segment, 18) for segment in segments[:3]]
    return "; ".join(segment.rstrip(".") for segment in top_segments).strip() + "."


def _normalized_source_text(text: str) -> str:
    cleaned = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    cleaned = cleaned.replace("`", " ")
    cleaned = re.sub(r"[{}\\[\\]]", " ", cleaned)
    cleaned = re.sub(r"\|", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _source_segments(text: str) -> list[str]:
    if not text:
        return []
    raw_segments = re.split(r"(?<=[.!?])\s+|(?:\s+-\s+)|(?:\s+\d+\.\s+)", text)
    segments = []
    for raw in raw_segments:
        segment = raw.strip(" -")
        if len(segment) < 12:
            continue
        if segment not in segments:
            segments.append(segment)
    return segments[:6]


def _truncate_words(text: str, limit: int) -> str:
    words = text.split()
    if len(words) <= limit:
        return text.strip()
    return " ".join(words[:limit]).strip()


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
    train_source_ids = {str(row.get("source_id") or "") for row in train_records if str(row.get("source_id") or "").strip()}
    validation_source_ids = {str(row.get("source_id") or "") for row in validation_records if str(row.get("source_id") or "").strip()}
    train_hashes = {str(row.get("content_hash") or "") for row in train_records if str(row.get("content_hash") or "").strip()}
    validation_hashes = {str(row.get("content_hash") or "") for row in validation_records if str(row.get("content_hash") or "").strip()}
    return {
        "used_source_count": len(combined_source_ids),
        "used_unique_content_hash_count": len(combined_hashes),
        "train_validation_source_overlap_count": len(train_source_ids & validation_source_ids),
        "train_validation_content_hash_overlap_count": len(train_hashes & validation_hashes),
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
