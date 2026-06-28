import json
import os
import re
import hashlib
import time
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import requests

WIKIPEDIA_DATASET_ID = "wikimedia/wikipedia"
WIKIPEDIA_CONFIG = "20231101.en"
WIKIPEDIA_SPLIT = "train"
SQUAD_DATASET_ID = "rajpurkar/squad_v2"
SQUAD_CONFIG = "squad_v2"
SQUAD_TRAIN_SPLIT = "train"
SQUAD_VALIDATION_SPLIT = "validation"
TRAINING_RECORD_TYPES = (
    "evidence_compression",
    "terminology_normalization",
    "style_rewrite",
    "reasoning_hint",
    "conflict_summary",
    "uncertainty_boundary",
    "glossary_extract",
)
EXPERT_OBJECTIVE_VERSION = "retrieval_grounded_behavior_v1"
GENERIC_TERM_STOPWORDS = {
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "event",
    "events",
    "title",
    "source",
    "article",
    "wikipedia",
    "train",
    "validation",
    "corpus",
}


def normalize_external_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def wikipedia_row_to_document(
    row: dict,
    *,
    config: str,
    split: str,
    minimum_chars: int = 1500,
    maximum_chars: int = 20000,
) -> dict | None:
    title = str(row.get("title") or "").strip()
    text = normalize_external_text(str(row.get("text") or ""))
    row_id = str(row.get("id") or "").strip()
    if not row_id or not title or not text:
        return None
    if len(text) < minimum_chars:
        return None
    if maximum_chars > 0 and len(text) > maximum_chars:
        text = text[:maximum_chars].strip()
    lowered_title = title.lower()
    lowered_text = text.lower()
    if "(disambiguation)" in lowered_title:
        return None
    if lowered_title.startswith("list of "):
        return None
    if lowered_text.startswith(("may refer to:", "may also refer to:", "most commonly refers to:")):
        return None
    alpha_count = sum(char.isalpha() for char in text)
    if alpha_count < 800:
        return None
    if text.count("\n*") > 80 or text.count("\n#") > 80:
        return None
    normalized_hash = stable_content_hash(text)
    return {
        "source_id": f"wiki:{config}:{row_id}",
        "title": title,
        "summary": truncate_words(text, 80),
        "text": text,
        "content_hash": normalized_hash,
        "origin_dataset": WIKIPEDIA_DATASET_ID,
        "origin_config": config,
        "origin_split": split,
        "origin_url": str(row.get("url") or "").strip(),
    }


def collect_wikipedia_documents(
    *,
    target_count: int,
    config: str = WIKIPEDIA_CONFIG,
    split: str = WIKIPEDIA_SPLIT,
    minimum_chars: int = 1500,
    maximum_chars: int = 20000,
    max_scan: int = 10000,
    retries: int = 3,
) -> list[dict]:
    seen_hashes: set[str] = set()
    documents: list[dict] = []
    scanned = 0
    for row in iter_parquet_rows(
        WIKIPEDIA_DATASET_ID,
        config=config,
        split=split,
        retries=retries,
    ):
        scanned += 1
        doc = wikipedia_row_to_document(
            row,
            config=config,
            split=split,
            minimum_chars=minimum_chars,
            maximum_chars=maximum_chars,
        )
        if doc is None:
            if scanned >= max_scan:
                break
            continue
        if doc["content_hash"] in seen_hashes:
            if scanned >= max_scan:
                break
            continue
        seen_hashes.add(doc["content_hash"])
        documents.append(doc)
        if len(documents) >= target_count:
            break
        if scanned >= max_scan:
            break
    if len(documents) < target_count:
        raise RuntimeError(
            f"Collected only {len(documents)} accepted Wikipedia articles after scanning {scanned} rows; target was {target_count}."
        )
    return sorted(documents, key=lambda item: str(item.get("source_id") or ""))


def build_wikipedia_training_dataset(
    *,
    dataset_id: str,
    dataset_name: str,
    train_source_target: int,
    validation_source_target: int,
    config: str = WIKIPEDIA_CONFIG,
    split: str = WIKIPEDIA_SPLIT,
    minimum_chars: int = 1500,
    maximum_chars: int = 20000,
    max_scan: int = 10000,
    retries: int = 3,
) -> dict:
    target_count = int(train_source_target) + int(validation_source_target)
    documents = collect_wikipedia_documents(
        target_count=target_count,
        config=config,
        split=split,
        minimum_chars=minimum_chars,
        maximum_chars=maximum_chars,
        max_scan=max_scan,
        retries=retries,
    )
    total_text_chars = sum(len(str(doc.get("text") or "")) for doc in documents)
    dataset_hash = stable_content_hash(
        "\n".join(f"{doc['source_id']}:{doc['content_hash']}" for doc in documents)
    )
    return {
        "cluster_id": dataset_id,
        "cluster_name": dataset_name,
        "source_count": len(documents),
        "unique_content_hash_count": len(documents),
        "duplicate_content_count": 0,
        "duplicate_content_ratio": 0.0,
        "total_text_chars": total_text_chars,
        "estimated_token_count": estimate_text_tokens(total_text_chars),
        "dataset_hash": dataset_hash,
        "train_source_target": int(train_source_target),
        "validation_source_target": int(validation_source_target),
        "documents": documents,
        "origin_dataset": WIKIPEDIA_DATASET_ID,
        "origin_config": config,
        "origin_split": split,
    }


def export_squad_qa_files(
    output_dir: Path,
    *,
    config: str = SQUAD_CONFIG,
    train_split: str = SQUAD_TRAIN_SPLIT,
    validation_split: str = SQUAD_VALIDATION_SPLIT,
    train_limit: int | None = None,
    validation_limit: int | None = None,
    retries: int = 3,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    train_records = squad_rows_to_records(
        iter_parquet_rows(SQUAD_DATASET_ID, config=config, split=train_split, retries=retries),
        split=train_split,
        limit=train_limit,
    )
    validation_records = squad_rows_to_records(
        iter_parquet_rows(SQUAD_DATASET_ID, config=config, split=validation_split, retries=retries),
        split=validation_split,
        limit=validation_limit,
    )
    train_path = output_dir / "train-qa.jsonl"
    validation_path = output_dir / "validation-qa.jsonl"
    prompts_path = output_dir / "squad-validation-prompts.jsonl"
    _write_jsonl(train_path, train_records)
    _write_jsonl(validation_path, validation_records)
    prompt_rows = [
        {
            "qa_id": row["qa_id"],
            "question": row["question"],
            "answers": row["answers"],
            "answer": row["answer"],
            "is_impossible": row["is_impossible"],
            "title": row["title"],
        }
        for row in validation_records
    ]
    _write_jsonl(prompts_path, prompt_rows)
    return {
        "train_qa_path": str(train_path),
        "validation_qa_path": str(validation_path),
        "squad_validation_prompts_path": str(prompts_path),
        "squad_train_count": len(train_records),
        "squad_validation_count": len(validation_records),
    }


def squad_rows_to_records(rows, *, split: str, limit: int | None = None) -> list[dict]:
    records: list[dict] = []
    seen_pairs: set[str] = set()
    for row in rows:
        record = squad_row_to_record(dict(row), split=split)
        pair_key = stable_content_hash(f"{record['question']}\n{record['context']}")
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)
        records.append(record)
        if limit is not None and len(records) >= limit:
            break
    return records


def squad_row_to_record(row: dict, *, split: str) -> dict:
    raw_answers = row.get("answers") or {}
    texts = [normalize_external_text(str(item or "")) for item in raw_answers.get("text") or []]
    unique_answers = []
    seen_answers = set()
    for answer in texts:
        if not answer or answer in seen_answers:
            continue
        seen_answers.add(answer)
        unique_answers.append(answer)
    is_impossible = len(unique_answers) == 0
    answer = unique_answers[0] if unique_answers else ""
    context = normalize_external_text(str(row.get("context") or ""))
    question = normalize_external_text(str(row.get("question") or ""))
    title = normalize_external_text(str(row.get("title") or ""))
    qa_id = str(row.get("id") or "").strip()
    return {
        "qa_id": f"squad_v2:{split}:{qa_id}",
        "title": title,
        "question": question,
        "prompt": question,
        "context": context,
        "answers": unique_answers,
        "answer": answer,
        "is_impossible": is_impossible,
        "answer_starts": list(raw_answers.get("answer_start") or []),
        "origin_dataset": SQUAD_DATASET_ID,
        "origin_config": SQUAD_CONFIG,
        "origin_split": split,
        "input_token_estimate": estimate_text_tokens(len(question) + len(context)),
        "target_token_estimate": estimate_text_tokens(len(answer)),
    }


def truncate_words(text: str, count: int) -> str:
    parts = text.split()
    if len(parts) <= count:
        return text
    return " ".join(parts[:count]).strip()


def estimate_text_tokens(text_or_chars: int | str) -> int:
    if isinstance(text_or_chars, str):
        char_count = len(text_or_chars)
    else:
        char_count = int(text_or_chars)
    return max(1, char_count // 4)


def write_external_dataset_manifest(manifest_path: Path, payload: dict) -> None:
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def stable_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def write_external_training_dataset(dataset: dict, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)

    documents = list(dataset.get("documents") or [])
    train_count = int(dataset.get("train_source_target") or 0)
    validation_count = int(dataset.get("validation_source_target") or 0)
    if train_count <= 0 or validation_count <= 0:
        raise ValueError("External training dataset requires explicit positive train and validation source targets.")
    ordered = sorted(documents, key=lambda item: str(item.get("source_id") or ""))
    required = train_count + validation_count
    if len(ordered) < required:
        raise ValueError(f"Need {required} documents but only found {len(ordered)}.")
    train_documents = ordered[:train_count]
    validation_documents = ordered[train_count : train_count + validation_count]
    train_records = _training_records(train_documents)
    validation_records = _training_records(validation_documents)
    train_source_records = _source_records(train_documents)
    validation_source_records = _source_records(validation_documents)

    train_path = output_dir / "train.jsonl"
    validation_path = output_dir / "validation.jsonl"
    train_sources_path = output_dir / "train-sources.jsonl"
    validation_sources_path = output_dir / "validation-sources.jsonl"
    train_corpus_path = output_dir / "train-corpus.txt"
    validation_corpus_path = output_dir / "validation-corpus.txt"
    manifest_path = output_dir / "dataset-manifest.json"

    _write_jsonl(train_path, train_records)
    _write_jsonl(validation_path, validation_records)
    _write_jsonl(train_sources_path, train_source_records)
    _write_jsonl(validation_sources_path, validation_source_records)
    train_corpus_path.write_text(_source_corpus_text(train_documents), encoding="utf-8")
    validation_corpus_path.write_text(_source_corpus_text(validation_documents), encoding="utf-8")

    record_distribution: dict[str, int] = {}
    for row in [*train_records, *validation_records]:
        record_type = str(row.get("record_type") or "")
        record_distribution[record_type] = record_distribution.get(record_type, 0) + 1

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
        "record_type_distribution": record_distribution,
        "training_record_types": list(TRAINING_RECORD_TYPES),
        "expert_objective_version": EXPERT_OBJECTIVE_VERSION,
        "requires_retrieved_evidence": True,
        "behavior_profile": _dataset_behavior_profile(documents),
        "behavior_specialization_enabled": True,
        "benchmark_record_accounting": _benchmark_record_accounting(train_records, validation_records),
        "train_source_count": len(train_documents),
        "validation_source_count": len(validation_documents),
    }
    write_external_dataset_manifest(manifest_path, manifest)
    return {
        "dataset_dir": str(output_dir),
        "train_path": str(train_path),
        "validation_path": str(validation_path),
        "train_sources_path": str(train_sources_path),
        "validation_sources_path": str(validation_sources_path),
        "train_corpus_path": str(train_corpus_path),
        "validation_corpus_path": str(validation_corpus_path),
        "manifest_path": str(manifest_path),
        **manifest,
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    text = "\n".join(json.dumps(row, ensure_ascii=True) for row in rows)
    if text:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def _training_records(documents: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for doc in documents:
        rows.extend(_records_for_document(doc))
    return rows


def _records_for_document(doc: dict) -> list[dict]:
    title = str(doc.get("title") or "Untitled")
    summary = str(doc.get("summary") or "").strip()
    text = str(doc.get("text") or "").strip()
    snippets = _evidence_snippets(text or summary, max_items=5)
    if not snippets:
        snippets = ["The source contains grounded evidence."]
    local_terms = _preferred_terms(title, summary, text)
    evidence_block = "\n".join(f"[{index + 1}] {snippet}" for index, snippet in enumerate(snippets))
    evidence_handles = [f"source:{doc['source_id']}#snippet-{index + 1}" for index in range(len(snippets))]
    shared = {
        "source_id": str(doc.get("source_id") or ""),
        "content_hash": str(doc.get("content_hash") or ""),
        "evidence_handles": evidence_handles,
    }
    return [
        _build_record(
            "evidence_compression",
            (
                f"Compress the retrieved evidence for '{title}' into a short grounded digest.\n\n"
                f"Evidence:\n{evidence_block}"
            ),
            _grounded_digest(title, snippets),
            shared,
        ),
        _build_record(
            "terminology_normalization",
            (
                f"Rewrite the evidence for '{title}' using preferred terminology only.\n\n"
                f"Evidence:\n{evidence_block}\n\nGeneric phrasing: explain this in neutral wording."
            ),
            _terminology_target(title, local_terms, snippets),
            shared,
        ),
        _build_record(
            "style_rewrite",
            (
                f"Rewrite a neutral answer for '{title}' in the local style without adding facts.\n\n"
                f"Evidence:\n{evidence_block}\n\nNeutral answer: {snippets[0]}"
            ),
            _style_target(title, snippets),
            shared,
        ),
        _build_record(
            "reasoning_hint",
            (
                f"Give a short reasoning hint for '{title}' supported by the retrieved evidence.\n\n"
                f"Evidence:\n{evidence_block}"
            ),
            _reasoning_target(local_terms, snippets),
            shared,
        ),
        _build_record(
            "conflict_summary",
            (
                f"Summarize the evidence for '{title}' while noting any uncertainty or internal tension.\n\n"
                f"Evidence:\n{evidence_block}"
            ),
            _conflict_target(snippets),
            shared,
        ),
        _build_record(
            "uncertainty_boundary",
            (
                f"State what can and cannot be said from partial evidence for '{title}'.\n\n"
                f"Evidence:\n{evidence_block}"
            ),
            _uncertainty_target(snippets),
            shared,
        ),
        _build_record(
            "glossary_extract",
            (
                f"Extract a small grounded glossary for '{title}' from the retrieved evidence.\n\n"
                f"Evidence:\n{evidence_block}"
            ),
            _glossary_target(local_terms, snippets),
            shared,
        ),
    ]


def _build_record(record_type: str, user_prompt: str, assistant_target: str, shared: dict) -> dict:
    return {
        "messages": [
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": assistant_target},
        ],
        "record_type": record_type,
        "category": record_type,
        "source_id": shared["source_id"],
        "content_hash": shared["content_hash"],
        "source_ids": [shared["source_id"]],
        "content_hashes": [shared["content_hash"]],
        "evidence_handles": list(shared["evidence_handles"]),
        "input_token_estimate": estimate_text_tokens(user_prompt),
        "target_token_estimate": estimate_text_tokens(assistant_target),
        "grounding_required": True,
        "behavior_profile": {},
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
                "text_token_estimate": estimate_text_tokens(text),
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
    return ("\n\n".join(blocks).strip() + "\n") if blocks else ""


def _evidence_snippets(text: str, *, max_items: int) -> list[str]:
    normalized = normalize_external_text(text)
    if not normalized:
        return []
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", normalized) if part.strip()]
    chunks = paragraphs if paragraphs else [normalized]
    snippets = []
    for chunk in chunks:
        for sentence in re.split(r"(?<=[.!?])\s+", chunk):
            item = sentence.strip()
            if len(item) < 40:
                continue
            snippets.append(item)
            if len(snippets) >= max_items:
                return snippets
    return snippets[:max_items]


def _preferred_terms(title: str, summary: str, text: str) -> list[str]:
    candidates = []
    for item in re.findall(r"\b[A-Z][A-Za-z0-9_-]{3,}\b", " ".join([title, summary, text[:600]])):
        normalized = item.strip()
        lowered = normalized.lower()
        if lowered in GENERIC_TERM_STOPWORDS:
            continue
        if normalized.isupper() or re.fullmatch(r"[A-Z]?[0-9_-]+", normalized):
            continue
        if normalized not in candidates:
            candidates.append(item)
        if len(candidates) >= 5:
            break
    for item in _title_terms(title):
        if item not in candidates:
            candidates.append(item)
        if len(candidates) >= 5:
            break
    return candidates


def _grounded_digest(title: str, snippets: list[str]) -> str:
    lines = [f"Digest for {title}: {snippets[0]}"]
    if len(snippets) > 1:
        lines.append(f"Supporting detail: {snippets[1]}")
    lines.append("Use only the retrieved evidence above for downstream synthesis.")
    return " ".join(lines)


def _glossary_target(local_terms: list[str], snippets: list[str]) -> str:
    if not local_terms:
        return f"Local terms remain grounded in the evidence: {snippets[0]}"
    snippet = snippets[0]
    return " ".join(f"{term}: use this term only when referring to the evidence that states '{snippet}'." for term in local_terms[:3])


def _dataset_behavior_profile(documents: list[dict]) -> dict:
    vocabulary = []
    for doc in documents[:20]:
        for term in _preferred_terms(str(doc.get("title") or ""), str(doc.get("summary") or ""), str(doc.get("text") or "")):
            if term not in vocabulary:
                vocabulary.append(term)
            if len(vocabulary) >= 12:
                break
        if len(vocabulary) >= 12:
            break
    return {
        "local_terms": vocabulary,
        "source_count": len(documents),
    }


def _title_terms(title: str) -> list[str]:
    rows = []
    for item in re.findall(r"[A-Za-z][A-Za-z0-9'-]{3,}", title):
        lowered = item.lower()
        if lowered in GENERIC_TERM_STOPWORDS:
            continue
        if item not in rows:
            rows.append(item)
    return rows


def _terminology_target(title: str, local_terms: list[str], snippets: list[str]) -> str:
    preferred = ", ".join(local_terms[:3]) if local_terms else title
    return (
        f"Preferred terminology: {preferred}. "
        f"Grounded rewrite: {snippets[0]} "
        "Do not introduce new labels beyond the retrieved evidence."
    )


def _style_target(title: str, snippets: list[str]) -> str:
    supporting = f" Supporting detail: {snippets[1]}" if len(snippets) > 1 else ""
    return (
        f"Practical note on {title}: {snippets[0]}"
        f"{supporting} Keep the answer concrete, plain, and grounded in the retrieved evidence."
    )


def _reasoning_target(local_terms: list[str], snippets: list[str]) -> str:
    interpretation = (
        f"this supports a pattern around {', '.join(local_terms[:2])}"
        if local_terms
        else "this supports the local source context"
    )
    return (
        f"Evidence first: {snippets[0]} "
        f"Interpretation: {interpretation}. "
        "Conclusion: answer only from the retrieved evidence and avoid unsupported additions."
    )


def _conflict_target(snippets: list[str]) -> str:
    support = snippets[0]
    competing = snippets[1] if len(snippets) > 1 else snippets[0]
    return (
        f"Trusted evidence: {support} "
        f"If a later claim conflicts with '{competing}', mark that later claim as unverified until retrieved evidence supports it. "
        "State the conflict neutrally and keep the evidence visible."
    )


def _uncertainty_target(snippets: list[str]) -> str:
    return (
        f"Supported by evidence: {snippets[0]} "
        "Missing evidence: any details not stated in the retrieved text. "
        "If asked beyond that scope, say the source does not provide enough evidence to answer."
    )


def _benchmark_record_accounting(train_records: list[dict], validation_records: list[dict]) -> dict:
    return {
        "used_source_count": len({str(row.get('source_id') or '') for row in [*train_records, *validation_records]}),
        "train": _record_accounting_summary(train_records),
        "validation": _record_accounting_summary(validation_records),
    }


def _record_accounting_summary(rows: list[dict]) -> dict:
    record_type_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    for row in rows:
        record_type = str(row.get("record_type") or "")
        source_id = str(row.get("source_id") or "")
        record_type_counts[record_type] = record_type_counts.get(record_type, 0) + 1
        source_counts[source_id] = source_counts.get(source_id, 0) + 1
    total = max(1, len(rows))
    return {
        "count": len(rows),
        "record_type_counts": record_type_counts,
        "source_count": len(source_counts),
        "max_record_share_per_source_per_record_type": 1.0 / max(1, len(record_type_counts)) if record_type_counts else 0.0,
        "maximum_validation_record_share_per_source_per_category": max(source_counts.values(), default=0) / total,
        "minimum_validation_records_per_category": min(record_type_counts.values(), default=0),
    }


def iter_parquet_rows(dataset_name: str, *, config: str, split: str, retries: int):
    parquet_files = list_parquet_files(dataset_name, config=config, split=split, retries=retries)
    if not parquet_files:
        raise RuntimeError(f"No parquet files found for {dataset_name} config={config} split={split}.")
    for file_info in parquet_files:
        local_path = download_parquet_file(file_info["url"], retries=retries)
        yield from _rows_from_parquet(local_path)


def list_parquet_files(dataset_name: str, *, config: str, split: str, retries: int) -> list[dict]:
    endpoint = f"https://datasets-server.huggingface.co/parquet?dataset={dataset_name}"
    payload = _request_json(endpoint, retries=retries)
    rows = []
    for item in payload.get("parquet_files") or []:
        if str(item.get("config") or "") != config:
            continue
        if str(item.get("split") or "") != split:
            continue
        rows.append(dict(item))
    return rows


def download_parquet_file(url: str, *, retries: int) -> Path:
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    cache_root = Path(tempfile.gettempdir()) / "cml-hf-parquet-cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    parsed = urlparse(url)
    filename = Path(parsed.path).name or stable_content_hash(url)
    local_path = cache_root / f"{stable_content_hash(url)[:16]}-{filename}"
    if local_path.exists() and local_path.stat().st_size > 0:
        return local_path
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            with requests.get(url, stream=True, timeout=120) as response:
                response.raise_for_status()
                with local_path.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            handle.write(chunk)
            return local_path
        except Exception as exc:  # pragma: no cover - network retry path
            last_error = exc
            if local_path.exists():
                local_path.unlink(missing_ok=True)
            if attempt >= retries:
                break
            time.sleep(min(5, attempt))
    raise RuntimeError(f"Failed to download parquet shard: {url}") from last_error


def _rows_from_parquet(path: Path):
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(batch_size=128):
        for row in batch.to_pylist():
            yield row


def _request_json(url: str, *, retries: int) -> dict:
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            return dict(response.json())
        except Exception as exc:  # pragma: no cover - network retry path
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(min(5, attempt))
    raise RuntimeError(f"Failed to fetch JSON from {url}") from last_error
