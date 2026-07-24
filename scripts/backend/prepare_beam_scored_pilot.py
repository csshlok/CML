from __future__ import annotations

import argparse
import ast
import hashlib
import json
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq


PROTOCOL = "beam-vault-scored-pilot-v1"
QUESTION_CATEGORIES = (
    "abstention",
    "contradiction_resolution",
    "event_ordering",
    "information_extraction",
    "instruction_following",
    "knowledge_update",
    "multi_session_reasoning",
    "preference_following",
    "summarization",
    "temporal_reasoning",
)
ANSWER_FIELDS = {
    "abstention": "ideal_response",
    "contradiction_resolution": "ideal_answer",
    "event_ordering": "answer",
    "information_extraction": "answer",
    "instruction_following": "expected_compliance",
    "knowledge_update": "answer",
    "multi_session_reasoning": "answer",
    "preference_following": "expected_compliance",
    "summarization": "ideal_summary",
    "temporal_reasoning": "answer",
}


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def select_pilot_conversations(
    development_ids: list[str], *, count: int = 5
) -> list[str]:
    if count < 1 or count > len(development_ids):
        raise ValueError("invalid_pilot_conversation_count")
    return sorted(
        development_ids,
        key=lambda value: _sha256(f"beam-scored-pilot-v1:{value}".encode()),
    )[:count]


def _source_ids(item: dict) -> list[int]:
    def flatten(value: object) -> list[object]:
        if isinstance(value, dict):
            return [item for group in value.values() for item in flatten(group)]
        if isinstance(value, (list, tuple, set)):
            return [item for group in value for item in flatten(group)]
        return [value]

    values = flatten(item.get("source_chat_ids") or [])
    return sorted({int(value) for value in values})


def normalize_questions(row: dict) -> list[dict]:
    conversation_id = str(row["conversation_id"])
    payload = ast.literal_eval(str(row["probing_questions"]))
    if set(payload) != set(QUESTION_CATEGORIES):
        raise ValueError(f"unexpected_beam_categories:{conversation_id}")
    normalized: list[dict] = []
    for category in QUESTION_CATEGORIES:
        items = payload[category]
        if len(items) != 2:
            raise ValueError(
                f"beam_pilot_requires_two_questions_per_category:{conversation_id}:{category}"
            )
        for index, item in enumerate(items):
            answer = str(item.get(ANSWER_FIELDS[category]) or "").strip()
            rubric = [str(value).strip() for value in item.get("rubric") or []]
            if not answer or not rubric:
                raise ValueError(
                    f"beam_question_missing_gold:{conversation_id}:{category}:{index}"
                )
            normalized.append(
                {
                    "question_id": f"beam-100k-{conversation_id}-{category}-{index + 1}",
                    "conversation_id": conversation_id,
                    "category": category,
                    "difficulty": str(item.get("difficulty") or ""),
                    "question": str(item["question"]).strip(),
                    "answer": answer,
                    "rubric": rubric,
                    "source_chat_ids": _source_ids(item),
                    "is_abstention": category == "abstention",
                }
            )
    return normalized


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Freeze a balanced BEAM development-only scored pilot."
    )
    parser.add_argument("--parquet", type=Path, required=True)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--development-windows", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--conversation-count", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    split_manifest = json.loads(args.split_manifest.read_text(encoding="utf-8"))
    selected_ids = select_pilot_conversations(
        [str(value) for value in split_manifest["development"]],
        count=args.conversation_count,
    )
    rows = pq.read_table(args.parquet).to_pylist()
    rows_by_id = {str(row["conversation_id"]): row for row in rows}
    questions = [
        question
        for conversation_id in selected_ids
        for question in normalize_questions(rows_by_id[conversation_id])
    ]
    expected_question_count = len(selected_ids) * len(QUESTION_CATEGORIES) * 2
    if len(questions) != expected_question_count:
        raise ValueError("unexpected_pilot_question_count")
    category_counts = Counter(question["category"] for question in questions)
    if len(set(category_counts.values())) != 1:
        raise ValueError("pilot_is_not_category_balanced")

    pilot_windows = [
        json.loads(line)
        for line in args.development_windows.read_text(encoding="utf-8").splitlines()
        if line.strip()
        and str(json.loads(line)["conversation_id"]) in set(selected_ids)
    ]
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    questions_path = output_dir / "questions.jsonl"
    windows_path = output_dir / "extraction-windows.jsonl"
    questions_payload = b"".join(_canonical_json(row) + b"\n" for row in questions)
    windows_payload = b"".join(_canonical_json(row) + b"\n" for row in pilot_windows)
    questions_path.write_bytes(questions_payload)
    windows_path.write_bytes(windows_payload)

    manifest = {
        "protocol": PROTOCOL,
        "source_sha256": _file_sha256(args.parquet),
        "split_manifest_sha256": _file_sha256(args.split_manifest),
        "development_windows_sha256": _file_sha256(args.development_windows),
        "selection_namespace": "beam-scored-pilot-v1",
        "selection_unit": "whole_development_conversation",
        "evaluation_role": "development",
        "selection_mode": "diagnostic",
        "selected_conversation_ids": selected_ids,
        "selected_conversation_count": len(selected_ids),
        "question_count": len(questions),
        "question_category_counts": dict(sorted(category_counts.items())),
        "questions_file": questions_path.name,
        "questions_sha256": _sha256(questions_payload),
        "extraction_windows_file": windows_path.name,
        "extraction_window_count": len(pilot_windows),
        "extraction_windows_sha256": _sha256(windows_payload),
        "validation_conversations_used": False,
        "sealed_test_conversations_used": False,
        "gates": {
            "minimum_schema_rate": 0.98,
            "maximum_truncation_rate": 0.0,
            "maximum_normalized_citation_issue_count": 0,
            "maximum_compiler_rejection_rate": 0.01,
            "minimum_dual_judge_agreement": 0.90,
            "maximum_api_cost_usd": 2.50,
            "maximum_candidate_overall_regression": 0.03,
        },
    }
    manifest["manifest_sha256"] = _sha256(_canonical_json(manifest))
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
