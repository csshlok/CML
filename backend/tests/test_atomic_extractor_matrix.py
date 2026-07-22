from __future__ import annotations

import json
from pathlib import Path

from scripts.backend.run_atomic_extractor_matrix import (
    DEFAULT_FIXTURES,
    DEFAULT_GATES,
    aggregate_candidate_results,
    evaluate_fixture_response,
    evaluate_gates,
    load_fixture_bundle,
    load_gate_manifest,
    parse_candidate,
)


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
                            "categories": ["physician"],
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
    assert gates["policy"]["loopback_endpoint_required"] is True
    assert candidate.label == "qwen-1.5b"
    assert candidate.base_url.endswith("/v1")
