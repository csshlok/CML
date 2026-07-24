from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.backend.prepare_atomic_extractor_training_data import (  # noqa: E402
    DEFAULT_PROTECTED,
    _canonical_json,
    _session_hash,
    _walk_objects,
    protected_inventory,
)


PROTOCOL = "atomic-training-teacher-source-sessions-v1"
DEFAULT_REGISTRY = REPO_ROOT / "backend/tests/fixtures/atomic_training_sources.json"
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT / ".tmp/atomic-memory-training-sources/teacher-corpus-v1"
)
DEFAULT_COUNTS = {
    "google-synthetic-persona-chat": 600,
    "multiwoz-2.2": 600,
    "hf-everyday-conversations": 300,
}
_PERSONA_TURN = re.compile(r"^User\s+([12]):\s*(.*)$", re.IGNORECASE)


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    source_row_id: str
    session: dict
    metadata: dict


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify and deterministically sample licensed conversation sources into "
            "an independent, unlabelled teacher-input corpus."
        )
    )
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--source-count",
        action="append",
        default=[],
        metavar="SOURCE_ID=COUNT",
        help="Override a source sample count; may be repeated.",
    )
    parser.add_argument("--minimum-turns", type=int, default=4)
    parser.add_argument("--maximum-characters", type=int, default=16_000)
    parser.add_argument("--sample-seed", type=int, default=20260723)
    parser.add_argument(
        "--protected-manifest",
        type=Path,
        action="append",
        default=[],
        help="Additional artifact whose IDs and session text must be excluded.",
    )
    return parser.parse_args()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _content_hash(session: dict) -> str:
    turns = [
        {
            "role": str(turn.get("role") or "").strip().casefold(),
            "content": " ".join(str(turn.get("content") or "").split()),
        }
        for turn in session.get("turns") or []
    ]
    return _sha256_bytes(_canonical_json(turns).encode("utf-8"))


def _protected_content_hashes(paths: Iterable[Path]) -> set[str]:
    hashes: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in _walk_objects(payload):
            session = item.get("session")
            if isinstance(session, dict) and session.get("turns"):
                hashes.add(_content_hash(session))
            sessions = item.get("haystack_sessions")
            if isinstance(sessions, list):
                for turns in sessions:
                    if isinstance(turns, list):
                        hashes.add(_content_hash({"turns": turns}))
    return hashes


def _normalize_turns(turns: Iterable[dict]) -> list[dict]:
    normalized: list[dict] = []
    for turn in turns:
        role = str(turn.get("role") or "").strip().casefold()
        content = str(turn.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        source_turn_id = str(
            turn.get("source_turn_id")
            if turn.get("source_turn_id") is not None
            else len(normalized)
        )
        normalized.append(
            {
                "role": role,
                "content": content,
                "source_turn_id": source_turn_id,
            }
        )
    return normalized


def parse_persona_conversation(text: str, user_number: int) -> list[dict]:
    turns: list[dict] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _PERSONA_TURN.match(line)
        if match:
            speaker = int(match.group(1))
            turns.append(
                {
                    "role": "user" if speaker == user_number else "assistant",
                    "content": match.group(2).strip(),
                    "source_turn_id": str(len(turns)),
                }
            )
        elif turns:
            turns[-1]["content"] = f"{turns[-1]['content']}\n{line}".strip()
    return _normalize_turns(turns)


def _stable_user_number(source_row_id: str, seed: int) -> int:
    digest = hashlib.sha256(f"{seed}:{source_row_id}".encode("utf-8")).digest()
    return 1 + (digest[0] % 2)


def iter_persona_records(
    path: Path, source_id: str, seed: int
) -> Iterator[SourceRecord]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_index, row in enumerate(reader):
            source_row_id = str(row_index)
            user_number = _stable_user_number(source_row_id, seed)
            turns = parse_persona_conversation(
                str(row.get("Best Generated Conversation") or ""), user_number
            )
            yield SourceRecord(
                source_id=source_id,
                source_row_id=source_row_id,
                session={"date": "", "turns": turns},
                metadata={
                    "mapped_user_number": user_number,
                    "persona_fields_used_as_evidence": False,
                },
            )


def _compact_multiwoz_annotations(turns: dict) -> list[dict]:
    compact: list[dict] = []
    turn_ids = turns.get("turn_id") or []
    speakers = turns.get("speaker") or []
    frames = turns.get("frames") or []
    for index, speaker in enumerate(speakers):
        if int(speaker) != 0 or index >= len(frames):
            continue
        frame = frames[index] or {}
        states = []
        for service, state in zip(
            frame.get("service") or [], frame.get("state") or [], strict=False
        ):
            slots = {}
            slot_values = state.get("slots_values") or {}
            for name, values in zip(
                slot_values.get("slots_values_name") or [],
                slot_values.get("slots_values_list") or [],
                strict=False,
            ):
                slots[str(name)] = [str(value) for value in values]
            states.append(
                {
                    "service": str(service),
                    "active_intent": str(state.get("active_intent") or ""),
                    "requested_slots": [
                        str(value) for value in state.get("requested_slots") or []
                    ],
                    "slots": slots,
                }
            )
        if states:
            compact.append(
                {
                    "source_turn_id": str(
                        turn_ids[index] if index < len(turn_ids) else index
                    ),
                    "states": states,
                }
            )
    return compact


def iter_multiwoz_records(path: Path, source_id: str) -> Iterator[SourceRecord]:
    with path.open("r", encoding="utf-8") as handle:
        for row_index, line in enumerate(handle):
            if not line.strip():
                continue
            payload = json.loads(line)
            source_row_id = str(payload.get("dialogue_id") or row_index)
            packed_turns = payload.get("turns") or {}
            utterances = packed_turns.get("utterance") or []
            speakers = packed_turns.get("speaker") or []
            turn_ids = packed_turns.get("turn_id") or []
            turns = []
            for index, (speaker, utterance) in enumerate(
                zip(speakers, utterances, strict=False)
            ):
                turns.append(
                    {
                        "role": "user" if int(speaker) == 0 else "assistant",
                        "content": str(utterance),
                        "source_turn_id": str(
                            turn_ids[index] if index < len(turn_ids) else index
                        ),
                    }
                )
            yield SourceRecord(
                source_id=source_id,
                source_row_id=source_row_id,
                session={"date": "", "turns": _normalize_turns(turns)},
                metadata={
                    "services": [str(value) for value in payload.get("services") or []],
                    "user_state_annotations": _compact_multiwoz_annotations(
                        packed_turns
                    ),
                    "annotations_are_qa_hints_not_evidence": True,
                },
            )


def iter_everyday_records(path: Path, source_id: str) -> Iterator[SourceRecord]:
    try:
        import pyarrow.parquet as parquet
    except ImportError as exc:  # pragma: no cover - environment failure
        raise RuntimeError(
            "pyarrow is required to read the approved Parquet source"
        ) from exc

    table = parquet.read_table(path)
    for row_index, payload in enumerate(table.to_pylist()):
        turns = _normalize_turns(payload.get("messages") or [])
        yield SourceRecord(
            source_id=source_id,
            source_row_id=str(row_index),
            session={"date": "", "turns": turns},
            metadata={
                "topic": str(payload.get("topic") or ""),
                "subtopic": str(payload.get("subtopic") or ""),
                "subsubtopic": str(payload.get("subsubtopic") or ""),
                "synthetic_source_token_length": payload.get("token_length"),
            },
        )


def _parse_counts(overrides: list[str]) -> dict[str, int]:
    counts = dict(DEFAULT_COUNTS)
    for override in overrides:
        source_id, separator, raw_count = override.partition("=")
        if not separator or source_id not in counts:
            raise ValueError(
                f"Expected one of {sorted(counts)} as SOURCE_ID=COUNT; got {override!r}"
            )
        count = int(raw_count)
        if count < 1:
            raise ValueError("Source counts must be positive")
        counts[source_id] = count
    return counts


def _source_data_path(source: dict) -> Path:
    candidates = [
        REPO_ROOT / item["path"]
        for item in source["files"]
        if not str(item["path"]).casefold().endswith("readme.md")
    ]
    if len(candidates) != 1:
        raise ValueError(
            f"{source['source_id']} must declare exactly one non-README data file"
        )
    return candidates[0]


def _verify_registry(registry: dict) -> list[dict]:
    if registry.get("policy", {}).get("requires_teacher_labels") is not True:
        raise ValueError("Registry must require independent teacher labels")
    if registry.get("policy", {}).get("may_train_directly_from_raw_sources") is not False:
        raise ValueError("Registry must forbid direct training from raw sources")

    verified: list[dict] = []
    for source in registry.get("approved_sources") or []:
        for expected in source.get("files") or []:
            path = REPO_ROOT / expected["path"]
            if not path.is_file():
                raise FileNotFoundError(path)
            actual_bytes = path.stat().st_size
            actual_sha256 = _sha256_file(path)
            if actual_bytes != int(expected["bytes"]):
                raise ValueError(f"Byte-size mismatch for {path}")
            if actual_sha256 != expected["sha256"]:
                raise ValueError(f"SHA-256 mismatch for {path}")
        verified.append(source)
    return verified


def _iter_source(source: dict, seed: int) -> Iterator[SourceRecord]:
    source_id = str(source["source_id"])
    path = _source_data_path(source)
    if source_id == "google-synthetic-persona-chat":
        return iter_persona_records(path, source_id, seed)
    if source_id == "multiwoz-2.2":
        return iter_multiwoz_records(path, source_id)
    if source_id == "hf-everyday-conversations":
        return iter_everyday_records(path, source_id)
    raise ValueError(f"No parser exists for approved source {source_id!r}")


def _sample_key(record: SourceRecord, seed: int) -> str:
    return hashlib.sha256(
        f"{seed}:{record.source_id}:{record.source_row_id}".encode("utf-8")
    ).hexdigest()


def select_records(
    records: Iterable[SourceRecord],
    *,
    count: int,
    seed: int,
    minimum_turns: int,
    maximum_characters: int,
    protected_ids: set[str],
    protected_session_hashes: set[str],
    protected_content_hashes: set[str],
    seen_content_hashes: set[str],
) -> tuple[list[SourceRecord], Counter]:
    eligible: list[tuple[str, SourceRecord]] = []
    stats: Counter = Counter()
    for record in records:
        stats["rows_seen"] += 1
        session = record.session
        turns = session.get("turns") or []
        if len(turns) < minimum_turns:
            stats["too_few_turns"] += 1
            continue
        character_count = sum(len(str(turn.get("content") or "")) for turn in turns)
        if character_count > maximum_characters:
            stats["too_many_characters"] += 1
            continue
        if record.source_row_id.casefold() in protected_ids:
            stats["protected_id_overlap"] += 1
            continue
        session_hash = _session_hash(session)
        content_hash = _content_hash(session)
        if (
            session_hash in protected_session_hashes
            or content_hash in protected_content_hashes
        ):
            stats["protected_content_overlap"] += 1
            continue
        if content_hash in seen_content_hashes:
            stats["duplicate_content"] += 1
            continue
        seen_content_hashes.add(content_hash)
        eligible.append((_sample_key(record, seed), record))

    eligible.sort(key=lambda item: item[0])
    selected = [record for _, record in eligible[:count]]
    stats["eligible"] = len(eligible)
    stats["selected"] = len(selected)
    if len(selected) != count:
        raise ValueError(
            f"Requested {count} records from {selected[0].source_id if selected else 'source'}, "
            f"but only {len(selected)} passed validation"
        )
    return selected, stats


def _write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def main() -> int:
    args = parse_args()
    counts = _parse_counts(args.source_count)
    registry_path = args.registry.resolve()
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    sources = _verify_registry(registry)
    source_by_id = {str(source["source_id"]): source for source in sources}
    if set(counts) != set(source_by_id):
        raise ValueError(
            "Default/overridden source IDs must exactly match approved registry sources"
        )

    protected_paths = [*DEFAULT_PROTECTED, *args.protected_manifest]
    protected_ids, protected_session_hashes = protected_inventory(protected_paths)
    protected_content_hashes = _protected_content_hashes(protected_paths)
    seen_content_hashes: set[str] = set()
    selected: list[SourceRecord] = []
    source_stats: dict[str, dict] = {}

    for source_id in counts:
        source_records, stats = select_records(
            _iter_source(source_by_id[source_id], args.sample_seed),
            count=counts[source_id],
            seed=args.sample_seed,
            minimum_turns=args.minimum_turns,
            maximum_characters=args.maximum_characters,
            protected_ids=protected_ids,
            protected_session_hashes=protected_session_hashes,
            protected_content_hashes=protected_content_hashes,
            seen_content_hashes=seen_content_hashes,
        )
        selected.extend(source_records)
        source_stats[source_id] = dict(sorted(stats.items()))

    selected.sort(key=lambda record: (record.source_id, record.source_row_id))
    output_rows = []
    total_characters = 0
    for record in selected:
        source = source_by_id[record.source_id]
        session_id = (
            f"hf-{record.source_id}-"
            f"{hashlib.sha256(record.source_row_id.encode('utf-8')).hexdigest()[:16]}"
        )
        session = {**record.session, "session_id": session_id}
        character_count = sum(
            len(str(turn.get("content") or "")) for turn in session["turns"]
        )
        total_characters += character_count
        output_rows.append(
            {
                "record_id": session_id,
                "source_id": record.source_id,
                "source_row_id": record.source_row_id,
                "source_repo_id": source["repo_id"],
                "source_uri": source["source_uri"],
                "source_revision": source["revision"],
                "source_license": source["license"],
                "source_license_uri": source["license_uri"],
                "source_split": source["split"],
                "session": session,
                "metadata": record.metadata,
                "teacher_status": "unlabelled",
                "teacher_requirements": {
                    "exact_dialogue_citations_only": True,
                    "ignore_metadata_as_evidence": True,
                    "two_pass_schema": True,
                },
            }
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    sessions_path = args.output_dir / "source-sessions.jsonl"
    _write_jsonl(sessions_path, output_rows)
    output_sha256 = _sha256_file(sessions_path)
    manifest = {
        "protocol": PROTOCOL,
        "status": "teacher_input_ready_not_training_ready",
        "registry_path": str(registry_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "registry_sha256": _sha256_file(registry_path),
        "sample_seed": args.sample_seed,
        "minimum_turns": args.minimum_turns,
        "maximum_characters": args.maximum_characters,
        "requested_counts": counts,
        "source_stats": source_stats,
        "record_count": len(output_rows),
        "total_dialogue_characters": total_characters,
        "estimated_dialogue_tokens": math.ceil(total_characters / 4),
        "token_estimate_method": "ceil(dialogue_characters/4); prompts and outputs excluded",
        "protected_artifacts": [
            {
                "path": str(path.resolve().relative_to(REPO_ROOT)).replace("\\", "/"),
                "sha256": _sha256_file(path),
            }
            for path in protected_paths
            if path.exists()
        ],
        "protected_id_overlap_count": sum(
            stats.get("protected_id_overlap", 0) for stats in source_stats.values()
        ),
        "protected_content_overlap_count": sum(
            stats.get("protected_content_overlap", 0)
            for stats in source_stats.values()
        ),
        "duplicate_content_count": sum(
            stats.get("duplicate_content", 0) for stats in source_stats.values()
        ),
        "output": {
            "path": str(sessions_path.resolve().relative_to(REPO_ROOT)).replace(
                "\\", "/"
            ),
            "bytes": sessions_path.stat().st_size,
            "sha256": output_sha256,
        },
        "training_guard": (
            "These records contain source sessions only. They must not be passed to "
            "QLoRA until independent teacher evidence and proposition targets have "
            "been generated and validated."
        ),
    }
    manifest_path = args.output_dir / "source-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
