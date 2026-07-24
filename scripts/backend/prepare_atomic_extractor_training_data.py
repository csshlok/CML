from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.atomic_memory_v2 import (  # noqa: E402
    AtomicMemoryV2EvidencePassResponse,
    AtomicMemoryV2PropositionPassResponse,
    atomic_memory_v2_evidence_pass_prompt,
    atomic_memory_v2_proposition_pass_prompt,
)


PROTOCOL = "atomic-extractor-independent-training-corpus-v1"
FORBIDDEN_SOURCES = ("beam", "locomo", "longmemeval")
DEFAULT_PROTECTED = (
    REPO_ROOT / "backend/tests/fixtures/atomic_memory_v2_extraction.json",
    REPO_ROOT / "backend/tests/fixtures/atomic_memory_v2_holdout.json",
    REPO_ROOT / "backend/tests/fixtures/beam_verified_oracle_v1.json",
)


class CorpusProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_name: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    license: str = Field(min_length=1)
    teacher_model: str = Field(min_length=1)
    teacher_provider: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    paid_cost_usd: float = Field(default=0.0, ge=0.0)
    source_uri: str | None = None
    generation_recipe_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )


class TrainingRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(min_length=1)
    split_group: str = Field(min_length=1)
    session: dict
    evidence_target: AtomicMemoryV2EvidencePassResponse
    proposition_target: AtomicMemoryV2PropositionPassResponse


class TrainingCorpus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corpus_version: str = Field(min_length=1)
    evaluation_role: Literal["training"]
    provenance: CorpusProvenance
    records: list[TrainingRecord] = Field(min_length=1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate an independent teacher-labelled corpus and emit deterministic "
            "evidence/proposition SFT splits."
        )
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--protected-manifest",
        type=Path,
        action="append",
        default=[],
        help="Additional evaluation artifact whose IDs and source text are forbidden.",
    )
    parser.add_argument("--validation-percent", type=int, default=10)
    parser.add_argument("--split-seed", type=int, default=20260723)
    parser.add_argument("--minimum-records", type=int, default=1000)
    parser.add_argument(
        "--allow-small-corpus",
        action="store_true",
        help="Permit pipeline smoke tests; resulting manifest is never training-ready.",
    )
    return parser.parse_args()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _session_hash(session: dict) -> str:
    stable = {
        "date": str(session.get("date") or ""),
        "turns": [
            {
                "role": str(turn.get("role") or ""),
                "content": str(turn.get("content") or ""),
            }
            for turn in session.get("turns") or []
        ],
    }
    return _sha256_text(_canonical_json(stable))


def _walk_objects(value: object):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk_objects(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_objects(nested)


def protected_inventory(paths: list[Path]) -> tuple[set[str], set[str]]:
    ids: set[str] = set()
    session_hashes: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in _walk_objects(payload):
            for key in ("id", "record_id", "question_id"):
                if item.get(key):
                    ids.add(str(item[key]).casefold())
            session = item.get("session")
            if isinstance(session, dict) and session.get("turns"):
                session_hashes.add(_session_hash(session))
            if item.get("haystack_sessions"):
                for index, turns in enumerate(item["haystack_sessions"]):
                    session_hashes.add(
                        _session_hash(
                            {
                                "date": (item.get("haystack_dates") or [""])[index],
                                "turns": turns,
                            }
                        )
                    )
    return ids, session_hashes


def _validate_session(record: TrainingRecord) -> list[str]:
    errors: list[str] = []
    session = record.session
    session_id = str(session.get("session_id") or "")
    turns = session.get("turns")
    if not session_id or not isinstance(turns, list) or not turns:
        return ["session_requires_id_and_nonempty_turns"]
    if record.evidence_target.session_id != session_id:
        errors.append("evidence_session_id_mismatch")
    if record.proposition_target.session_id != session_id:
        errors.append("proposition_session_id_mismatch")

    span_ids: set[str] = set()
    memories: set[str] = set()
    for span in record.evidence_target.spans:
        if span.span_id in span_ids:
            errors.append("duplicate_span_id")
        span_ids.add(span.span_id)
        normalized_memory = " ".join(span.memory_text.casefold().split())
        if normalized_memory in memories:
            errors.append("duplicate_evidence_memory")
        memories.add(normalized_memory)
        citation = span.citation
        if citation.turn_index >= len(turns):
            errors.append("citation_turn_out_of_range")
            continue
        turn = turns[citation.turn_index]
        content = str(turn.get("content") or "")
        if citation.excerpt not in content:
            errors.append("citation_excerpt_not_exact")
        if citation.start_char is not None and citation.end_char is not None:
            if content[citation.start_char : citation.end_char] != citation.excerpt:
                errors.append("citation_offsets_not_exact")
        expected_turn_id = turn.get("source_turn_id")
        if (
            citation.source_turn_id is not None
            and expected_turn_id is not None
            and citation.source_turn_id != expected_turn_id
        ):
            errors.append("source_turn_id_mismatch")

    proposition_ids: set[str] = set()
    proposition_memories: set[str] = set()
    represented_spans: set[str] = set()
    for proposition in record.proposition_target.propositions:
        if proposition.proposition_id in proposition_ids:
            errors.append("duplicate_proposition_id")
        proposition_ids.add(proposition.proposition_id)
        normalized_memory = " ".join(proposition.memory_text.casefold().split())
        if normalized_memory in proposition_memories:
            errors.append("duplicate_proposition_memory")
        proposition_memories.add(normalized_memory)
        if proposition.evidence_span_id is not None:
            if proposition.evidence_span_id not in span_ids:
                errors.append("unknown_evidence_span_id")
            represented_spans.add(proposition.evidence_span_id)
    missing = span_ids - represented_spans
    if missing:
        errors.append("unrepresented_evidence_span")
    return errors


def _split_for(group: str, seed: int, validation_percent: int) -> str:
    digest = hashlib.sha256(f"{seed}:{group}".encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big") % 100
    return "validation" if bucket < validation_percent else "train"


def _sft_rows(record: TrainingRecord) -> list[dict]:
    session = record.session
    evidence = record.evidence_target
    return [
        {
            "record_id": record.record_id,
            "pass": "evidence",
            "messages": [
                {"role": "user", "content": atomic_memory_v2_evidence_pass_prompt(session)},
                {
                    "role": "assistant",
                    "content": json.dumps(
                        evidence.model_dump(mode="json"),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            ],
        },
        {
            "record_id": record.record_id,
            "pass": "proposition",
            "messages": [
                {
                    "role": "user",
                    "content": atomic_memory_v2_proposition_pass_prompt(
                        session, evidence.spans
                    ),
                },
                {
                    "role": "assistant",
                    "content": json.dumps(
                        record.proposition_target.model_dump(mode="json"),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            ],
        },
    ]


def prepare_corpus(
    payload: dict,
    *,
    protected_paths: list[Path],
    validation_percent: int,
    split_seed: int,
    minimum_records: int,
    allow_small_corpus: bool,
) -> tuple[dict[str, list[dict]], dict]:
    corpus = TrainingCorpus.model_validate(payload)
    provenance_text = " ".join(
        (
            corpus.provenance.source_name,
            corpus.provenance.source_version,
            corpus.provenance.source_uri or "",
        )
    ).casefold()
    if any(forbidden in provenance_text for forbidden in FORBIDDEN_SOURCES):
        raise ValueError("benchmark_derived_training_source_forbidden")
    if not 1 <= validation_percent <= 50:
        raise ValueError("validation_percent_must_be_between_1_and_50")

    protected_ids, protected_hashes = protected_inventory(protected_paths)
    seen_ids: set[str] = set()
    seen_sessions: set[str] = set()
    rejected: list[dict] = []
    accepted: list[TrainingRecord] = []
    for record in corpus.records:
        reasons = _validate_session(record)
        record_key = record.record_id.casefold()
        session_digest = _session_hash(record.session)
        if record_key in seen_ids:
            reasons.append("duplicate_record_id")
        if session_digest in seen_sessions:
            reasons.append("duplicate_session_content")
        if record_key in protected_ids:
            reasons.append("protected_evaluation_id_overlap")
        if session_digest in protected_hashes:
            reasons.append("protected_evaluation_content_overlap")
        seen_ids.add(record_key)
        seen_sessions.add(session_digest)
        if reasons:
            rejected.append(
                {"record_id": record.record_id, "reasons": sorted(set(reasons))}
            )
        else:
            accepted.append(record)
    if rejected:
        raise ValueError(
            "training_corpus_quality_or_leakage_failure:"
            + _canonical_json(rejected[:20])
        )
    if len(accepted) < minimum_records and not allow_small_corpus:
        raise ValueError(
            f"training_corpus_too_small:{len(accepted)}<{minimum_records}"
        )

    outputs: dict[str, list[dict]] = {"train": [], "validation": []}
    record_split_counts: Counter[str] = Counter()
    pass_counts: Counter[str] = Counter()
    for record in sorted(accepted, key=lambda item: item.record_id):
        split = _split_for(record.split_group, split_seed, validation_percent)
        record_split_counts[split] += 1
        for row in _sft_rows(record):
            outputs[split].append(row)
            pass_counts[row["pass"]] += 1
    if not outputs["train"] or not outputs["validation"]:
        raise ValueError("deterministic_split_requires_nonempty_train_and_validation")

    audit = {
        "protocol": PROTOCOL,
        "corpus_version": corpus.corpus_version,
        "evaluation_role": corpus.evaluation_role,
        "provenance": corpus.provenance.model_dump(mode="json"),
        "record_count": len(accepted),
        "record_split_counts": dict(record_split_counts),
        "sft_example_count": sum(len(rows) for rows in outputs.values()),
        "pass_counts": dict(pass_counts),
        "protected_manifest_count": len(protected_paths),
        "protected_id_count": len(protected_ids),
        "protected_session_hash_count": len(protected_hashes),
        "leakage_rejection_count": 0,
        "quality_rejection_count": 0,
        "minimum_records": minimum_records,
        "training_ready": len(accepted) >= minimum_records,
        "split_seed": split_seed,
        "validation_percent": validation_percent,
    }
    return outputs, audit


def _write_jsonl(path: Path, rows: list[dict]) -> str:
    content = "".join(_canonical_json(row) + "\n" for row in rows)
    path.write_text(content, encoding="utf-8")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def main() -> int:
    args = parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    protected_paths = [*DEFAULT_PROTECTED, *args.protected_manifest]
    try:
        outputs, audit = prepare_corpus(
            payload,
            protected_paths=protected_paths,
            validation_percent=args.validation_percent,
            split_seed=args.split_seed,
            minimum_records=args.minimum_records,
            allow_small_corpus=args.allow_small_corpus,
        )
    except (ValidationError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    args.output_dir.mkdir(parents=True, exist_ok=True)
    hashes = {
        split: _write_jsonl(args.output_dir / f"{split}.jsonl", rows)
        for split, rows in outputs.items()
    }
    input_hash = hashlib.sha256(args.input.read_bytes()).hexdigest()
    manifest = {
        **audit,
        "input_sha256": input_hash,
        "output_sha256": hashes,
        "protected_manifests": [
            {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in protected_paths
            if path.exists()
        ],
    }
    (args.output_dir / "training-data-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2))
    return 0 if manifest["training_ready"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
