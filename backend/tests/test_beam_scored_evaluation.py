from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from scripts.backend.run_beam_scored_evaluation import (
    _arm_task_ids,
    _atomic_duplicates_raw,
    _atomic_utility_reason,
    _pack,
    _pack_candidate,
    _parse_structured_verdict,
    _question_shape,
    _rank,
    _split_content,
    _split_content_with_offsets,
)


def test_empty_optional_arm_is_excluded_from_report_aggregation() -> None:
    tasks = ["baseline:q1", "candidate:q1"]

    assert _arm_task_ids(tasks, "baseline") == ["baseline:q1"]
    assert _arm_task_ids(tasks, "candidate") == ["candidate:q1"]
    assert _arm_task_ids(tasks, "oracle") == []


def test_raw_content_split_is_lossless_and_bounded() -> None:
    content = "first sentence. " + ("x" * 900) + "\n\n" + ("y" * 900)

    pieces = _split_content(content, 700)

    assert "".join(pieces) == content
    assert all(len(piece) <= 700 for piece in pieces)
    assert _split_content_with_offsets(content, 700) == [
        (piece, sum(len(value) for value in pieces[:index]), sum(len(value) for value in pieces[: index + 1]))
        for index, piece in enumerate(pieces)
    ]


def test_rank_uses_vault_hybrid_weights_and_atomic_source_class() -> None:
    documents = [
        {
            "doc_id": "raw",
            "kind": "raw",
            "source_type": "external_transcript",
            "text": "alpha unrelated",
        },
        {
            "doc_id": "atomic",
            "kind": "atomic",
            "source_type": "document",
            "text": "alpha answer",
        },
    ]
    vectors = np.asarray([[1.0, 0.0], [1.0, 0.0]], dtype="float32")

    ranked = _rank("alpha", documents, vectors, np.asarray([1.0, 0.0]))

    assert ranked[0]["doc_id"] == "atomic"
    assert ranked[0]["combined_score"] > ranked[1]["combined_score"]


def test_pack_renders_stable_source_offsets() -> None:
    blocks = [
        {
            "doc_id": "atomic",
            "kind": "atomic",
            "date": "2024-01-01",
            "role": "user",
            "source_turn_id": 1,
            "source_start_char": 4,
            "source_end_char": 14,
            "text": "short fact",
        },
        {
            "doc_id": "raw",
            "kind": "raw",
            "date": "2024-01-01",
            "role": "user",
            "source_turn_id": 2,
            "text": "long evidence",
        },
    ]

    context, identifiers = _pack(blocks, 1_000)

    assert identifiers == ["atomic", "raw"]
    assert "source_chars=4:14" in context


def test_candidate_pack_reserves_raw_evidence_and_sorts_temporal_blocks() -> None:
    raw = [
        {
            "doc_id": "raw-later",
            "kind": "raw",
            "date": "",
            "role": "user",
            "source_turn_id": 20,
            "source_start_char": 0,
            "source_end_char": 30,
            "batch_index": 1,
            "text": "The second event happened on April 15, 2024.",
        },
        {
            "doc_id": "raw-earlier",
            "kind": "raw",
            "date": "",
            "role": "user",
            "source_turn_id": 10,
            "source_start_char": 0,
            "source_end_char": 30,
            "batch_index": 0,
            "text": "The first event happened on March 25, 2024.",
        },
    ]
    atomic = [
        {
            "doc_id": "atomic-middle",
            "kind": "atomic",
            "date": "",
            "role": "user",
            "source_turn_id": 15,
            "source_start_char": 0,
            "source_end_char": 10,
            "batch_index": 0,
            "text": "A related event happened on April 1, 2024.",
        }
    ]

    context, identifiers, diagnostics = _pack_candidate(
        "How many days passed between the events?",
        raw,
        atomic,
        max_chars=2_000,
        raw_reserve_ratio=0.75,
    )

    assert diagnostics["question_shape"] == "temporal"
    assert diagnostics["raw_document_count"] == 2
    assert identifiers == ["raw-earlier", "atomic-middle", "raw-later"]
    assert context.index("March 25") < context.index("April 1") < context.index("April 15")


def test_candidate_pack_raw_reserve_ratio_changes_binding_allocation() -> None:
    raw = [
        {
            "doc_id": f"raw-{index}",
            "kind": "raw",
            "date": "2024-01-01",
            "role": "user",
            "source_turn_id": index,
            "text": (f"raw evidence {index} " + ("r" * 700)),
        }
        for index in range(4)
    ]
    atomic = [
        {
            "doc_id": f"atomic-{index}",
            "kind": "atomic",
            "date": "2024-01-01",
            "role": "user",
            "source_turn_id": 100 + index,
            "text": (f"new atomic evidence {index} " + ("a" * 500)),
            "evidence_kinds": ["event"],
        }
        for index in range(4)
    ]

    _, low_ids, low = _pack_candidate(
        "What happened?",
        raw,
        atomic,
        max_chars=2_700,
        raw_reserve_ratio=0.50,
    )
    _, high_ids, high = _pack_candidate(
        "What happened?",
        raw,
        atomic,
        max_chars=2_700,
        raw_reserve_ratio=0.95,
    )

    assert low_ids != high_ids
    assert low["atomic_document_count"] > high["atomic_document_count"]
    assert low["raw_document_count"] < high["raw_document_count"]


def test_atomic_duplicate_detection_requires_near_complete_overlap() -> None:
    raw = [{"text": "Crystal delegated editing tasks to Greg on April 2."}]

    assert _atomic_duplicates_raw(
        {"text": "Crystal delegated editing tasks to Greg on April 2."}, raw
    )
    assert not _atomic_duplicates_raw(
        {"text": "Crystal started yoga on April 4."}, raw
    )


def test_atomic_utility_requires_new_source_or_grounded_relation_gain() -> None:
    raw = [
        {
            "source_turn_id": 7,
            "text": "My physician Elena asked me to rest.",
        }
    ]

    assert _atomic_utility_reason(
        {
            "source_turn_id": 8,
            "text": "The user rested.",
            "evidence_kinds": ["event"],
        },
        raw,
    ) == (True, "adds_source_turn")
    assert _atomic_utility_reason(
        {
            "source_turn_id": 7,
            "text": "Elena asked the user to rest.",
            "evidence_kinds": ["event"],
        },
        raw,
    ) == (False, "same_source_without_relation_or_alias")
    assert _atomic_utility_reason(
        {
            "source_turn_id": 7,
            "text": "Elena is the user's doctor.",
            "evidence_kinds": ["alias", "relation"],
        },
        raw,
    ) == (True, "adds_normalized_relation")


def test_question_shape_uses_general_semantics() -> None:
    assert _question_shape("How many days passed between both events?") == "temporal"
    assert _question_shape("Have I ever completed this project?") == "state_or_contradiction"
    assert _question_shape("Summarize my progress") == "summary"


def test_structured_judge_verdict_accepts_compact_json() -> None:
    verdict = _parse_structured_verdict(
        '{"correct":true,"reason":"same number","satisfied_rubric_items":[0],'
        '"missing_rubric_items":[],"contradiction":false}'
    )

    assert verdict["correct"] is True
    assert verdict["satisfied_rubric_items"] == [0]


def test_verified_oracle_manifest_is_explicit_and_complete() -> None:
    path = Path(__file__).parent / "fixtures" / "beam_verified_oracle_v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["protocol"] == "beam-verified-oracle-v1"
    assert len(payload["entries"]) == 20
    invalid = [
        question_id
        for question_id, entry in payload["entries"].items()
        if not entry["evaluation_valid"]
    ]
    assert invalid == ["beam-100k-10-temporal_reasoning-2"]
    assert (
        payload["entries"]["beam-100k-18-summarization-1"][
            "verified_source_chat_ids"
        ]
    )
