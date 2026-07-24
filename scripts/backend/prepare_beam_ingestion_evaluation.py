from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Iterable

import pyarrow.parquet as pq


PROTOCOL = "beam-ingestion-evaluation-v3-role-scoped-nonoverlap"
DEFAULT_NAMESPACE = "vault-beam-100k-v1"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def deterministic_split(
    conversation_ids: Iterable[str],
    *,
    namespace: str = DEFAULT_NAMESPACE,
    development_count: int = 10,
    validation_count: int = 4,
) -> dict[str, list[str]]:
    raw_identifiers = [str(item) for item in conversation_ids]
    identifiers = sorted(set(raw_identifiers))
    if len(identifiers) != len(raw_identifiers):
        raise ValueError("conversation_ids_must_be_unique")
    if development_count <= 0 or validation_count <= 0:
        raise ValueError("development_and_validation_counts_must_be_positive")
    if development_count + validation_count >= len(identifiers):
        raise ValueError("split_counts_leave_no_sealed_test_conversations")
    ranked = sorted(
        identifiers,
        key=lambda item: _sha256_bytes(f"{namespace}:{item}".encode("utf-8")),
    )
    development_end = development_count
    validation_end = development_end + validation_count
    return {
        "development": sorted(ranked[:development_end]),
        "validation": sorted(ranked[development_end:validation_end]),
        "sealed_test": sorted(ranked[validation_end:]),
    }


def _split_turn(turn: dict, *, max_chars: int) -> list[dict]:
    content = str(turn["content"])
    if max_chars < 256:
        raise ValueError("max_chars_must_be_at_least_256")
    pieces: list[dict] = []
    start = 0
    while start < len(content):
        hard_end = min(len(content), start + max_chars)
        end = hard_end
        if hard_end < len(content):
            minimum_end = start + int(max_chars * 0.6)
            candidates = [
                content.rfind(boundary, minimum_end, hard_end)
                for boundary in ("\n\n", "\n", ". ", " ")
            ]
            usable = [position for position in candidates if position >= minimum_end]
            if usable:
                end = max(usable) + 1
        piece = dict(turn)
        piece["content"] = content[start:end]
        piece["source_char_start"] = start
        piece["source_char_end"] = end
        pieces.append(piece)
        start = end
    return pieces


def _window_turns(
    turns: list[dict],
    *,
    window_turns: int,
    overlap_turns: int,
    max_window_chars: int,
) -> Iterable[tuple[int, list[dict]]]:
    if window_turns < 2:
        raise ValueError("window_turns_must_be_at_least_two")
    if overlap_turns < 0 or overlap_turns >= window_turns:
        raise ValueError("overlap_turns_must_be_nonnegative_and_less_than_window_turns")
    if max_window_chars < 512:
        raise ValueError("max_window_chars_must_be_at_least_512")
    start = 0
    while start < len(turns):
        window: list[dict] = []
        char_count = 0
        end = start
        while end < len(turns) and len(window) < window_turns:
            candidate_chars = len(str(turns[end]["content"]))
            if window and char_count + candidate_chars > max_window_chars:
                break
            window.append(turns[end])
            char_count += candidate_chars
            end += 1
        yield start, window
        if end >= len(turns):
            break
        start = max(start + 1, end - min(overlap_turns, len(window) - 1))


def conversation_windows(
    row: dict,
    *,
    source_split: str,
    window_turns: int = 6,
    overlap_turns: int = 0,
    max_window_chars: int = 12_000,
    included_roles: set[str] | None = None,
) -> list[dict]:
    conversation_id = str(row["conversation_id"])
    roles = included_roles or {"user", "assistant"}
    if not roles or not roles.issubset({"user", "assistant", "tool"}):
        raise ValueError("included_roles_must_be_supported_and_nonempty")
    windows: list[dict] = []
    for batch_index, batch in enumerate(row["chat"]):
        normalized_turns = [
            piece
            for turn in batch
            if str(turn.get("role") or "") in roles
            and str(turn.get("content") or "").strip()
            for piece in _split_turn(
                {
                    "role": str(turn["role"]),
                    "content": str(turn["content"]),
                    "source_turn_id": int(turn["id"]),
                    "source_index": str(turn["index"]),
                    "time_anchor": str(turn.get("time_anchor") or ""),
                },
                max_chars=max_window_chars,
            )
        ]
        for start, turns in _window_turns(
            normalized_turns,
            window_turns=window_turns,
            overlap_turns=overlap_turns,
            max_window_chars=max_window_chars,
        ):
            window_id = (
                f"beam-{source_split.lower()}-{conversation_id}-"
                f"b{batch_index:02d}-t{start:05d}"
            )
            source_payload = {
                "conversation_id": conversation_id,
                "batch_index": batch_index,
                "turns": turns,
            }
            windows.append(
                {
                    "window_id": window_id,
                    "conversation_id": conversation_id,
                    "source_split": source_split,
                    "batch_index": batch_index,
                    "window_start": start,
                    "date": turns[0]["time_anchor"],
                    "turns": [
                        {"role": turn["role"], "content": turn["content"]}
                        for turn in turns
                    ],
                    "source_slices": [
                        {
                            "source_turn_id": turn["source_turn_id"],
                            "source_index": turn["source_index"],
                            "source_char_start": turn["source_char_start"],
                            "source_char_end": turn["source_char_end"],
                        }
                        for turn in turns
                    ],
                    "source_content_sha256": _sha256_bytes(
                        _canonical_json(source_payload)
                    ),
                }
            )
    return windows


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Iterable[dict]) -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            encoded = _canonical_json(row)
            handle.write(encoded.decode("utf-8") + "\n")
            digest.update(encoded + b"\n")
            count += 1
    return count, digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze BEAM conversation splits and materialize development/validation "
            "ingestion windows without exposing sealed-test content."
        )
    )
    parser.add_argument("--parquet", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-split", default="100K")
    parser.add_argument("--source-uri", required=True)
    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    parser.add_argument("--development-count", type=int, default=10)
    parser.add_argument("--validation-count", type=int, default=4)
    parser.add_argument("--window-turns", type=int, default=6)
    parser.add_argument("--overlap-turns", type=int, default=0)
    parser.add_argument("--max-window-chars", type=int, default=12_000)
    parser.add_argument(
        "--included-role",
        action="append",
        choices=("user", "assistant", "tool"),
        default=[],
        help="Role materialized for extraction; repeat as needed. Defaults to every supported role.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    parquet_path = args.parquet.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    table = pq.read_table(parquet_path)
    rows = table.to_pylist()
    conversation_ids = [str(row["conversation_id"]) for row in rows]
    splits = deterministic_split(
        conversation_ids,
        namespace=args.namespace,
        development_count=args.development_count,
        validation_count=args.validation_count,
    )
    rows_by_id = {str(row["conversation_id"]): row for row in rows}
    included_roles = set(args.included_role or ["user", "assistant", "tool"])

    source_sha256 = _file_sha256(parquet_path)
    snapshot = {
        "protocol": PROTOCOL,
        "dataset": "Mohammadta/BEAM",
        "config": "default",
        "source_split": args.source_split,
        "source_uri": args.source_uri,
        "source_file": parquet_path.name,
        "source_bytes": parquet_path.stat().st_size,
        "source_sha256": source_sha256,
        "conversation_count": len(conversation_ids),
        "schema": str(table.schema),
        "included_roles": sorted(included_roles),
    }
    _write_json(output_dir / "snapshot.json", snapshot)

    split_manifest = {
        "protocol": PROTOCOL,
        "namespace": args.namespace,
        "source_sha256": source_sha256,
        "assignment_unit": "whole_conversation",
        "extraction_role_scope": sorted(included_roles),
        "development": splits["development"],
        "validation": splits["validation"],
        "sealed_test": splits["sealed_test"],
        "sealed_test_policy": (
            "IDs and fingerprints only; content is not materialized by this command"
        ),
    }
    split_manifest["manifest_sha256"] = _sha256_bytes(
        _canonical_json(split_manifest)
    )
    _write_json(output_dir / "split-manifest.json", split_manifest)

    window_outputs: dict[str, dict] = {}
    for split_name in ("development", "validation"):
        windows = [
            window
            for conversation_id in splits[split_name]
            for window in conversation_windows(
                rows_by_id[conversation_id],
                source_split=args.source_split,
                window_turns=args.window_turns,
                overlap_turns=args.overlap_turns,
                max_window_chars=args.max_window_chars,
                included_roles=included_roles,
            )
        ]
        path = output_dir / f"{split_name}-windows.jsonl"
        count, sha256 = _write_jsonl(path, windows)
        window_outputs[split_name] = {
            "file": path.name,
            "window_count": count,
            "sha256": sha256,
        }

    sealed_fingerprints = {
        conversation_id: _sha256_bytes(
            _canonical_json(
                {
                    "conversation_id": conversation_id,
                    "chat": rows_by_id[conversation_id]["chat"],
                }
            )
        )
        for conversation_id in splits["sealed_test"]
    }
    _write_json(
        output_dir / "sealed-test-fingerprints.json",
        {
            "protocol": PROTOCOL,
            "source_sha256": source_sha256,
            "conversation_fingerprints": sealed_fingerprints,
        },
    )
    _write_json(
        output_dir / "window-manifest.json",
        {
            "protocol": PROTOCOL,
            "source_sha256": source_sha256,
            "window_turns": args.window_turns,
            "overlap_turns": args.overlap_turns,
            "max_window_chars": args.max_window_chars,
            "included_roles": sorted(included_roles),
            "outputs": window_outputs,
            "sealed_test_materialized": False,
        },
    )

    print(
        json.dumps(
            {
                "snapshot": snapshot,
                "split_manifest": split_manifest,
                "windows": window_outputs,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
