from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.embeddings import tokenize  # noqa: E402
from backend.app.core.retrieval_scoring import (  # noqa: E402
    SOURCE_CLASS_WEIGHTS,
    _bm25_scores,
)
from scripts.backend.evaluate_vault_longmemeval_api import (  # noqa: E402
    Provider,
    _chat,
    _cohen_kappa,
    _finish_reason,
    _parse_binary_verdict,
    _provider,
    _provider_cost,
    _usage,
    _wilson_interval,
)


PROTOCOL = "beam-vault-paired-scored-evaluation-v2"
RETRIEVAL_PROTOCOL = "vault-hybrid-70-30-marginal-utility-atomic-beam-v3"
READER_PROTOCOLS = {
    "current": "beam-rubric-blind-memory-reader-v1",
    "evidence-first": "beam-evidence-first-memory-reader-v2",
}
JUDGE_PROTOCOL = "beam-rubric-structured-semantic-v2"
_TEMPORAL_QUESTION_RE = re.compile(
    r"\b(?:when|before|after|between|date|days?|weeks?|months?|years?|"
    r"timeline|chronolog|order|first|last|latest|earlier|later)\b",
    re.IGNORECASE,
)
_CONTRADICTION_QUESTION_RE = re.compile(
    r"\b(?:ever|contradict|conflict|which is correct|changed|update|latest)\b",
    re.IGNORECASE,
)
_MONTH_PATTERN = (
    r"January|February|March|April|May|June|July|August|"
    r"September|October|November|December"
)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(b"".join(_canonical_json(row) + b"\n" for row in rows))
    for attempt in range(6):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.1 * (attempt + 1))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare and optionally execute a paired BEAM Vault evaluation with "
            "CUDA retrieval embeddings and cost-capped API readers/judges."
        )
    )
    parser.add_argument("--parquet", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--extraction-windows", type=Path, required=True)
    parser.add_argument("--extraction-report", type=Path, required=True)
    parser.add_argument(
        "--selection-manifest",
        type=Path,
        help=(
            "Sealed manifest produced with the question set. Required for any "
            "promotion-eligible report; CLI role labels alone are not trusted."
        ),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--evaluation-role",
        choices=("development", "validation", "holdout"),
        default="development",
    )
    parser.add_argument(
        "--selection-mode",
        choices=("representative", "diagnostic"),
        default="representative",
    )
    parser.add_argument(
        "--atomic-extraction-scope",
        choices=("full-haystack", "retrieved-only"),
        default="full-haystack",
        help="retrieved-only is diagnostic and never promotion-eligible.",
    )
    parser.add_argument(
        "--embedding-model",
        default="sentence-transformers/all-MiniLM-L6-v2",
    )
    parser.add_argument(
        "--embedding-cache-dir",
        type=Path,
        default=Path("C:/Users/csshl/.cache/huggingface/hub"),
    )
    parser.add_argument("--raw-chunk-chars", type=int, default=6_000)
    parser.add_argument("--top-raw", type=int, default=10)
    parser.add_argument("--top-atomic", type=int, default=20)
    parser.add_argument("--max-context-chars", type=int, default=28_000)
    parser.add_argument("--oracle-question-count", type=int, default=20)
    parser.add_argument("--oracle-manifest", type=Path)
    parser.add_argument(
        "--scope",
        choices=("full", "oracle"),
        default="full",
        help="Run paired baseline/candidate tasks or only the verified oracle arm.",
    )
    parser.add_argument(
        "--reader-variant",
        choices=tuple(READER_PROTOCOLS),
        default="evidence-first",
    )
    parser.add_argument(
        "--raw-reserve-ratio",
        type=float,
        default=0.75,
        help="Candidate context fraction reserved for ranked raw evidence before atomics.",
    )
    parser.add_argument("--run-api", action="store_true")
    parser.add_argument("--max-api-cost-usd", type=float, default=2.50)
    parser.add_argument("--max-answer-tokens", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--api-concurrency", type=int, default=4)
    return parser.parse_args()


def _split_content(content: str, max_chars: int) -> list[str]:
    if max_chars < 512:
        raise ValueError("raw_chunk_chars_must_be_at_least_512")
    pieces: list[str] = []
    start = 0
    while start < len(content):
        hard_end = min(len(content), start + max_chars)
        end = hard_end
        if hard_end < len(content):
            minimum = start + int(max_chars * 0.6)
            candidates = [
                content.rfind(boundary, minimum, hard_end)
                for boundary in ("\n\n", "\n", ". ", " ")
            ]
            valid = [value for value in candidates if value >= minimum]
            if valid:
                end = max(valid) + 1
        pieces.append(content[start:end])
        start = end
    return pieces or [""]


def _split_content_with_offsets(content: str, max_chars: int) -> list[tuple[str, int, int]]:
    pieces = _split_content(content, max_chars)
    output: list[tuple[str, int, int]] = []
    cursor = 0
    for piece in pieces:
        end = cursor + len(piece)
        output.append((piece, cursor, end))
        cursor = end
    return output


def _raw_documents(rows: list[dict], selected_ids: set[str], max_chars: int) -> list[dict]:
    documents: list[dict] = []
    for row in rows:
        conversation_id = str(row["conversation_id"])
        if conversation_id not in selected_ids:
            continue
        for batch_index, batch in enumerate(row["chat"]):
            for turn in batch:
                content = str(turn.get("content") or "").strip()
                if not content:
                    continue
                turn_id = int(turn["id"])
                for piece_index, (piece, start_char, end_char) in enumerate(
                    _split_content_with_offsets(content, max_chars)
                ):
                    documents.append(
                        {
                            "doc_id": (
                                f"raw:{conversation_id}:{turn_id}:"
                                f"{piece_index:03d}"
                            ),
                            "conversation_id": conversation_id,
                            "kind": "raw",
                            "source_type": "external_transcript",
                            "source_turn_id": turn_id,
                            "batch_index": batch_index,
                            "role": str(turn.get("role") or ""),
                            "date": str(turn.get("time_anchor") or ""),
                            "text": piece,
                            "source_start_char": start_char,
                            "source_end_char": end_char,
                        }
                    )
    return documents


def _atomic_documents(
    extraction_report: dict, windows: list[dict]
) -> tuple[list[dict], list[dict]]:
    windows_by_id = {str(row["window_id"]): row for row in windows}
    documents: list[dict] = []
    audits: list[dict] = []
    seen: set[tuple[str, int, str]] = set()
    for result in extraction_report["results"]:
        window = windows_by_id[str(result["window_id"])]
        session_turns = window["turns"]
        source_slices = window["source_slices"]
        memory_records = (
            result.get("proposition_memories")
            or result.get("evidence_spans")
            or []
        )
        for span in memory_records:
            citation = span["citation"]
            turn_index = int(citation["turn_index"])
            excerpt = str(citation["excerpt"])
            matching_indices = [
                index
                for index, turn in enumerate(session_turns)
                if excerpt in str(turn.get("content") or "")
            ]
            if turn_index not in matching_indices and len(matching_indices) == 1:
                turn_index = matching_indices[0]
            if turn_index < 0 or turn_index >= len(source_slices):
                continue
            source_turn_id = int(source_slices[turn_index]["source_turn_id"])
            memory_text = str(span["memory_text"]).strip()
            key = (str(window["conversation_id"]), source_turn_id, memory_text.casefold())
            if key in seen:
                continue
            seen.add(key)
            document = {
                "doc_id": f"atomic:{window['conversation_id']}:{source_turn_id}:{len(documents):05d}",
                "conversation_id": str(window["conversation_id"]),
                "kind": "atomic",
                "source_type": "document",
                "source_turn_id": source_turn_id,
                "batch_index": int(window["batch_index"]),
                "role": str(span.get("attributed_to") or ""),
                "date": str(window["date"]),
                "text": memory_text,
                "evidence_kinds": sorted(
                    set(
                        map(
                            str,
                            span.get("evidence_kinds")
                            or [span.get("proposition_kind") or "relation"],
                        )
                    )
                ),
                "confidence": float(span["confidence"]),
                "source_start_char": (
                    int(citation["start_char"])
                    if citation.get("start_char") is not None
                    else max(
                        0,
                        str(session_turns[turn_index].get("content") or "").find(excerpt),
                    )
                ),
                "source_end_char": (
                    int(citation["end_char"])
                    if citation.get("end_char") is not None
                    else max(
                        0,
                        str(session_turns[turn_index].get("content") or "").find(excerpt),
                    )
                    + len(excerpt)
                ),
            }
            documents.append(document)
            audits.append(
                {
                    **document,
                    "citation_excerpt": excerpt,
                    "confidence": float(span["confidence"]),
                    "evidence_kinds": span["evidence_kinds"],
                }
            )
    return documents, audits


def _embed(
    texts: list[str],
    *,
    model_name: str,
    cache_dir: Path,
    cache_path: Path,
) -> np.ndarray:
    import torch
    from sentence_transformers import SentenceTransformer

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required; CPU embedding fallback is disabled")
    identity = {
        "model": model_name,
        "texts_sha256": _fingerprint(texts),
        "count": len(texts),
    }
    manifest_path = cache_path.with_suffix(".json")
    if cache_path.exists() and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest == identity:
            return np.load(cache_path)
    model = SentenceTransformer(
        model_name,
        cache_folder=str(cache_dir),
        local_files_only=True,
        device="cuda",
    )
    vectors = model.encode(
        texts,
        batch_size=64,
        normalize_embeddings=True,
        show_progress_bar=True,
        device="cuda",
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(cache_path, vectors)
    manifest_path.write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
    return np.asarray(vectors)


def _rank(
    query: str,
    documents: list[dict],
    document_vectors: np.ndarray,
    query_vector: np.ndarray,
) -> list[dict]:
    rows = [
        {"chunk_id": document["doc_id"], "text": document["text"]}
        for document in documents
    ]
    lexical = _bm25_scores(tokenize(query), rows)
    ranked: list[dict] = []
    for document, vector in zip(documents, document_vectors, strict=True):
        semantic = float(np.dot(query_vector, vector))
        source_class = (
            "external_transcript" if document["kind"] == "raw" else "document"
        )
        weight = SOURCE_CLASS_WEIGHTS[source_class]
        bm25 = float(lexical.get(document["doc_id"], 0.0))
        ranked.append(
            {
                **document,
                "semantic_score": round(semantic, 6),
                "bm25_score": round(bm25, 6),
                "combined_score": round(((semantic * 0.7) + (bm25 * 0.3)) * weight, 6),
            }
        )
    ranked.sort(key=lambda row: (-row["combined_score"], row["doc_id"]))
    return ranked


def _render_block(block: dict) -> str:
    label = "DERIVED" if block["kind"] == "atomic" else "RAW"
    fields = [
        label,
        f"turn={block['source_turn_id']}",
        f"role={block['role']}",
        (
            f"source_chars={block.get('source_start_char', 0)}:"
            f"{block.get('source_end_char', len(block['text']))}"
        ),
    ]
    if block.get("date"):
        fields.append(f"date={block['date']}")
    return f"[{';'.join(fields)}]\n{block['text']}"


def _pack(blocks: list[dict], max_chars: int) -> tuple[str, list[str]]:
    rendered: list[str] = []
    included: list[str] = []
    used = 0
    for block in blocks:
        text = _render_block(block)
        if rendered and used + len(text) > max_chars:
            continue
        if not rendered and len(text) > max_chars:
            text = text[:max_chars]
        rendered.append(text)
        included.append(block["doc_id"])
        used += len(text)
    return "\n\n".join(rendered), included


def _normalized_word_set(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


def _atomic_duplicates_raw(atomic: dict, raw_blocks: list[dict]) -> bool:
    atomic_text = str(atomic["text"]).strip().casefold()
    atomic_words = _normalized_word_set(atomic_text)
    if not atomic_words:
        return True
    for raw in raw_blocks:
        raw_text = str(raw["text"]).casefold()
        if atomic_text in raw_text:
            return True
        raw_words = _normalized_word_set(raw_text)
        overlap = len(atomic_words & raw_words) / len(atomic_words)
        if overlap >= 0.92:
            return True
    return False


_UTILITY_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "assistant",
    "at",
    "be",
    "because",
    "by",
    "for",
    "from",
    "has",
    "have",
    "he",
    "her",
    "his",
    "i",
    "in",
    "is",
    "it",
    "its",
    "me",
    "my",
    "of",
    "on",
    "or",
    "she",
    "that",
    "the",
    "their",
    "them",
    "they",
    "this",
    "to",
    "tool",
    "user",
    "was",
    "we",
    "were",
    "with",
    "you",
    "your",
}


def _atomic_utility_reason(
    atomic: dict,
    selected_raw: list[dict],
) -> tuple[bool, str]:
    """Keep derived text only when it contributes evidence or grounded semantics."""
    source_turn_id = int(atomic["source_turn_id"])
    same_source = [
        row for row in selected_raw if int(row["source_turn_id"]) == source_turn_id
    ]
    if not same_source:
        return True, "adds_source_turn"
    kinds = set(map(str, atomic.get("evidence_kinds") or []))
    if not kinds.intersection({"alias", "relation"}):
        return False, "same_source_without_relation_or_alias"
    atomic_words = _normalized_word_set(str(atomic["text"])) - _UTILITY_STOP_WORDS
    raw_words = set().union(
        *(
            _normalized_word_set(str(row["text"])) - _UTILITY_STOP_WORDS
            for row in same_source
        )
    )
    if atomic_words - raw_words:
        return True, "adds_normalized_relation"
    return False, "same_source_without_semantic_gain"


def _question_shape(question: str) -> str:
    if _TEMPORAL_QUESTION_RE.search(question):
        return "temporal"
    if _CONTRADICTION_QUESTION_RE.search(question):
        return "state_or_contradiction"
    if re.search(r"\b(?:summarize|summary|overview|progress)\b", question, re.IGNORECASE):
        return "summary"
    return "factual"


def _temporal_key(block: dict) -> tuple[datetime, int, int, str]:
    candidates = [str(block.get("date") or ""), str(block.get("text") or "")]
    parsed = datetime.max
    for value in candidates:
        iso = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", value)
        if iso:
            try:
                parsed = datetime.strptime(iso.group(0), "%Y-%m-%d")
                break
            except ValueError:
                pass
        named = re.search(
            rf"\b({_MONTH_PATTERN})\s+(\d{{1,2}})(?:,\s*(20\d{{2}}))?\b",
            value,
            re.IGNORECASE,
        )
        if named:
            year = named.group(3) or "2024"
            try:
                parsed = datetime.strptime(
                    f"{named.group(1)} {named.group(2)}, {year}",
                    "%B %d, %Y",
                )
                break
            except ValueError:
                pass
    return (
        parsed,
        int(block.get("batch_index") or 0),
        int(block["source_turn_id"]),
        str(block["doc_id"]),
    )


def _pack_candidate(
    question: str,
    raw_hits: list[dict],
    atomic_hits: list[dict],
    *,
    max_chars: int,
    raw_reserve_ratio: float,
) -> tuple[str, list[str], dict]:
    if not 0.5 <= raw_reserve_ratio <= 0.95:
        raise ValueError("raw_reserve_ratio_must_be_between_0.5_and_0.95")
    raw_reserve_chars = max(1, int(max_chars * raw_reserve_ratio))
    _, reserved_raw_ids = _pack(raw_hits, raw_reserve_chars)
    reserved_raw_id_set = set(reserved_raw_ids)
    selected_raw = [
        row for row in raw_hits if row["doc_id"] in reserved_raw_id_set
    ]
    selected_atomic: list[dict] = []
    used = sum(len(_render_block(block)) for block in selected_raw)
    duplicate_count = 0
    utility_skipped: dict[str, int] = {}
    utility_selected: dict[str, int] = {}
    for block in atomic_hits:
        if _atomic_duplicates_raw(block, selected_raw):
            duplicate_count += 1
            continue
        useful, reason = _atomic_utility_reason(block, selected_raw)
        if not useful:
            utility_skipped[reason] = utility_skipped.get(reason, 0) + 1
            continue
        rendered = _render_block(block)
        if used + len(rendered) > max_chars:
            continue
        selected_atomic.append(block)
        utility_selected[reason] = utility_selected.get(reason, 0) + 1
        used += len(rendered)
    selected_raw_ids = {row["doc_id"] for row in selected_raw}
    for block in raw_hits:
        if block["doc_id"] in selected_raw_ids:
            continue
        rendered = _render_block(block)
        if used + len(rendered) > max_chars:
            continue
        selected_raw.append(block)
        selected_raw_ids.add(block["doc_id"])
        used += len(rendered)
    shape = _question_shape(question)
    if shape == "temporal":
        ordered = sorted(
            [*selected_raw, *selected_atomic],
            key=lambda block: (*_temporal_key(block), block["kind"] == "atomic"),
        )
    else:
        ordered = [*selected_raw, *selected_atomic]
    context, identifiers = _pack(ordered, max_chars)
    diagnostics = {
        "question_shape": shape,
        "raw_reserve_ratio": raw_reserve_ratio,
        "raw_reserve_chars": raw_reserve_chars,
        "packing_policy": (
            "reserve-raw-then-add-marginal-utility-atomic-then-backfill-raw-v3"
        ),
        "raw_document_count": len(selected_raw),
        "atomic_document_count": len(selected_atomic),
        "duplicate_atomic_skipped": duplicate_count,
        "utility_atomic_selected_by_reason": dict(sorted(utility_selected.items())),
        "utility_atomic_skipped_by_reason": dict(sorted(utility_skipped.items())),
        "context_chars": len(context),
        "raw_document_ids": [row["doc_id"] for row in selected_raw],
        "atomic_document_ids": [row["doc_id"] for row in selected_atomic],
        "source_turn_ids": sorted(
            {int(row["source_turn_id"]) for row in [*selected_raw, *selected_atomic]}
        ),
    }
    return context, identifiers, diagnostics


def prepare_retrieval(args: argparse.Namespace) -> tuple[list[dict], dict]:
    questions = _load_jsonl(args.questions)
    selection_manifest: dict = {}
    selection_manifest_failures: list[str] = []
    if args.selection_manifest:
        selection_manifest = json.loads(
            args.selection_manifest.read_text(encoding="utf-8")
        )
        expected_questions_hash = str(
            selection_manifest.get("questions_sha256") or ""
        )
        expected_windows_hash = str(
            selection_manifest.get("extraction_windows_sha256") or ""
        )
        if expected_questions_hash != _file_sha256(args.questions):
            selection_manifest_failures.append("questions_manifest_hash_mismatch")
        if expected_windows_hash != _file_sha256(args.extraction_windows):
            selection_manifest_failures.append(
                "extraction_windows_manifest_hash_mismatch"
            )
        manifest_role = str(selection_manifest.get("evaluation_role") or "")
        manifest_mode = str(selection_manifest.get("selection_mode") or "")
        if manifest_role != args.evaluation_role:
            selection_manifest_failures.append("evaluation_role_manifest_mismatch")
        if manifest_mode != args.selection_mode:
            selection_manifest_failures.append("selection_mode_manifest_mismatch")
    else:
        selection_manifest_failures.append("selection_manifest_missing")
    oracle_manifest = {"entries": {}}
    if args.oracle_manifest:
        oracle_manifest = json.loads(args.oracle_manifest.read_text(encoding="utf-8"))
        if oracle_manifest.get("protocol") != "beam-verified-oracle-v1":
            raise ValueError("unsupported_oracle_manifest_protocol")
    oracle_entries = oracle_manifest.get("entries") or {}
    selected_ids = {str(row["conversation_id"]) for row in questions}
    parquet_rows = pq.read_table(args.parquet).to_pylist()
    windows = _load_jsonl(args.extraction_windows)
    extraction_report = json.loads(args.extraction_report.read_text(encoding="utf-8"))
    raw_documents = _raw_documents(parquet_rows, selected_ids, args.raw_chunk_chars)
    atomic_documents, audits = _atomic_documents(extraction_report, windows)
    documents = [*raw_documents, *atomic_documents]
    documents_by_id = {row["doc_id"]: row for row in documents}
    texts = [row["text"] for row in documents]
    query_texts = [row["question"] for row in questions]
    document_vectors = _embed(
        texts,
        model_name=args.embedding_model,
        cache_dir=args.embedding_cache_dir,
        cache_path=args.output_dir / "document-embeddings.npy",
    )
    query_vectors = _embed(
        query_texts,
        model_name=args.embedding_model,
        cache_dir=args.embedding_cache_dir,
        cache_path=args.output_dir / "question-embeddings.npy",
    )
    by_conversation: dict[str, list[int]] = defaultdict(list)
    for index, document in enumerate(documents):
        by_conversation[document["conversation_id"]].append(index)
    rows: list[dict] = []
    raw_recall_values: list[float] = []
    atomic_recall_values: list[float] = []
    baseline_packed_recall_values: list[float] = []
    candidate_packed_recall_values: list[float] = []
    for position, (question, query_vector) in enumerate(
        zip(questions, query_vectors, strict=True), start=1
    ):
        indices = by_conversation[str(question["conversation_id"])]
        conversation_documents = [documents[index] for index in indices]
        conversation_vectors = document_vectors[indices]
        ranked = _rank(
            question["question"],
            conversation_documents,
            conversation_vectors,
            query_vector,
        )
        raw_hits = [row for row in ranked if row["kind"] == "raw"][: args.top_raw]
        atomic_hits = [row for row in ranked if row["kind"] == "atomic"][: args.top_atomic]
        baseline_context, baseline_ids = _pack(raw_hits, args.max_context_chars)
        candidate_context, candidate_ids, packing_diagnostics = _pack_candidate(
            question["question"],
            raw_hits,
            atomic_hits,
            max_chars=args.max_context_chars,
            raw_reserve_ratio=args.raw_reserve_ratio,
        )
        gold = set(int(value) for value in question["source_chat_ids"])
        raw_found = gold & {int(row["source_turn_id"]) for row in raw_hits}
        atomic_found = gold & {int(row["source_turn_id"]) for row in atomic_hits}
        baseline_packed_found = gold & {
            int(documents_by_id[doc_id]["source_turn_id"]) for doc_id in baseline_ids
        }
        candidate_packed_found = gold & set(
            packing_diagnostics["source_turn_ids"]
        )
        if gold:
            raw_recall_values.append(len(raw_found) / len(gold))
            atomic_recall_values.append(len(atomic_found) / len(gold))
            baseline_packed_recall_values.append(
                len(baseline_packed_found) / len(gold)
            )
            candidate_packed_recall_values.append(
                len(candidate_packed_found) / len(gold)
            )
        oracle_selected = (
            question["question_id"] in oracle_entries if args.oracle_manifest else True
        )
        oracle_entry = dict(oracle_entries.get(question["question_id"]) or {})
        verified_gold = set(
            int(value)
            for value in oracle_entry.get(
                "verified_source_chat_ids", question["source_chat_ids"]
            )
        )
        oracle_hits = [
            document
            for document in conversation_documents
            if document["kind"] == "raw"
            and int(document["source_turn_id"]) in verified_gold
        ]
        oracle_hits.sort(
            key=lambda row: (
                int(row.get("batch_index") or 0),
                int(row["source_turn_id"]),
                int(row.get("source_start_char") or 0),
            )
        )
        oracle_context, oracle_ids = _pack(oracle_hits, args.max_context_chars)
        oracle_valid = bool(
            oracle_selected
            and oracle_entry.get(
                "evaluation_valid",
                bool(verified_gold) or bool(question.get("is_abstention")),
            )
        )
        effective_answer = str(
            oracle_entry.get("reference_override") or question["answer"]
        )
        effective_rubric = list(
            oracle_entry.get("rubric_override") or question["rubric"]
        )
        rows.append(
            {
                **question,
                "effective_answer": effective_answer,
                "effective_rubric": effective_rubric,
                "rank": position,
                "baseline_context": baseline_context,
                "candidate_context": candidate_context,
                "oracle_context": oracle_context,
                "baseline_document_ids": baseline_ids,
                "candidate_document_ids": candidate_ids,
                "packing_diagnostics": packing_diagnostics,
                "oracle_document_ids": oracle_ids,
                "oracle_selected": oracle_selected,
                "oracle_valid": oracle_valid,
                "oracle_verification_reason": str(
                    oracle_entry.get("verification_reason") or ""
                ),
                "verified_source_chat_ids": sorted(verified_gold),
                "oracle_context_sha256": _fingerprint(oracle_context),
                "raw_found_source_ids": sorted(raw_found),
                "atomic_found_source_ids": sorted(atomic_found),
                "baseline_packed_found_source_ids": sorted(baseline_packed_found),
                "candidate_packed_found_source_ids": sorted(candidate_packed_found),
                "raw_recall_at_k": len(raw_found) / len(gold) if gold else None,
                "atomic_recall_at_k": len(atomic_found) / len(gold) if gold else None,
                "baseline_packed_recall": (
                    len(baseline_packed_found) / len(gold) if gold else None
                ),
                "candidate_packed_recall": (
                    len(candidate_packed_found) / len(gold) if gold else None
                ),
                "retrieval_protocol": RETRIEVAL_PROTOCOL,
            }
        )
        if position % 10 == 0:
            print(f"retrieved {position}/{len(questions)}", flush=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(args.output_dir / "retrieval.jsonl", rows)
    audit_ranked = sorted(
        audits,
        key=lambda row: _fingerprint(["beam-fact-audit-v1", row["doc_id"]]),
    )[:100]
    _write_jsonl(args.output_dir / "fact-audit-sample.jsonl", audit_ranked)
    extraction_results = extraction_report["results"]
    structural = {
        "window_count": len(extraction_results),
        "schema_rate": statistics.fmean(
            bool(row["schema_compliant"]) for row in extraction_results
        ),
        "structural_pass_rate": statistics.fmean(
            bool(row["structural_pass"]) for row in extraction_results
        ),
        "truncation_rate": statistics.fmean(
            bool(row.get("output_truncated")) for row in extraction_results
        ),
        "compiler_rejection_count": sum(
            int(row.get("compiler_rejected_count") or 0) for row in extraction_results
        ),
        "normalized_citation_issue_count": sum(
            int(row.get("normalized_citation_issue_count") or 0)
            for row in extraction_results
        ),
        "model_citation_issue_count": sum(
            int(row.get("model_citation_issue_count") or 0)
            for row in extraction_results
        ),
        "evidence_span_count": len(atomic_documents),
        "duplicate_span_count": sum(
            len(row.get("evidence_spans") or []) for row in extraction_results
        )
        - len(atomic_documents),
        "peak_gpu_memory_mib": extraction_report["summary"]["peak_gpu_memory_mib"],
        "mean_window_seconds": extraction_report["summary"]["mean_wall_seconds"],
        "max_window_seconds": extraction_report["summary"]["max_wall_seconds"],
    }
    offline_promotion_failures: list[str] = []
    offline_promotion_failures.extend(selection_manifest_failures)
    if args.evaluation_role != "development":
        offline_promotion_failures.append("offline_replay_must_use_development_data")
    if args.selection_mode != "representative":
        offline_promotion_failures.append("selection_is_not_representative")
    if args.atomic_extraction_scope != "full-haystack":
        offline_promotion_failures.append("extraction_scope_is_not_full_haystack")
    if structural["schema_rate"] < 0.98:
        offline_promotion_failures.append("schema_rate_below_98_percent")
    if structural["truncation_rate"] > 0:
        offline_promotion_failures.append("truncated_extraction_windows")
    if structural["normalized_citation_issue_count"] > 0:
        offline_promotion_failures.append("normalized_citation_issues")
    if statistics.fmean(candidate_packed_recall_values) < statistics.fmean(
        baseline_packed_recall_values
    ):
        offline_promotion_failures.append("candidate_packed_recall_regressed")
    if any(
        set(row["baseline_packed_found_source_ids"])
        - set(row["packing_diagnostics"]["source_turn_ids"])
        for row in rows
    ):
        offline_promotion_failures.append(
            "answer_provenance_from_baseline_was_displaced"
        )
    summary = {
        "protocol": PROTOCOL,
        "retrieval_protocol": RETRIEVAL_PROTOCOL,
        "evaluation_role": args.evaluation_role,
        "selection_mode": args.selection_mode,
        "selection_manifest": {
            "provided": bool(args.selection_manifest),
            "sha256": (
                _file_sha256(args.selection_manifest)
                if args.selection_manifest
                else None
            ),
            "validation_failures": selection_manifest_failures,
        },
        "atomic_extraction_scope": args.atomic_extraction_scope,
        "question_count": len(questions),
        "raw_document_count": len(raw_documents),
        "atomic_document_count": len(atomic_documents),
        "fact_audit_sample_count": len(audit_ranked),
        "raw_macro_recall_at_k": statistics.fmean(raw_recall_values),
        "atomic_macro_recall_at_k": statistics.fmean(atomic_recall_values),
        "baseline_packed_macro_recall": statistics.fmean(
            baseline_packed_recall_values
        ),
        "candidate_packed_macro_recall": statistics.fmean(
            candidate_packed_recall_values
        ),
        "packing": {
            "mean_raw_documents": statistics.fmean(
                row["packing_diagnostics"]["raw_document_count"] for row in rows
            ),
            "mean_atomic_documents": statistics.fmean(
                row["packing_diagnostics"]["atomic_document_count"] for row in rows
            ),
            "mean_context_chars": statistics.fmean(
                row["packing_diagnostics"]["context_chars"] for row in rows
            ),
            "total_duplicate_atomics_skipped": sum(
                row["packing_diagnostics"]["duplicate_atomic_skipped"] for row in rows
            ),
            "baseline_raw_documents_not_retained": sum(
                len(
                    set(row["baseline_document_ids"])
                    - set(row["packing_diagnostics"]["raw_document_ids"])
                )
                for row in rows
            ),
            "relevant_baseline_source_turns_not_retained": sum(
                len(
                    set(row["baseline_packed_found_source_ids"])
                    - set(row["packing_diagnostics"]["source_turn_ids"])
                )
                for row in rows
            ),
        },
        "oracle": {
            "manifest_protocol": oracle_manifest.get("protocol"),
            "manifest_sha256": (
                _fingerprint(oracle_manifest) if args.oracle_manifest else None
            ),
            "valid_question_count": sum(bool(row["oracle_valid"]) for row in rows),
            "invalid_question_count": sum(
                bool(row["oracle_selected"]) and not bool(row["oracle_valid"])
                for row in rows
            ),
            "selected_question_count": sum(
                bool(row["oracle_selected"]) for row in rows
            ),
            "empty_valid_context_count": sum(
                bool(row["oracle_valid"])
                and not row["oracle_context"]
                and not bool(row.get("is_abstention"))
                for row in rows
            ),
        },
        "structural_extraction": structural,
        "cuda_embedding_model": args.embedding_model,
        "cpu_model_fallback_allowed": False,
        "offline_retrieval_gate_passed": not offline_promotion_failures,
        "offline_retrieval_gate_failures": offline_promotion_failures,
        "promotion_passed": False,
        "promotion_blocker": (
            "Cached answer-level failure replay must predict a positive accuracy delta "
            "with zero new regressions before reader evaluation."
        ),
    }
    (args.output_dir / "offline-report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return rows, summary


def _answer_prompt(question: dict, context: str, variant: str = "evidence-first") -> str:
    if variant not in READER_PROTOCOLS:
        raise ValueError(f"unsupported_reader_variant:{variant}")
    if variant == "current":
        instructions = (
            "Use only the supplied Vault context. Follow any requested output format "
            "exactly. If the context does not support an answer, say that the information "
            "is unavailable. Give the answer directly without discussing retrieval."
        )
    else:
        instructions = """Use only the supplied Vault context. RAW CONVERSATION is authoritative; DERIVED ATOMIC MEMORY is a retrieval aid and must not override conflicting raw evidence.
Before answering, silently identify all evidence needed for the requested result. For elapsed time, state both endpoint dates and the calculated duration. For ordering, use event dates and source-turn order. For summaries and causal explanations, cover each distinct supported action or change without adding generic advice or inferred metrics. For progress questions, distinguish completed work from plans; summarize supported plans instead of claiming that all information is unavailable. If the evidence contains contradictory user claims, report both claims and ask for clarification instead of choosing one. Follow remembered formatting and response-style preferences when present. If evidence is genuinely insufficient, say so without guessing. Return only the concise final answer; do not expose your analysis or discuss retrieval."""
    return f"""You are answering a long-term conversational-memory question. {instructions}

Vault context:
{context}

Question: {question['question']}

Answer:"""


def _judge_prompt(question: dict, answer: str) -> str:
    rubric = "\n".join(
        f"- {item}" for item in question.get("effective_rubric", question["rubric"])
    )
    reference = question.get("effective_answer", question["answer"])
    return f"""Semantically grade the model answer against the question, reference, and required rubric. Equivalent wording, compact answers, and omitted units already explicit in the question are acceptable. A scalar answer such as "7" is equivalent to "7 women" when the question supplies the entity and the number matches. Date wording may vary if the date and requested format are correct. Do not require the model to repeat explanatory reference prose unless the rubric requires it.

For contradiction questions, correctness requires acknowledging all material conflicting claims rather than selecting one unsupported side. For calculations, the final value and the stated endpoints/reasoning must not conflict. For abstention questions, the answer must appropriately state that the requested information is unavailable.

Keep reason at 12 words or fewer. Use integer indexes only in both rubric arrays. Do not restate the answer, reference, or rubric. Return one compact JSON object only:
{{"correct":true_or_false,"reason":"brief semantic reason","satisfied_rubric_items":[0],"missing_rubric_items":[],"contradiction":false}}

Question: {question['question']}

Reference answer: {reference}

Required rubric:
{rubric}

Model answer: {answer}
"""


def _parse_structured_verdict(raw: str) -> dict:
    candidate = raw.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        leading_boolean = re.search(
            r'"correct"\s*:\s*(true|false)', candidate, re.IGNORECASE
        )
        if leading_boolean:
            return {
                "correct": leading_boolean.group(1).casefold() == "true",
                "reason": "truncated_structured_verdict_recovered",
                "satisfied_rubric_items": [],
                "missing_rubric_items": [],
                "contradiction": False,
            }
        return {
            "correct": _parse_binary_verdict(candidate),
            "reason": "legacy_binary_fallback",
            "satisfied_rubric_items": [],
            "missing_rubric_items": [],
            "contradiction": False,
        }
    if not isinstance(payload, dict) or not isinstance(payload.get("correct"), bool):
        raise ValueError(f"invalid_structured_judge_verdict:{raw[:200]}")
    return {
        "correct": bool(payload["correct"]),
        "reason": str(payload.get("reason") or "")[:500],
        "satisfied_rubric_items": [
            int(value) for value in payload.get("satisfied_rubric_items") or []
        ],
        "missing_rubric_items": [
            int(value) for value in payload.get("missing_rubric_items") or []
        ],
        "contradiction": bool(payload.get("contradiction")),
    }


def _adjudication_prompt(
    question: dict,
    answer: str,
    primary_verdict: dict,
    independent_verdict: dict,
) -> str:
    return (
        _judge_prompt(question, answer)
        + "\nTwo graders disagreed. Resolve the disagreement from the source question, "
        "reference, rubric, and model answer—not by majority vote. Preserve semantic "
        "equivalence but enforce every explicit rubric item. Their compact records are:\n"
        f"Grader A: {json.dumps(primary_verdict, ensure_ascii=False)}\n"
        f"Grader B: {json.dumps(independent_verdict, ensure_ascii=False)}\n"
        "Return the same compact JSON schema with your final decision."
    )


def _estimated_tokens(text: str) -> int:
    return math.ceil(len(text) / 3.5)


def _estimated_cost(provider: Provider, prompt_tokens: int, output_tokens: int) -> float:
    return (
        prompt_tokens * provider.input_price_per_million
        + output_tokens * provider.output_price_per_million
    ) / 1_000_000


def cost_preview(args: argparse.Namespace, rows: list[dict]) -> dict:
    reader = _provider("kimi", "kimi-k2.6")
    primary = _provider("kimi", "kimi-k2.6")
    independent = _provider("openai", "gpt-5.4-2026-03-05")
    valid_oracle_rows = [
        row
        for row in rows
        if bool(row.get("oracle_selected")) and bool(row.get("oracle_valid"))
    ]
    oracle_ids = {
        row["question_id"]
        for row in sorted(
            valid_oracle_rows,
            key=lambda row: _fingerprint(["beam-oracle-v2", row["question_id"]]),
        )[: args.oracle_question_count]
    }
    tasks = []
    if args.scope == "full":
        tasks = [
            (arm, row, row[f"{arm}_context"])
            for row in rows
            for arm in ("baseline", "candidate")
        ]
    tasks.extend(
        ("oracle", row, row["oracle_context"])
        for row in rows
        if row["question_id"] in oracle_ids
    )
    reader_prompt_tokens = sum(
        _estimated_tokens(_answer_prompt(row, context, args.reader_variant))
        for _, row, context in tasks
    )
    assumed_answer_tokens = 160 * len(tasks)
    assumed_judge_prompt_tokens = sum(
        _estimated_tokens(_judge_prompt(row, "x" * 560))
        for _, row, _ in tasks
    )
    assumed_judge_output_tokens = 60 * len(tasks)
    base_estimated = {
        "reader": _estimated_cost(reader, reader_prompt_tokens, assumed_answer_tokens),
        "primary_judge": _estimated_cost(
            primary, assumed_judge_prompt_tokens, assumed_judge_output_tokens
        ),
        "independent_judge": _estimated_cost(
            independent, assumed_judge_prompt_tokens, assumed_judge_output_tokens
        ),
    }
    adjudicator_upper_bound = _estimated_cost(
        independent,
        int(assumed_judge_prompt_tokens * 1.3),
        assumed_judge_output_tokens,
    )
    adjudicator_expected = adjudicator_upper_bound * 0.15
    expected_total = sum(base_estimated.values()) + adjudicator_expected
    upper_bound_total = sum(base_estimated.values()) + adjudicator_upper_bound
    preview = {
        "protocol": PROTOCOL,
        "reader_task_count": len(tasks),
        "paired_question_count": len(rows),
        "oracle_question_count": len(oracle_ids),
        "scope": args.scope,
        "reader_variant": args.reader_variant,
        "estimated_tokens": {
            "reader_prompt": reader_prompt_tokens,
            "reader_completion_assumption": assumed_answer_tokens,
            "per_judge_prompt": assumed_judge_prompt_tokens,
            "per_judge_completion_assumption": assumed_judge_output_tokens,
        },
        "estimated_usd": {
            **base_estimated,
            "adjudicator_expected_15pct_disagreement": adjudicator_expected,
            "adjudicator_upper_bound": adjudicator_upper_bound,
            "base_total": sum(base_estimated.values()),
            "expected_total": expected_total,
            "upper_bound_total": upper_bound_total,
        },
        "hard_cap_usd": args.max_api_cost_usd,
        "passes_cost_cap": expected_total <= args.max_api_cost_usd,
        "oracle_question_ids": sorted(oracle_ids),
    }
    (args.output_dir / "cost-preview.json").write_text(
        json.dumps(preview, indent=2) + "\n", encoding="utf-8"
    )
    return preview


def _checkpoint_rows(path: Path, rows_by_key: dict[str, dict], order: list[str]) -> None:
    _write_jsonl(path, [rows_by_key[key] for key in order if key in rows_by_key])


def _arm_task_ids(task_order: list[str], arm: str) -> list[str]:
    return [task_id for task_id in task_order if task_id.startswith(f"{arm}:")]


def run_api(args: argparse.Namespace, retrieval_rows: list[dict], preview: dict) -> dict:
    if not preview["passes_cost_cap"]:
        raise RuntimeError(
            "predicted_api_cost_exceeds_cap:"
            f"{preview['estimated_usd']['expected_total']:.6f}>"
            f"{args.max_api_cost_usd:.6f}"
        )
    reader = _provider("kimi", "kimi-k2.6")
    primary = _provider("kimi", "kimi-k2.6")
    independent = _provider("openai", "gpt-5.4-2026-03-05")
    oracle_ids = set(preview["oracle_question_ids"])
    tasks = []
    if args.scope == "full":
        tasks = [
            {
                "task_id": f"{arm}:{row['question_id']}",
                "arm": arm,
                "question": row,
                "context": row[f"{arm}_context"],
            }
            for row in retrieval_rows
            for arm in ("baseline", "candidate")
        ]
    tasks.extend(
        {
            "task_id": f"oracle:{row['question_id']}",
            "arm": "oracle",
            "question": row,
            "context": row["oracle_context"],
        }
        for row in retrieval_rows
        if row["question_id"] in oracle_ids
    )
    task_order = [task["task_id"] for task in tasks]
    hypothesis_path = args.output_dir / "hypotheses.jsonl"
    hypotheses = {
        row["task_id"]: row for row in _load_jsonl(hypothesis_path)
    }
    if args.api_concurrency < 1 or args.api_concurrency > 8:
        raise ValueError("api_concurrency_must_be_between_1_and_8")

    def read_one(task: dict) -> dict:
        started = time.perf_counter()
        response = _chat(
            reader,
            _answer_prompt(
                task["question"], task["context"], variant=args.reader_variant
            ),
            max_tokens=args.max_answer_tokens,
            timeout=args.timeout,
            retries=args.retries,
        )
        choice = response["choices"][0]
        return {
            "task_id": task["task_id"],
            "arm": task["arm"],
            "question_id": task["question"]["question_id"],
            "conversation_id": task["question"]["conversation_id"],
            "category": task["question"]["category"],
            "answer": str(choice["message"]["content"]).strip(),
            "reader_usage": _usage(response),
            "reader_finish_reason": _finish_reason(response),
            "reader_wall_seconds": time.perf_counter() - started,
            "reader_protocol": READER_PROTOCOLS[args.reader_variant],
        }

    pending_reader_tasks = [
        task for task in tasks if task["task_id"] not in hypotheses
    ]
    with ThreadPoolExecutor(max_workers=args.api_concurrency) as executor:
        futures = {
            executor.submit(read_one, task): task for task in pending_reader_tasks
        }
        completed_reader_count = len(hypotheses)
        for future in as_completed(futures):
            task = futures[future]
            row = future.result()
            hypotheses[task["task_id"]] = row
            completed_reader_count += 1
            _checkpoint_rows(hypothesis_path, hypotheses, task_order)
            print(
                f"reader {completed_reader_count}/{len(tasks)} {task['task_id']}",
                flush=True,
            )

    question_by_id = {row["question_id"]: row for row in retrieval_rows}

    def judge_all(provider: Provider, suffix: str) -> list[dict]:
        path = args.output_dir / f"judged-{suffix}.jsonl"
        existing = {row["task_id"]: row for row in _load_jsonl(path)}

        def judge_one(task_id: str) -> dict:
            hypothesis = hypotheses[task_id]
            question = question_by_id[hypothesis["question_id"]]
            started = time.perf_counter()
            response = _chat(
                provider,
                _judge_prompt(question, hypothesis["answer"]),
                max_tokens=96,
                timeout=args.timeout,
                retries=args.retries,
            )
            raw = str(response["choices"][0]["message"]["content"]).strip()
            verdict = _parse_structured_verdict(raw)
            return {
                "task_id": task_id,
                "arm": hypothesis["arm"],
                "question_id": hypothesis["question_id"],
                "category": hypothesis["category"],
                **verdict,
                "raw_verdict": raw,
                "judge_usage": _usage(response),
                "judge_finish_reason": _finish_reason(response),
                "judge_wall_seconds": time.perf_counter() - started,
                "judge_protocol": JUDGE_PROTOCOL,
                "model": provider.model,
            }

        pending_task_ids = [task_id for task_id in task_order if task_id not in existing]
        with ThreadPoolExecutor(max_workers=args.api_concurrency) as executor:
            futures = {
                executor.submit(judge_one, task_id): task_id
                for task_id in pending_task_ids
            }
            completed_judge_count = len(existing)
            for future in as_completed(futures):
                task_id = futures[future]
                existing[task_id] = future.result()
                completed_judge_count += 1
                _checkpoint_rows(path, existing, task_order)
                print(
                    f"{suffix} judge {completed_judge_count}/{len(task_order)} "
                    f"{task_id}",
                    flush=True,
                )
        return [existing[key] for key in task_order]

    primary_rows = judge_all(primary, "kimi")
    independent_rows = judge_all(independent, "openai")
    primary_by_id = {row["task_id"]: row for row in primary_rows}
    independent_by_id = {row["task_id"]: row for row in independent_rows}
    question_by_id = {row["question_id"]: row for row in retrieval_rows}
    disagreement_ids = [
        task_id
        for task_id in task_order
        if bool(primary_by_id[task_id]["correct"])
        != bool(independent_by_id[task_id]["correct"])
    ]
    adjudication_path = args.output_dir / "adjudicated-openai.jsonl"
    adjudications = {
        row["task_id"]: row for row in _load_jsonl(adjudication_path)
    }
    preliminary_costs = {
        "reader": _provider_cost(
            reader,
            [
                hypotheses[task_id]["reader_usage"]
                for task_id in task_order
            ],
        ),
        "primary_judge": _provider_cost(
            primary, [row["judge_usage"] for row in primary_rows]
        ),
        "independent_judge": _provider_cost(
            independent, [row["judge_usage"] for row in independent_rows]
        ),
    }
    preliminary_total = sum(
        value["estimated_usd_with_reported_cache"]
        for value in preliminary_costs.values()
    )
    unresolved_disagreements = [
        task_id for task_id in disagreement_ids if task_id not in adjudications
    ]
    adjudication_prompt_tokens = sum(
        _estimated_tokens(
            _adjudication_prompt(
                question_by_id[hypotheses[task_id]["question_id"]],
                hypotheses[task_id]["answer"],
                primary_by_id[task_id],
                independent_by_id[task_id],
            )
        )
        for task_id in unresolved_disagreements
    )
    projected_adjudication_cost = _estimated_cost(
        independent,
        adjudication_prompt_tokens,
        60 * len(unresolved_disagreements),
    )
    adjudication_skipped_due_cost = (
        preliminary_total + projected_adjudication_cost > args.max_api_cost_usd
    )

    def adjudicate_one(task_id: str) -> dict:
        hypothesis = hypotheses[task_id]
        question = question_by_id[hypothesis["question_id"]]
        started = time.perf_counter()
        response = _chat(
            independent,
            _adjudication_prompt(
                question,
                hypothesis["answer"],
                primary_by_id[task_id],
                independent_by_id[task_id],
            ),
            max_tokens=96,
            timeout=args.timeout,
            retries=args.retries,
        )
        raw = str(response["choices"][0]["message"]["content"]).strip()
        return {
            "task_id": task_id,
            "arm": hypothesis["arm"],
            "question_id": hypothesis["question_id"],
            "category": hypothesis["category"],
            **_parse_structured_verdict(raw),
            "raw_verdict": raw,
            "judge_usage": _usage(response),
            "judge_finish_reason": _finish_reason(response),
            "judge_wall_seconds": time.perf_counter() - started,
            "judge_protocol": f"{JUDGE_PROTOCOL}-disagreement-adjudication",
            "model": independent.model,
        }

    pending_adjudications = (
        [] if adjudication_skipped_due_cost else unresolved_disagreements
    )
    with ThreadPoolExecutor(max_workers=args.api_concurrency) as executor:
        futures = {
            executor.submit(adjudicate_one, task_id): task_id
            for task_id in pending_adjudications
        }
        completed_count = len(adjudications)
        for future in as_completed(futures):
            task_id = futures[future]
            adjudications[task_id] = future.result()
            completed_count += 1
            _checkpoint_rows(adjudication_path, adjudications, disagreement_ids)
            print(
                f"adjudicator {completed_count}/{len(disagreement_ids)} {task_id}",
                flush=True,
            )
    hypothesis_rows = [hypotheses[key] for key in task_order]
    costs = {
        "reader": _provider_cost(
            reader, [row["reader_usage"] for row in hypothesis_rows]
        ),
        "primary_judge": _provider_cost(
            primary, [row["judge_usage"] for row in primary_rows]
        ),
        "independent_judge": _provider_cost(
            independent, [row["judge_usage"] for row in independent_rows]
        ),
        "adjudicator": _provider_cost(
            independent,
            [
                adjudications[task_id]["judge_usage"]
                for task_id in disagreement_ids
                if task_id in adjudications
            ],
        ),
    }
    actual_total = sum(value["estimated_usd_with_reported_cache"] for value in costs.values())
    if actual_total > args.max_api_cost_usd:
        raise RuntimeError(
            f"actual_api_cost_exceeded_cap:{actual_total:.6f}>{args.max_api_cost_usd:.6f}"
        )
    adjudicated_by_id = {
        task_id: (
            bool(primary_by_id[task_id]["correct"])
            if bool(primary_by_id[task_id]["correct"])
            == bool(independent_by_id[task_id]["correct"])
            else bool(adjudications.get(task_id, {}).get("correct"))
        )
        for task_id in task_order
    }
    arms: dict[str, dict] = {}
    evaluated_arms = (
        ("baseline", "candidate", "oracle")
        if args.scope == "full"
        else ("oracle",)
    )
    for arm in evaluated_arms:
        ids = _arm_task_ids(task_order, arm)
        if not ids:
            continue
        primary_labels = [bool(primary_by_id[key]["correct"]) for key in ids]
        independent_labels = [bool(independent_by_id[key]["correct"]) for key in ids]
        by_category: dict[str, list[bool]] = defaultdict(list)
        adjudicated_by_category: dict[str, list[bool]] = defaultdict(list)
        for key in ids:
            category = primary_by_id[key]["category"]
            by_category[category].append(
                bool(primary_by_id[key]["correct"])
                and bool(independent_by_id[key]["correct"])
            )
            adjudicated_by_category[category].append(adjudicated_by_id[key])
        dual = [left and right for left, right in zip(primary_labels, independent_labels)]
        adjudicated = [adjudicated_by_id[key] for key in ids]
        arms[arm] = {
            "question_count": len(ids),
            "primary_accuracy": statistics.fmean(primary_labels),
            "independent_accuracy": statistics.fmean(independent_labels),
            "dual_judge_accuracy": statistics.fmean(dual),
            "dual_judge_correct_count": sum(dual),
            "dual_judge_accuracy_wilson_95": _wilson_interval(sum(dual), len(dual)),
            "adjudicated_accuracy": statistics.fmean(adjudicated),
            "adjudicated_correct_count": sum(adjudicated),
            "adjudicated_accuracy_wilson_95": _wilson_interval(
                sum(adjudicated), len(adjudicated)
            ),
            "dual_judge_accuracy_by_category": {
                category: {
                    "accuracy": statistics.fmean(values),
                    "count": len(values),
                }
                for category, values in sorted(by_category.items())
            },
            "adjudicated_accuracy_by_category": {
                category: {
                    "accuracy": statistics.fmean(values),
                    "count": len(values),
                }
                for category, values in sorted(adjudicated_by_category.items())
            },
        }
    primary_all = [bool(row["correct"]) for row in primary_rows]
    independent_all = [bool(row["correct"]) for row in independent_rows]
    baseline_ids = _arm_task_ids(task_order, "baseline")
    candidate_ids = _arm_task_ids(task_order, "candidate")
    baseline_by_question = {
        key.split(":", 1)[1]: (
            bool(primary_by_id[key]["correct"])
            and bool(independent_by_id[key]["correct"])
        )
        for key in baseline_ids
    }
    candidate_by_question = {
        key.split(":", 1)[1]: (
            bool(primary_by_id[key]["correct"])
            and bool(independent_by_id[key]["correct"])
        )
        for key in candidate_ids
    }
    paired_ids = sorted(set(baseline_by_question) & set(candidate_by_question))
    baseline_adjudicated = {
        key.split(":", 1)[1]: adjudicated_by_id[key] for key in baseline_ids
    }
    candidate_adjudicated = {
        key.split(":", 1)[1]: adjudicated_by_id[key] for key in candidate_ids
    }
    adjudicated_paired_ids = sorted(
        set(baseline_adjudicated) & set(candidate_adjudicated)
    )
    paired_ids = sorted(set(baseline_by_question) & set(candidate_by_question))
    report = {
        "protocol": PROTOCOL,
        "reader_protocol": READER_PROTOCOLS[args.reader_variant],
        "judge_protocol": JUDGE_PROTOCOL,
        "scope": args.scope,
        "arms": arms,
        "paired": {
            "question_count": len(paired_ids),
            "candidate_wins": sum(
                candidate_by_question[key] and not baseline_by_question[key]
                for key in paired_ids
            ),
            "baseline_wins": sum(
                baseline_by_question[key] and not candidate_by_question[key]
                for key in paired_ids
            ),
            "both_correct": sum(
                baseline_by_question[key] and candidate_by_question[key]
                for key in paired_ids
            ),
            "both_incorrect": sum(
                not baseline_by_question[key] and not candidate_by_question[key]
                for key in paired_ids
            ),
            "candidate_accuracy_delta": (
                arms["candidate"]["dual_judge_accuracy"]
                - arms["baseline"]["dual_judge_accuracy"]
                if paired_ids
                else None
            ),
        },
        "adjudicated_paired": {
            "question_count": len(adjudicated_paired_ids),
            "candidate_wins": sum(
                candidate_adjudicated[key] and not baseline_adjudicated[key]
                for key in adjudicated_paired_ids
            ),
            "baseline_wins": sum(
                baseline_adjudicated[key] and not candidate_adjudicated[key]
                for key in adjudicated_paired_ids
            ),
            "both_correct": sum(
                baseline_adjudicated[key] and candidate_adjudicated[key]
                for key in adjudicated_paired_ids
            ),
            "both_incorrect": sum(
                not baseline_adjudicated[key] and not candidate_adjudicated[key]
                for key in adjudicated_paired_ids
            ),
            "candidate_accuracy_delta": (
                arms["candidate"]["adjudicated_accuracy"]
                - arms["baseline"]["adjudicated_accuracy"]
                if adjudicated_paired_ids
                else None
            ),
        },
        "judge_agreement": statistics.fmean(
            left == right for left, right in zip(primary_all, independent_all)
        ),
        "judge_cohen_kappa": _cohen_kappa(primary_all, independent_all),
        "judge_disagreement_count": len(disagreement_ids),
        "adjudication_skipped_due_cost": adjudication_skipped_due_cost,
        "projected_adjudication_cost_usd": projected_adjudication_cost,
        "usage_and_estimated_cost": {**costs, "total_estimated_usd": actual_total},
        "cost_cap_usd": args.max_api_cost_usd,
    }
    (args.output_dir / "api-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    args = parse_args()
    args.output_dir = args.output_dir.resolve()
    retrieval_rows, offline = prepare_retrieval(args)
    preview = cost_preview(args, retrieval_rows)
    output = {"offline": offline, "cost_preview": preview}
    if args.run_api:
        output["api"] = run_api(args, retrieval_rows, preview)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
