import json
import re
from collections import Counter
from pathlib import Path

from backend.app.core.database import connect, dict_from_row
from backend.app.core.embeddings import content_hash
from backend.app.core.encrypted_storage import source_from_encrypted_row

TRAINING_RECORD_TYPES = (
    "evidence_compression",
    "terminology_normalization",
    "style_rewrite",
    "reasoning_hint",
    "conflict_summary",
    "uncertainty_boundary",
    "glossary_extract",
)

LEGACY_CATEGORY_BY_RECORD_TYPE = {
    "evidence_compression": "summarization",
    "terminology_normalization": "terminology_consistency",
    "style_rewrite": "style_transfer",
    "reasoning_hint": "reasoning_pattern",
    "conflict_summary": "contradiction_handling",
    "uncertainty_boundary": "out_of_scope_refusal",
    "glossary_extract": "terminology_consistency",
}


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
        title = str(source.get("title") or "").strip()
        if title.upper() == "MANIFEST.JSON":
            continue
        text = str(source.get("extracted_text") or source.get("raw_text") or "").strip()
        if not text or source.get("deleted_at") or _exclude_from_training(source):
            continue

        summary = str(source.get("summary") or "").strip()
        total_text_chars += len(text)
        documents.append(
            {
                "source_id": source["id"],
                "title": title or "Untitled",
                "summary": summary,
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
            for doc in sorted(documents, key=lambda item: item["source_id"])
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
    record_type_distribution = Counter(str(row.get("record_type") or "") for row in records if str(row.get("record_type") or "").strip())

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
        "record_type_distribution": dict(record_type_distribution),
        "training_record_types": list(TRAINING_RECORD_TYPES),
        "expert_objective_version": "retrieval_grounded_compression_v1",
        "requires_retrieved_evidence": True,
        "benchmark_record_accounting": record_accounting,
    }

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

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
        doc_hash = str(doc.get("content_hash") or "")
        if not doc_hash or doc_hash in seen_hashes:
            continue
        seen_hashes.add(doc_hash)
        records.extend(_records_for_document(dataset, doc))
    return records


def _records_for_document(dataset: dict, doc: dict) -> list[dict]:
    title = str(doc.get("title") or "Untitled")
    summary = (doc.get("summary") or "").strip()
    text = str(doc.get("text") or "")
    snippets = _evidence_snippets(text or summary, max_items=5)
    if not snippets:
        snippets = ["The local source contains cluster-specific evidence."]
    evidence_handles = [f"source:{doc['source_id']}#snippet-{index + 1}" for index in range(len(snippets))]
    local_terms = _preferred_terms(title, summary, text)
    evidence_block = "\n".join(
        f"[{index + 1}] {snippet}"
        for index, snippet in enumerate(snippets)
    )
    shared_metadata = {
        "source_id": doc["source_id"],
        "content_hash": doc["content_hash"],
        "source_ids": [doc["source_id"]],
        "content_hashes": [doc["content_hash"]],
        "evidence_handles": evidence_handles,
        "grounding_required": True,
    }
    records = [
        _build_record(
            record_type="evidence_compression",
            category=LEGACY_CATEGORY_BY_RECORD_TYPE["evidence_compression"],
            user_prompt=(
                f"Compress the retrieved evidence for '{title}' into a short grounded digest.\n\n"
                f"Evidence:\n{evidence_block}"
            ),
            assistant_target=_grounded_digest(title, snippets),
            metadata=shared_metadata,
        ),
        _build_record(
            record_type="terminology_normalization",
            category=LEGACY_CATEGORY_BY_RECORD_TYPE["terminology_normalization"],
            user_prompt=(
                f"Rewrite the evidence for '{title}' using the cluster's preferred terminology only.\n\n"
                f"Evidence:\n{evidence_block}\n\nGeneric phrasing: explain this in neutral wording."
            ),
            assistant_target=(
                f"Use cluster-preferred phrasing such as {', '.join(local_terms) if local_terms else 'local cluster vocabulary'}. "
                f"Keep the rewrite grounded in: {snippets[0]}"
            ),
            metadata=shared_metadata,
        ),
        _build_record(
            record_type="style_rewrite",
            category=LEGACY_CATEGORY_BY_RECORD_TYPE["style_rewrite"],
            user_prompt=(
                f"Rewrite a neutral answer for '{title}' in the cluster's local style without adding facts.\n\n"
                f"Evidence:\n{evidence_block}\n\nNeutral answer: {snippets[0]}"
            ),
            assistant_target=(
                f"{_practical_note_excerpt(summary, text)} "
                f"Ground the answer in the evidence and keep it concrete: {snippets[0]}"
            ),
            metadata=shared_metadata,
        ),
        _build_record(
            record_type="reasoning_hint",
            category=LEGACY_CATEGORY_BY_RECORD_TYPE["reasoning_hint"],
            user_prompt=(
                f"Give a short reasoning hint for '{title}' supported by the retrieved evidence.\n\n"
                f"Evidence:\n{evidence_block}"
            ),
            assistant_target=(
                f"Evidence first: {snippets[0]} "
                f"Interpretation: this supports a local pattern around {', '.join(local_terms[:2]) if local_terms else 'the cluster context'}. "
                "Conclusion: keep the next answer aligned with that pattern."
            ),
            metadata=shared_metadata,
        ),
        _build_record(
            record_type="conflict_summary",
            category=LEGACY_CATEGORY_BY_RECORD_TYPE["conflict_summary"],
            user_prompt=(
                f"Summarize the evidence for '{title}' while noting any uncertainty or internal tension.\n\n"
                f"Evidence:\n{evidence_block}"
            ),
            assistant_target=(
                f"Current evidence from {title} supports: {snippets[0]} "
                "If a later snippet conflicts, note the conflict neutrally and keep the source handle visible."
            ),
            metadata=shared_metadata,
        ),
        _build_record(
            record_type="uncertainty_boundary",
            category=LEGACY_CATEGORY_BY_RECORD_TYPE["uncertainty_boundary"],
            user_prompt=(
                f"State what can and cannot be said from partial evidence for '{title}'.\n\n"
                f"Evidence:\n{evidence_block}"
            ),
            assistant_target=(
                f"The available evidence supports: {snippets[0]} "
                "Anything beyond those retrieved details should be marked as missing or uncertain."
            ),
            metadata=shared_metadata,
        ),
        _build_record(
            record_type="glossary_extract",
            category=LEGACY_CATEGORY_BY_RECORD_TYPE["glossary_extract"],
            user_prompt=(
                f"Extract a small grounded glossary for '{title}' from the retrieved evidence.\n\n"
                f"Evidence:\n{evidence_block}"
            ),
            assistant_target=_glossary_target(local_terms, snippets),
            metadata=shared_metadata,
        ),
    ]
    return records


def _build_record(
    *,
    record_type: str,
    category: str,
    user_prompt: str,
    assistant_target: str,
    metadata: dict,
) -> dict:
    input_token_estimate = _estimate_text_tokens(user_prompt)
    target_token_estimate = _estimate_text_tokens(assistant_target)
    return {
        "messages": [
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": assistant_target},
        ],
        "record_type": record_type,
        "category": category,
        "source_id": metadata["source_id"],
        "content_hash": metadata["content_hash"],
        "source_ids": list(metadata["source_ids"]),
        "content_hashes": list(metadata["content_hashes"]),
        "evidence_handles": list(metadata["evidence_handles"]),
        "input_token_estimate": input_token_estimate,
        "target_token_estimate": target_token_estimate,
        "grounding_required": bool(metadata["grounding_required"]),
    }


def _grounded_digest(title: str, snippets: list[str]) -> str:
    lines = [
        f"Digest for {title}: {snippets[0]}",
    ]
    if len(snippets) > 1:
        lines.append(f"Supporting detail: {snippets[1]}")
    lines.append("Use only the retrieved evidence above for downstream synthesis.")
    return " ".join(lines)


def _glossary_target(local_terms: list[str], snippets: list[str]) -> str:
    if not local_terms:
        return f"Local terms remain grounded in the evidence: {snippets[0]}"
    parts = [f"{term}: grounded local term from the retrieved evidence." for term in local_terms[:3]]
    return " ".join(parts)


def _evidence_snippets(text: str, *, max_items: int) -> list[str]:
    candidate = _normalized_source_text(text)
    segments = _source_segments(candidate)
    return [_truncate_words(segment, 24).rstrip(".") + "." for segment in segments[:max_items]]


def _practical_note_excerpt(summary: str, text: str) -> str:
    candidate = _normalized_source_text(text or summary or "")
    segments = _source_segments(candidate)
    if not segments:
        return "The local source captures a cluster-specific practical detail."
    top_segments = [_truncate_words(segment, 18) for segment in segments[:3]]
    return "; ".join(segment.rstrip(".") for segment in top_segments).strip() + "."


def _normalized_source_text(text: str) -> str:
    cleaned = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    cleaned = cleaned.replace("`", " ")
    cleaned = re.sub(r"[{}\[\]]", " ", cleaned)
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


def _preferred_terms(title: str, summary: str, text: str) -> list[str]:
    seen = []
    for raw in f"{title} {summary} {text}".replace("_", " ").replace("-", " ").split():
        token = "".join(char for char in raw.lower() if char.isalnum())
        if len(token) < 5 or token in seen:
            continue
        seen.append(token)
        if len(seen) >= 4:
            break
    return seen


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def _estimate_tokens(text_chars: int) -> int:
    return max(0, text_chars // 4)


def _estimate_text_tokens(text: str) -> int:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return 0
    return max(1, (len(cleaned) + 3) // 4)


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
    record_type_counts = Counter(str(row.get("record_type") or "") for row in rows if str(row.get("record_type") or "").strip())
    category_counts = Counter(str(row.get("category") or "") for row in rows if str(row.get("category") or "").strip())
    content_hashes = [str(row.get("content_hash") or "") for row in rows if str(row.get("content_hash") or "").strip()]
    unique_hashes = set(content_hashes)
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
    per_record_type_source_counts: dict[str, Counter] = {}
    max_share_per_source_per_record_type: dict[str, float] = {}
    for record_type in record_type_counts:
        counter = Counter(
            str(row.get("source_id") or "")
            for row in rows
            if str(row.get("record_type") or "") == record_type and str(row.get("source_id") or "").strip()
        )
        per_record_type_source_counts[record_type] = counter
        denominator = record_type_counts[record_type]
        max_share_per_source_per_record_type[record_type] = (
            max((count / denominator) for count in counter.values())
            if denominator > 0 and counter
            else 0.0
        )
    return {
        "record_count": total,
        "unique_source_count": len(source_counts),
        "unique_content_hash_count": len(unique_hashes),
        "duplicate_content_ratio": duplicate_source_content_ratio,
        "record_type_counts": dict(record_type_counts),
        "category_counts": dict(category_counts),
        "source_record_counts": dict(source_counts),
        "max_record_share_per_source": (max((count / total) for count in source_counts.values()) if total and source_counts else 0.0),
        "source_record_counts_per_record_type": {
            record_type: dict(counter)
            for record_type, counter in per_record_type_source_counts.items()
        },
        "max_record_share_per_source_per_record_type": max_share_per_source_per_record_type,
        # Keep the legacy key name so older reporting code still has a stable field to read.
        "max_record_share_per_source_per_category": dict(max_share_per_source_per_record_type),
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
