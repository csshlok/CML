from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts.backend.evaluate_atomic_extractor_checkpoint import (
    build_promotion_report,
)
from scripts.backend.authorize_atomic_reader_benchmark import build_authorization
from scripts.backend.prepare_beam_failure_replay import build_replay, final_labels
from scripts.backend.prepare_atomic_extractor_training_data import (
    _split_for,
    prepare_corpus,
)
from scripts.backend.train_atomic_extractor_qlora import validate_inputs


def _record(index: int, *, content: str | None = None) -> dict:
    text = content or f"I repaired device {index} yesterday."
    excerpt = text
    return {
        "record_id": f"independent-{index}",
        "split_group": f"conversation-{index}",
        "session": {
            "session_id": f"session-{index}",
            "date": "2026-07-01",
            "turns": [{"role": "user", "content": text}],
        },
        "evidence_target": {
            "session_id": f"session-{index}",
            "spans": [
                {
                    "span_id": "span-1",
                    "citation": {"turn_index": 0, "excerpt": excerpt},
                    "memory_text": f"The user repaired device {index} yesterday.",
                    "attributed_to": "user",
                    "evidence_kinds": ["event"],
                    "confidence": 1.0,
                }
            ],
        },
        "proposition_target": {
            "session_id": f"session-{index}",
            "propositions": [
                {
                    "proposition_id": "proposition-1",
                    "memory_text": f"The user repaired device {index} yesterday.",
                    "evidence_span_id": "span-1",
                    "proposition_kind": "event",
                    "predicate": "repair",
                    "modality": "completed",
                    "subject_text": "user",
                    "subject_kind": "speaker",
                    "subject_categories": [],
                    "object_text": f"device {index}",
                    "object_kind": "object",
                    "object_categories": [],
                    "participants": [],
                    "quantities": [],
                    "confidence": 1.0,
                }
            ],
        },
    }


def _corpus(records: list[dict], *, source_name: str = "independent synthetic") -> dict:
    return {
        "corpus_version": "independent-v1",
        "evaluation_role": "training",
        "provenance": {
            "source_name": source_name,
            "source_version": "1",
            "license": "CC0-1.0",
            "teacher_model": "teacher-v1",
            "teacher_provider": "local",
            "created_at": "2026-07-23T00:00:00Z",
            "paid_cost_usd": 0,
        },
        "records": records,
    }


def test_training_preparation_is_deterministic_and_emits_both_passes() -> None:
    records = [_record(index) for index in range(20)]
    outputs, audit = prepare_corpus(
        _corpus(records),
        protected_paths=[],
        validation_percent=20,
        split_seed=20260723,
        minimum_records=20,
        allow_small_corpus=False,
    )

    assert outputs["train"]
    assert outputs["validation"]
    assert audit["training_ready"] is True
    assert audit["sft_example_count"] == 40
    assert {row["pass"] for rows in outputs.values() for row in rows} == {
        "evidence",
        "proposition",
    }
    assert _split_for("same-group", 7, 20) == _split_for("same-group", 7, 20)


def test_training_preparation_rejects_benchmark_provenance() -> None:
    with pytest.raises(ValueError, match="benchmark_derived"):
        prepare_corpus(
            _corpus([_record(1)], source_name="LoCoMo"),
            protected_paths=[],
            validation_percent=50,
            split_seed=1,
            minimum_records=1,
            allow_small_corpus=True,
        )


def test_training_preparation_rejects_protected_content(tmp_path) -> None:
    protected = {
        "fixtures": [
            {"id": "protected", "session": _record(1)["session"]}
        ]
    }
    path = tmp_path / "protected.json"
    path.write_text(json.dumps(protected), encoding="utf-8")

    with pytest.raises(ValueError, match="protected_evaluation_content_overlap"):
        prepare_corpus(
            _corpus([_record(99, content="I repaired device 1 yesterday.")]),
            protected_paths=[path],
            validation_percent=50,
            split_seed=1,
            minimum_records=1,
            allow_small_corpus=True,
        )


def test_qlora_input_validation_checks_frozen_hashes(tmp_path) -> None:
    train = tmp_path / "train.jsonl"
    validation = tmp_path / "validation.jsonl"
    train.write_text('{"messages":[]}\n', encoding="utf-8")
    validation.write_text('{"messages":[]}\n', encoding="utf-8")

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    manifest = {
        "protocol": "atomic-extractor-independent-training-corpus-v1",
        "evaluation_role": "training",
        "training_ready": True,
        "record_count": 1000,
        "sft_example_count": 2000,
        "output_sha256": {
            "train": digest(train),
            "validation": digest(validation),
        },
    }
    (tmp_path / "training-data-manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    args = SimpleNamespace(
        data_dir=tmp_path,
        max_length=1536,
        batch_size=1,
        lora_r=16,
        lora_alpha=32,
    )

    assert validate_inputs(args)["record_count"] == 1000
    train.write_text('{"messages":[1]}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="hash_mismatch"):
        validate_inputs(args)


def _semantic_report(role: str, f1: float, *, passed: bool) -> dict:
    return {
        "evaluation_role": role,
        "fixture_sha256": "same-validation-fixture",
        "gate_version": "gate-v1",
        "reports": [
            {
                "candidate": {"label": f"{role}-{f1}"},
                "micro_precision": f1,
                "micro_recall": f1,
                "micro_f1": f1,
                "gate": {"passed": passed},
            }
        ],
    }


def test_checkpoint_promotion_requires_clean_validation_gain() -> None:
    training = {
        "protocol": "atomic-extractor-qwen3-4b-qlora-v1",
        "status": "completed",
    }
    report = build_promotion_report(
        training,
        _semantic_report("development", 0.85, passed=True),
        _semantic_report("validation", 0.86, passed=True),
        _semantic_report("validation", 0.80, passed=False),
        minimum_validation_f1_delta=0.02,
    )
    assert report["holdout_authorized"] is True
    assert report["reader_benchmark_authorized"] is False

    failed = build_promotion_report(
        training,
        _semantic_report("development", 0.85, passed=True),
        _semantic_report("validation", 0.81, passed=True),
        _semantic_report("validation", 0.80, passed=False),
        minimum_validation_f1_delta=0.02,
    )
    assert failed["holdout_authorized"] is False


def test_reader_authorization_requires_redacted_holdout_and_clean_replay() -> None:
    promotion = {
        "holdout_authorized": True,
        "reader_benchmark_authorized": False,
    }
    holdout = {
        "evaluation_role": "holdout",
        "holdout_details_redacted": True,
        "reports": [{"candidate": {"label": "fine-tuned"}, "gate": {"passed": True}}],
    }
    offline = {
        "evaluation_role": "development",
        "selection_mode": "representative",
        "atomic_extraction_scope": "full-haystack",
        "cpu_model_fallback_allowed": False,
        "promotion_passed": True,
        "new_regression_count": 0,
        "false_safe_activation_count": 0,
        "predicted_accuracy_delta": 0.05,
        "baseline_packed_macro_recall": 0.5,
        "candidate_packed_macro_recall": 0.7,
    }

    assert build_authorization(
        promotion, holdout, offline
    )["reader_benchmark_authorized"] is True
    holdout["holdout_details_redacted"] = False
    assert build_authorization(
        promotion, holdout, offline
    )["reader_benchmark_authorized"] is False


def test_failure_replay_uses_adjudication_only_for_disagreements() -> None:
    primary = [
        {"arm": "baseline", "question_id": "q1", "correct": True},
        {"arm": "candidate", "question_id": "q1", "correct": False},
        {"arm": "baseline", "question_id": "q2", "correct": False},
        {"arm": "candidate", "question_id": "q2", "correct": True},
    ]
    independent = [
        {"arm": "baseline", "question_id": "q1", "correct": True},
        {"arm": "candidate", "question_id": "q1", "correct": True},
        {"arm": "baseline", "question_id": "q2", "correct": False},
        {"arm": "candidate", "question_id": "q2", "correct": True},
    ]
    adjudicated = [
        {"arm": "candidate", "question_id": "q1", "correct": False}
    ]
    final = final_labels(primary, independent, adjudicated)
    selected, manifest = build_replay(
        [
            {"question_id": "q1", "category": "update"},
            {"question_id": "q2", "category": "preference"},
        ],
        final,
    )

    assert len(selected) == 2
    assert manifest["baseline_win_count"] == 1
    assert manifest["candidate_win_count"] == 1
