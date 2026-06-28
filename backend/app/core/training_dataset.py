import json
import re
from collections import Counter
from pathlib import Path

from backend.app.core.database import connect, dict_from_row
from backend.app.core.embeddings import content_hash
from backend.app.core.encrypted_storage import source_from_encrypted_row
from backend.app.core.expert_contract import EXPERT_OBJECTIVE_VERSION

TRAINABLE_TEXT_EXTENSIONS = (".md", ".txt", ".rst", ".adoc", ".html", ".htm")
TRAINING_RECORD_TYPES = (
    "source_fact_extract",
    "evidence_compression",
    "citation_boundary",
    "terminology_normalization",
    "style_rewrite",
    "reasoning_hint",
    "conflict_summary",
    "uncertainty_boundary",
)

LEGACY_CATEGORY_BY_RECORD_TYPE = {
    "source_fact_extract": "factual_recall",
    "evidence_compression": "summarization",
    "citation_boundary": "citation_grounding",
    "terminology_normalization": "terminology_consistency",
    "style_rewrite": "style_transfer",
    "reasoning_hint": "reasoning_pattern",
    "conflict_summary": "contradiction_handling",
    "uncertainty_boundary": "out_of_scope_refusal",
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
    behavior_profile = _dataset_behavior_profile(documents)

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
        "behavior_profile": behavior_profile,
        "documents": documents,
    }


def build_path_text_dataset(
    *,
    dataset_id: str,
    dataset_name: str,
    source_paths: list[str | Path],
    minimum_chars: int = 400,
) -> dict:
    documents = []
    seen_hashes: set[str] = set()
    total_text_chars = 0

    for source_path in source_paths:
        root = Path(source_path)
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else sorted(item for item in root.rglob("*") if item.is_file())
        for path in candidates:
            if path.suffix.lower() not in TRAINABLE_TEXT_EXTENSIONS:
                continue
            if path.name.lower() == "manifest.json":
                continue
            if _looks_like_translated_readme(path.name):
                continue
            text = _path_text_content(path)
            if not text:
                continue
            normalized = _normalized_trainable_text(text)
            if len(normalized) < minimum_chars:
                continue
            if normalized.count("```") > 40:
                continue
            alpha_count = sum(char.isalpha() for char in normalized)
            if alpha_count < 200:
                continue
            doc_hash = content_hash(normalized)
            if doc_hash in seen_hashes:
                continue
            seen_hashes.add(doc_hash)
            total_text_chars += len(normalized)
            documents.append(
                {
                    "source_id": content_hash(str(path.resolve(strict=False))),
                    "title": path.name,
                    "summary": _truncate_words(normalized, 120),
                    "text": normalized,
                    "content_hash": doc_hash,
                    "original_path": str(path),
                }
            )

    documents = sorted(documents, key=lambda item: (str(item.get("title") or ""), str(item.get("source_id") or "")))
    duplicate_content_count = 0
    duplicate_content_ratio = 0.0
    dataset_hash = content_hash(
        "\n".join(
            f"{doc['source_id']}:{doc['content_hash']}"
            for doc in documents
        )
    )
    behavior_profile = _dataset_behavior_profile(documents)
    return {
        "cluster_id": dataset_id,
        "cluster_name": dataset_name,
        "source_count": len(documents),
        "unique_content_hash_count": len(documents),
        "duplicate_content_count": duplicate_content_count,
        "duplicate_content_ratio": duplicate_content_ratio,
        "total_text_chars": total_text_chars,
        "estimated_token_count": _estimate_tokens(total_text_chars),
        "dataset_hash": dataset_hash,
        "behavior_profile": behavior_profile,
        "documents": documents,
    }


def write_cluster_training_dataset(dataset: dict, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)

    documents = list(dataset.get("documents") or [])
    train_documents, validation_documents = _split_training_documents(
        documents,
        train_source_target=int(dataset.get("train_source_target") or 0) or None,
        validation_source_target=int(dataset.get("validation_source_target") or 0) or None,
    )
    train_dataset = {**dataset, "documents": train_documents}
    validation_dataset = {**dataset, "documents": validation_documents}

    if train_documents and validation_documents:
        train_records = _training_records(train_dataset)
        validation_records = _training_records(validation_dataset)
    else:
        records = _training_records(dataset)
        train_records, validation_records = _split_training_records(records)

    records = [*train_records, *validation_records]
    train_source_records = _source_records(train_documents)
    validation_source_records = _source_records(validation_documents)
    train_qa_records = _qa_records(train_dataset, train_documents)
    validation_qa_records = _qa_records(validation_dataset, validation_documents)

    train_path = output_dir / "train.jsonl"
    validation_path = output_dir / "validation.jsonl"
    train_sources_path = output_dir / "train-sources.jsonl"
    validation_sources_path = output_dir / "validation-sources.jsonl"
    train_corpus_path = output_dir / "train-corpus.txt"
    validation_corpus_path = output_dir / "validation-corpus.txt"
    train_qa_path = output_dir / "train-qa.jsonl"
    validation_qa_path = output_dir / "validation-qa.jsonl"
    manifest_path = output_dir / "dataset-manifest.json"

    _write_jsonl(train_path, train_records)
    _write_jsonl(validation_path, validation_records)
    _write_jsonl(train_sources_path, train_source_records)
    _write_jsonl(validation_sources_path, validation_source_records)
    _write_jsonl(train_qa_path, train_qa_records)
    _write_jsonl(validation_qa_path, validation_qa_records)
    train_corpus_path.write_text(_source_corpus_text(train_documents), encoding="utf-8")
    validation_corpus_path.write_text(_source_corpus_text(validation_documents), encoding="utf-8")
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
        "expert_objective_version": EXPERT_OBJECTIVE_VERSION,
        "requires_retrieved_evidence": True,
        "behavior_profile": dict(dataset.get("behavior_profile") or {}),
        "behavior_specialization_enabled": True,
        "benchmark_record_accounting": record_accounting,
        "train_source_count": len(train_documents),
        "validation_source_count": len(validation_documents),
    }

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return {
        "dataset_dir": str(output_dir),
        "train_path": str(train_path),
        "validation_path": str(validation_path),
        "train_sources_path": str(train_sources_path),
        "validation_sources_path": str(validation_sources_path),
        "train_corpus_path": str(train_corpus_path),
        "validation_corpus_path": str(validation_corpus_path),
        "train_qa_path": str(train_qa_path),
        "validation_qa_path": str(validation_qa_path),
        "manifest_path": str(manifest_path),
        **manifest,
    }


def _split_training_documents(
    documents: list[dict],
    *,
    train_source_target: int | None = None,
    validation_source_target: int | None = None,
) -> tuple[list[dict], list[dict]]:
    ordered = sorted(
        (dict(doc) for doc in documents),
        key=lambda item: (
            str(item.get("source_id") or ""),
            str(item.get("content_hash") or ""),
            str(item.get("title") or ""),
        ),
    )
    if len(ordered) <= 1:
        return ordered, []
    if train_source_target is not None or validation_source_target is not None:
        normalized_train = max(0, int(train_source_target or 0))
        normalized_validation = max(0, int(validation_source_target or 0))
        required = normalized_train + normalized_validation
        if normalized_train <= 0 or normalized_validation <= 0:
            raise ValueError("Explicit source split targets must both be positive.")
        if len(ordered) < required:
            raise ValueError(
                f"Dataset contains {len(ordered)} sources but requires {required} for the requested train/validation split."
            )
        return ordered[:normalized_train], ordered[normalized_train : normalized_train + normalized_validation]
    split_at = max(1, int(len(ordered) * 0.8))
    if split_at >= len(ordered):
        split_at = len(ordered) - 1
    return ordered[:split_at], ordered[split_at:]


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
        "behavior_profile": dict(dataset.get("behavior_profile") or {}),
    }
    records = [
        _build_record(
            record_type="source_fact_extract",
            category=LEGACY_CATEGORY_BY_RECORD_TYPE["source_fact_extract"],
            user_prompt=(
                f"Extract the key facts from retrieved evidence for '{title}' without adding outside facts.\n\n"
                f"Evidence:\n{evidence_block}"
            ),
            assistant_target=(
                f"According to source {title}, {snippets[0]} "
                "Use only retrieved source evidence for factual claims."
            ),
            metadata=shared_metadata,
        ),
        _build_record(
            record_type="evidence_compression",
            category=LEGACY_CATEGORY_BY_RECORD_TYPE["evidence_compression"],
            user_prompt=(
                f"Compress the retrieved evidence for '{title}' into three grounded bullets.\n\n"
                f"Evidence:\n{evidence_block}"
            ),
            assistant_target=_grounded_digest(title, snippets),
            metadata=shared_metadata,
        ),
        _build_record(
            record_type="citation_boundary",
            category=LEGACY_CATEGORY_BY_RECORD_TYPE["citation_boundary"],
            user_prompt=(
                f"Answer using only retrieved evidence for '{title}' and cite the source title.\n\n"
                f"Evidence:\n{evidence_block}"
            ),
            assistant_target=(
                f"According to source {title}, {snippets[0]} "
                f"Source: {title}."
            ),
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
                f"Use consistent cluster vocabulary such as {', '.join(local_terms) if local_terms else 'local cluster vocabulary'}. "
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
                f"Start small, keep it concrete: {_practical_note_excerpt(summary, text)} "
                f"Ground the answer in the evidence and keep it concrete: {snippets[0]}"
                f"{_behavior_contract_suffix(shared_metadata['behavior_profile'])}"
            ),
            metadata=shared_metadata,
        ),
        _build_record(
            record_type="reasoning_hint",
            category=LEGACY_CATEGORY_BY_RECORD_TYPE["reasoning_hint"],
            user_prompt=(
                f"Give a short reasoning pattern for '{title}' supported by the retrieved evidence.\n\n"
                f"Evidence:\n{evidence_block}"
            ),
            assistant_target=(
                f"The source evidence is: {snippets[0]} "
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
                f"State what is not covered by partial evidence for '{title}'.\n\n"
                f"Evidence:\n{evidence_block}"
            ),
            assistant_target=(
                f"The available evidence supports: {snippets[0]} "
                "Anything beyond those retrieved details is missing evidence and should be marked uncertain."
            ),
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
        "behavior_profile": dict(metadata.get("behavior_profile") or {}),
    }


def _source_records(documents: list[dict]) -> list[dict]:
    rows = []
    for doc in documents:
        text = str(doc.get("text") or "").strip()
        rows.append(
            {
                "source_id": str(doc.get("source_id") or ""),
                "title": str(doc.get("title") or "Untitled"),
                "summary": str(doc.get("summary") or "").strip(),
                "text": text,
                "content_hash": str(doc.get("content_hash") or ""),
                "text_char_count": len(text),
                "text_token_estimate": _estimate_text_tokens(text),
            }
        )
    return rows


def _source_corpus_text(documents: list[dict]) -> str:
    blocks = []
    for doc in documents:
        text = str(doc.get("text") or "").strip()
        if not text:
            continue
        blocks.append(
            "\n".join(
                [
                    f"### SOURCE_ID: {str(doc.get('source_id') or '').strip()}",
                    f"### TITLE: {str(doc.get('title') or 'Untitled').strip()}",
                    text,
                ]
            ).strip()
        )
    if not blocks:
        return ""
    return "\n\n".join(blocks).strip() + "\n"


def _qa_records(dataset: dict, documents: list[dict]) -> list[dict]:
    rows = []
    for doc in documents:
        rows.extend(_qa_records_for_document(dataset, doc))
    return rows


def _qa_records_for_document(dataset: dict, doc: dict) -> list[dict]:
    title = str(doc.get("title") or "Untitled")
    summary = str(doc.get("summary") or "").strip()
    text = str(doc.get("text") or "")
    snippets = _evidence_snippets(text or summary, max_items=5)
    if not snippets:
        snippets = ["The local source contains cluster-specific evidence."]
    local_terms = _preferred_terms(title, summary, text)
    shared_metadata = {
        "source_id": str(doc.get("source_id") or ""),
        "content_hash": str(doc.get("content_hash") or ""),
        "source_ids": [str(doc.get("source_id") or "")],
        "content_hashes": [str(doc.get("content_hash") or "")],
        "evidence_handles": [f"source:{doc['source_id']}#snippet-{index + 1}" for index in range(len(snippets))],
        "grounding_required": True,
        "behavior_profile": dict(dataset.get("behavior_profile") or {}),
    }
    return [
        _build_qa_record(
            record_type="evidence_compression",
            prompt=(
                f"Compress the retrieved evidence for '{title}' into a short grounded digest.\n\n"
                f"Evidence:\n" + "\n".join(f"[{index + 1}] {snippet}" for index, snippet in enumerate(snippets))
            ),
            answer=_grounded_digest(title, snippets),
            metadata=shared_metadata,
        ),
        _build_qa_record(
            record_type="style_rewrite",
            prompt=(
                f"Rewrite a neutral answer for '{title}' in the cluster's local style without adding facts.\n\n"
                f"Neutral answer: {snippets[0]}"
            ),
            answer=(
                f"{_practical_note_excerpt(summary, text)} "
                f"Ground the answer in the evidence and keep it concrete: {snippets[0]} "
                f"{_behavior_contract_suffix(shared_metadata['behavior_profile'])}"
            ),
            metadata=shared_metadata,
        ),
        _build_qa_record(
            record_type="reasoning_hint",
            prompt=(
                f"Give a short reasoning hint for '{title}' supported by the retrieved evidence."
            ),
            answer=(
                f"Evidence first: {snippets[0]} "
                f"Interpretation: this supports a local pattern around {', '.join(local_terms[:2]) if local_terms else 'the cluster context'}. "
                "Conclusion: keep the next answer aligned with that pattern."
            ),
            metadata=shared_metadata,
        ),
    ]


def _build_qa_record(*, record_type: str, prompt: str, answer: str, metadata: dict) -> dict:
    return {
        "record_type": record_type,
        "source_id": metadata["source_id"],
        "content_hash": metadata["content_hash"],
        "prompt": prompt,
        "answer": answer,
        "input_token_estimate": _estimate_text_tokens(prompt),
        "target_token_estimate": _estimate_text_tokens(answer),
        "grounding_required": bool(metadata["grounding_required"]),
        "evidence_handles": list(metadata["evidence_handles"]),
        "behavior_profile": dict(metadata.get("behavior_profile") or {}),
    }


def _grounded_digest(title: str, snippets: list[str]) -> str:
    lines = [
        f"- {snippets[0]}",
    ]
    if len(snippets) > 1:
        lines.append(f"- Supporting detail: {snippets[1]}")
    lines.append(f"- Source: {title}.")
    return "\n".join(lines)


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


def _normalized_trainable_text(text: str) -> str:
    cleaned = str(text or "").replace("\ufeff", " ")
    cleaned = re.sub(r"\r\n?", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    return cleaned.strip()


def _path_text_content(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _looks_like_translated_readme(name: str) -> bool:
    return bool(re.match(r"readme-[a-z]{2,3}(?:-[a-z]{2})?\.md$", str(name or "").lower()))


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


def _dataset_behavior_profile(documents: list[dict]) -> dict:
    terms: list[str] = []
    for doc in documents[:8]:
        for term in _preferred_terms(
            str(doc.get("title") or ""),
            str(doc.get("summary") or ""),
            str(doc.get("text") or ""),
        ):
            if term not in terms:
                terms.append(term)
            if len(terms) >= 6:
                break
        if len(terms) >= 6:
            break
    return {
        "voice": "cluster-local-expert",
        "terminology_shift": terms[:4],
        "style_markers": ["grounded", "concrete", "practical"],
        "reasoning_order": ["evidence", "interpretation", "conclusion"],
        "framing_rules": [
            "keep claims tied to supplied evidence",
            "prefer practical takeaways",
        ],
        "refusal_style": "state missing evidence explicitly",
        "practicality_bias": "practical",
    }


def _behavior_contract_suffix(profile: dict) -> str:
    style_markers = ", ".join(str(item) for item in profile.get("style_markers") or [] if str(item).strip())
    reasoning_order = " -> ".join(str(item) for item in profile.get("reasoning_order") or [] if str(item).strip())
    if not style_markers and not reasoning_order:
        return ""
    parts = []
    if style_markers:
        parts.append(f"Style markers: {style_markers}.")
    if reasoning_order:
        parts.append(f"Reasoning order: {reasoning_order}.")
    return " ".join(parts)


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
