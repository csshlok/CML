from __future__ import annotations

import pytest

from scripts.backend.benchmark_reader_evidence_local import (
    _metrics,
    select_from_manifest,
    select_references,
)

pytestmark = pytest.mark.skip(
    reason="DEAD EXPERIMENT: reader-evidence packing failed frozen accuracy gates"
)


def _reference(question_id: str, question_type: str, question: str, answer: str) -> dict:
    return {
        "question_id": question_id,
        "question_type": question_type,
        "question": question,
        "answer": answer,
        "answer_session_ids": [f"answer-{question_id}"],
    }


def test_stratified_selection_is_deterministic_and_does_not_read_answers() -> None:
    rows = []
    for index in range(4):
        rows.extend(
            [
                _reference(
                    f"numeric-{index}",
                    "single-session-user",
                    f"How many items {index}?",
                    "secret-a",
                ),
                _reference(
                    f"temporal-{index}",
                    "temporal-reasoning",
                    f"Which event was first {index}?",
                    "secret-b",
                ),
                _reference(
                    f"preference-{index}",
                    "single-session-preference",
                    f"What do I prefer {index}?",
                    "secret-c",
                ),
                _reference(
                    f"update-{index}", "knowledge-update", f"What is current {index}?", "secret-d"
                ),
                _reference(
                    f"multi-{index}",
                    "multi-session",
                    f"Which projects changed {index}?",
                    "secret-e",
                ),
            ]
        )

    first = select_references(rows, per_stratum=2, seed="frozen")
    changed_answers = [{**row, "answer": "different hidden answer"} for row in rows]
    second = select_references(changed_answers, per_stratum=2, seed="frozen")

    assert [row["question_id"] for row in first] == [row["question_id"] for row in second]
    assert len(first) == 10
    assert len({row["question_id"] for row in first}) == 10


def test_proxy_metrics_keep_accuracy_separate_from_token_overlap() -> None:
    packing = {"prompt_tokens_estimate": 100}
    rows = [
        {
            "legacy": {
                "accepted": False,
                "token_f1": 0.8,
                "reference_contained": True,
                "packing": packing,
            },
            "reader_evidence": {
                "accepted": True,
                "token_f1": 0.7,
                "reference_contained": False,
                "packing": packing,
            },
        }
    ]

    result = _metrics(rows, "reader_evidence")

    assert result["local_proxy_accuracy"] == 1.0
    assert result["mean_token_f1"] == 0.7
    assert result["reference_containment_rate"] == 0.0


def test_frozen_manifest_requires_the_exact_dataset_hash() -> None:
    dataset = [_reference("q1", "multi-session", "Which item?", "one")]
    manifest = {
        "dataset_sha256": "expected",
        "items": [{"question_id": "q1", "stratum": "multi-session"}],
    }

    with pytest.raises(RuntimeError, match="expects dataset"):
        select_from_manifest(dataset, manifest=manifest, dataset_hash="different")

    selected = select_from_manifest(dataset, manifest=manifest, dataset_hash="expected")
    assert selected[0]["question_id"] == "q1"
    assert selected[0]["evaluation_stratum"] == "multi-session"
