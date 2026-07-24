from __future__ import annotations

import json

from scripts.backend.run_atomic_extractor_matrix import (
    DEFAULT_FIXTURES,
    DEFAULT_GATES,
    aggregate_candidate_results,
    compose_decomposed_candidate,
    evaluate_decomposed_fixture_response,
    evaluate_fixture_response,
    evaluate_gates,
    evaluate_proposition_fixture_response,
    load_fixture_bundle,
    load_gate_manifest,
    parse_candidate,
)
from scripts.backend.select_atomic_extractor_candidate import build_selection_report
from scripts.backend.serve_local_qwen_openai import ChatCompletionRequest


def _fixture() -> dict:
    return {
        "id": "doctor",
        "critical": True,
        "session": {
            "session_id": "s1",
            "date": "2026-07-22",
            "turns": [{"role": "user", "content": "I visited Dr. Lee."}],
        },
        "required": [
            "category|dr. lee|doctor",
            "event|medical_visit|completed",
        ],
        "forbidden": ["event|medical_visit|recommended"],
    }


def _response(status: str = "completed") -> str:
    return json.dumps(
        {
            "sessions": [
                {
                    "session_id": "s1",
                    "entities": [
                        {
                            "mention_id": "m1",
                            "citation": {"turn_index": 0, "excerpt": "Dr. Lee"},
                            "surface_text": "Dr. Lee",
                            "entity_kind": "person",
                            "categories": ["doctor"],
                            "confidence": 0.99,
                        }
                    ],
                    "events": [
                        {
                            "event_id": "e1",
                            "citation": {
                                "turn_index": 0,
                                "excerpt": "I visited Dr. Lee.",
                            },
                            "event_type": "medical visit",
                            "status": status,
                            "participants": [
                                {"role": "patient", "entity_ref": "user"},
                                {"role": "doctor", "entity_ref": "m1"},
                            ],
                            "confidence": 0.99,
                        }
                    ],
                }
            ]
        }
    )


def test_matrix_fixture_evaluation_scores_normalized_semantics() -> None:
    result = evaluate_fixture_response(
        _fixture(),
        response_text=_response(),
        finish_reason="stop",
        wall_seconds=0.5,
        peak_gpu_memory_mib=1024,
    )

    assert result["schema_compliant"] is True
    assert result["required_hit_count"] == 2
    assert result["complete_pass"] is True
    assert result["forbidden_hits"] == []


def test_matrix_fixture_evaluation_catches_forbidden_semantics() -> None:
    fixture = _fixture()
    fixture["required"] = ["event|medical_visit|recommended"]
    fixture["forbidden"] = ["event|medical_visit|recommended"]

    result = evaluate_fixture_response(
        fixture,
        response_text=_response(status="recommended"),
        finish_reason="stop",
        wall_seconds=0.5,
        peak_gpu_memory_mib=1024,
    )

    assert result["forbidden_hits"] == ["event|medical_visit|recommended"]
    assert result["complete_pass"] is False


def test_matrix_aggregation_and_gate_evaluation_fail_closed() -> None:
    passing = evaluate_fixture_response(
        _fixture(),
        response_text=_response(),
        finish_reason="stop",
        wall_seconds=0.1,
        peak_gpu_memory_mib=1024,
    )
    metrics = aggregate_candidate_results([passing])
    gates = {
        "gate_version": "test",
        "thresholds": {
            "required_signature_recall_min": 1.0,
            "forbidden_signature_violation_count_max": 0,
            "peak_gpu_memory_mib_max": 2048,
        },
    }

    assert evaluate_gates(metrics, gates)["passed"] is True
    metrics["forbidden_signature_violation_count"] = 1
    decision = evaluate_gates(metrics, gates)
    assert decision["passed"] is False
    assert decision["failed_checks"] == [
        "forbidden_signature_violation_count_max"
    ]


def test_matrix_manifests_and_loopback_candidate_load() -> None:
    fixtures = load_fixture_bundle(DEFAULT_FIXTURES)
    gates = load_gate_manifest(DEFAULT_GATES)
    candidate = parse_candidate("qwen-1.5b|Qwen/Test|http://127.0.0.1:8081/v1")

    assert len(fixtures["fixtures"]) == 30
    assert fixtures["evaluation_role"] == "development"
    assert gates["policy"]["loopback_endpoint_required"] is True
    assert candidate.label == "qwen-1.5b"
    assert candidate.base_url.endswith("/v1")


def test_default_selection_chooses_smallest_distributable_gate_pass() -> None:
    inventory = {
        "inventory_version": "test",
        "candidates": [
            {
                "label": "small",
                "parameter_count_b": 1.5,
                "default_distribution_eligible": True,
            },
            {
                "label": "large",
                "parameter_count_b": 4.0,
                "default_distribution_eligible": True,
            },
        ],
    }
    matrix = {
        "protocol": "matrix-v1",
        "gate_version": "gates-v1",
        "evaluation_role": "holdout",
        "fixture_count": 30,
        "reports": [
            {"candidate": {"label": "small"}, "metrics": {}, "gate": {"passed": True}},
            {"candidate": {"label": "large"}, "metrics": {}, "gate": {"passed": True}},
        ],
    }

    selection = build_selection_report([matrix], inventory)

    assert selection["selection_status"] == "selected"
    assert selection["selected_candidate"] == "small"


def test_default_selection_rejects_development_only_gate_pass() -> None:
    inventory = {
        "inventory_version": "test",
        "candidates": [
            {
                "label": "candidate",
                "parameter_count_b": 1.5,
                "default_distribution_eligible": True,
            }
        ],
    }
    matrix = {
        "protocol": "matrix-v1",
        "gate_version": "gates-v1",
        "evaluation_role": "development",
        "fixture_count": 30,
        "reports": [
            {
                "candidate": {"label": "candidate"},
                "metrics": {},
                "gate": {"passed": True},
            }
        ],
    }

    selection = build_selection_report([matrix], inventory)

    assert selection["selection_status"] == "no_candidate_passed"
    assert selection["selected_candidate"] is None
    assert selection["candidates"][0]["rejection_reasons"] == [
        "independent_holdout_required"
    ]


def test_transformers_benchmark_endpoint_accepts_schema_and_large_output_budget() -> None:
    request = ChatCompletionRequest.model_validate(
        {
            "model": "extractor",
            "messages": [{"role": "user", "content": "extract"}],
            "max_tokens": 2048,
            "response_format": {"type": "json_object", "schema": {"type": "object"}},
            "chat_template_kwargs": {"enable_thinking": False},
        }
    )

    assert request.max_tokens == 2048
    assert request.response_format["schema"] == {"type": "object"}


def test_decomposed_passes_compose_into_one_normalized_fixture_result() -> None:
    fixture = _fixture()
    passes = {
        "entities": {
            "response_text": json.dumps(
                {
                    "session_id": "s1",
                    "entities": [
                        {
                            "mention_id": "m1",
                            "citation": {"turn_index": 0, "excerpt": "Dr. Lee"},
                            "surface_text": "Dr. Lee",
                            "entity_kind": "person",
                            "categories": ["doctor"],
                            "confidence": 0.99,
                        }
                    ],
                }
            ),
            "finish_reason": "stop",
            "wall_seconds": 0.1,
        },
        "events": {
            "response_text": json.dumps(
                {
                    "session_id": "s1",
                    "events": [
                        {
                            "event_id": "e1",
                            "citation": {
                                "turn_index": 0,
                                "excerpt": "I visited Dr. Lee.",
                            },
                            "event_type": "medical_visit",
                            "status": "completed",
                            "participants": [
                                {"role": "patient", "entity_ref": "user"},
                                {"role": "doctor", "entity_ref": "m1"},
                            ],
                            "confidence": 0.99,
                        }
                    ],
                }
            ),
            "finish_reason": "stop",
            "wall_seconds": 0.1,
        },
        "relations_tables": {
            "response_text": json.dumps(
                {"session_id": "s1", "relations": [], "table_cells": []}
            ),
            "finish_reason": "stop",
            "wall_seconds": 0.1,
        },
    }

    candidate = compose_decomposed_candidate(
        fixture,
        entity_response_text=passes["entities"]["response_text"],
        event_response_text=passes["events"]["response_text"],
        relation_table_response_text=passes["relations_tables"]["response_text"],
    )
    result = evaluate_decomposed_fixture_response(
        fixture,
        passes=passes,
        wall_seconds=0.3,
        peak_gpu_memory_mib=1024,
    )

    assert len(candidate.entities) == 1
    assert len(candidate.events) == 1
    assert result["strategy"] == "decomposed"
    assert result["complete_pass"] is True
    assert result["required_hit_count"] == 2


def test_decomposed_evaluation_isolates_invalid_pass_without_hiding_error() -> None:
    fixture = _fixture()
    passes = {
        "entities": {
            "response_text": json.dumps(
                {
                    "session_id": "s1",
                    "entities": [
                        {
                            "mention_id": "m1",
                            "citation": {"turn_index": 0, "excerpt": "Dr. Lee"},
                            "surface_text": "Dr. Lee",
                            "entity_kind": "person",
                            "categories": ["doctor"],
                            "confidence": 0.99,
                        }
                    ],
                }
            ),
            "finish_reason": "stop",
            "wall_seconds": 0.1,
        },
        "events": {
            "response_text": json.dumps({"session_id": "s1", "events": []}),
            "finish_reason": "stop",
            "wall_seconds": 0.1,
        },
        "relations_tables": {
            "response_text": "not json",
            "finish_reason": "stop",
            "wall_seconds": 0.1,
        },
    }

    result = evaluate_decomposed_fixture_response(
        fixture,
        passes=passes,
        wall_seconds=0.3,
        peak_gpu_memory_mib=1024,
    )

    assert result["required_hit_count"] == 1
    assert result["schema_compliant"] is False
    assert result["complete_pass"] is False
    assert result["error"].startswith("decomposed_pass_errors:")
    assert set(result["pass_errors"]) == {"relations_tables"}


def test_proposition_evaluation_compiles_flat_passes_and_keeps_pass_metrics() -> None:
    fixture = _fixture()
    passes = {
        "evidence": {
            "response_text": json.dumps(
                {
                    "session_id": "s1",
                    "spans": [
                        {
                            "span_id": "s1",
                            "citation": {
                                "turn_index": 0,
                                "excerpt": "I visited Dr. Lee.",
                            },
                            "memory_text": "The user visited Dr. Lee, a doctor.",
                            "attributed_to": "user",
                            "evidence_kinds": ["entity", "event"],
                            "confidence": 1.0,
                        }
                    ],
                }
            ),
            "finish_reason": "stop",
            "wall_seconds": 0.1,
        },
        "propositions": {
            "response_text": json.dumps(
                {
                    "session_id": "s1",
                    "propositions": [
                        {
                            "proposition_id": "p1",
                            "memory_text": "The user visited Dr. Lee.",
                            "citation": {
                                "turn_index": 0,
                                "excerpt": "I visited Dr. Lee.",
                            },
                            "proposition_kind": "event",
                            "predicate": "medical_visit",
                            "modality": "completed",
                            "subject_text": "",
                            "subject_kind": "none",
                            "subject_categories": [],
                            "subject_role": "actor",
                            "object_text": "",
                            "object_kind": "none",
                            "object_categories": [],
                            "object_role": "object",
                            "participants": [
                                {
                                    "role": "patient",
                                    "value_text": "user",
                                    "value_kind": "speaker",
                                    "categories": [],
                                },
                                {
                                    "role": "doctor",
                                    "value_text": "Dr. Lee",
                                    "value_kind": "person",
                                    "categories": ["doctor"],
                                },
                            ],
                            "event_date": None,
                            "quantities": [],
                            "supersession_scope": None,
                            "confidence": 0.99,
                        }
                    ],
                }
            ),
            "finish_reason": "stop",
            "wall_seconds": 0.2,
        },
    }

    result = evaluate_proposition_fixture_response(
        fixture,
        passes=passes,
        wall_seconds=0.3,
        peak_gpu_memory_mib=1024,
    )

    assert result["complete_pass"] is True
    assert result["required_hit_count"] == 2
    assert result["pass_errors"] == {}
    assert result["strategy"] == "propositions"
    assert result["proposition_memories"][0]["memory_text"] == (
        "The user visited Dr. Lee."
    )
