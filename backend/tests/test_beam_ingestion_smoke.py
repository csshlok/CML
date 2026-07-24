from __future__ import annotations

from backend.app.core.atomic_memory_v2 import AtomicMemoryV2EvidencePassResponse
from scripts.backend.run_beam_ingestion_smoke import (
    _citation_issues,
    _evidence_response_schema,
    _repair_evidence_payload_citations,
    _repair_proposition_span_references,
)


def _session() -> dict:
    return {
        "session_id": "window-1",
        "date": "2024-04-02",
        "turns": [
            {
                "role": "user",
                "content": "I visited Dr. Lee. She recommended rest.",
                "source_turn_id": "conversation-3-turn-7",
                "source_char_start": 100,
                "source_char_end": 142,
            }
        ],
    }


def _evidence() -> AtomicMemoryV2EvidencePassResponse:
    return AtomicMemoryV2EvidencePassResponse.model_validate(
        {
            "session_id": "window-1",
            "spans": [
                {
                    "span_id": "medical-visit",
                    "citation": {
                        "turn_index": 0,
                        "excerpt": "I visited Dr. Lee.",
                        "source_turn_id": "conversation-3-turn-7",
                        "start_char": 100,
                        "end_char": 118,
                    },
                    "memory_text": "The user visited Dr. Lee.",
                    "attributed_to": "user",
                    "evidence_kinds": ["event"],
                    "confidence": 0.99,
                }
            ],
        }
    )


def test_evidence_schema_requires_stable_source_anchors() -> None:
    citation = _evidence_response_schema(320)["$defs"]["CandidateCitation"]

    assert citation["properties"]["excerpt"]["maxLength"] == 320
    assert {"source_turn_id", "start_char", "end_char"}.issubset(
        citation["required"]
    )


def test_evidence_payload_repair_rejects_semantic_relocation() -> None:
    payload = {
        "spans": [
            {
                "span_id": "medical-visit",
                "memory_text": "The user visited Dr. Lee.",
                "citation": {
                    "turn_index": 0,
                    "excerpt": "Visited the doctor.",
                    "source_turn_id": "conversation-3-turn-7",
                    "start_char": 0,
                    "end_char": 19,
                },
            }
        ]
    }

    original = dict(payload["spans"][0]["citation"])

    assert _repair_evidence_payload_citations(_session(), payload) == 0
    citation = payload["spans"][0]["citation"]
    assert citation == original


def test_evidence_payload_repair_only_canonicalizes_an_exact_excerpt() -> None:
    payload = {
        "spans": [
            {
                "span_id": "medical-visit",
                "memory_text": "The user visited Dr. Lee.",
                "citation": {
                    "turn_index": 99,
                    "excerpt": "I visited Dr. Lee.",
                    "source_turn_id": "wrong-turn",
                    "start_char": 0,
                    "end_char": 18,
                },
            }
        ]
    }

    assert _repair_evidence_payload_citations(_session(), payload) == 1
    citation = payload["spans"][0]["citation"]
    assert citation == {
        "turn_index": 0,
        "excerpt": "I visited Dr. Lee.",
        "source_turn_id": "conversation-3-turn-7",
        "start_char": 100,
        "end_char": 118,
    }


def test_unknown_proposition_reference_is_not_guessed() -> None:
    payload = {
        "propositions": [
            {
                "predicate": "medical_visit",
                "subject_text": "user",
                "object_text": "Dr. Lee",
                "evidence_span_id": "invented-span",
                "citation": {"turn_index": 0, "excerpt": "I visited Dr. Lee."},
            }
        ]
    }

    assert _repair_proposition_span_references(payload, _evidence()) == 0
    proposition = payload["propositions"][0]
    assert proposition["evidence_span_id"] == "invented-span"
    assert "citation" in proposition


def test_valid_proposition_reference_drops_redundant_citation() -> None:
    payload = {
        "propositions": [
            {
                "predicate": "medical_visit",
                "subject_text": "user",
                "object_text": "Dr. Lee",
                "evidence_span_id": "medical-visit",
                "citation": {"turn_index": 0, "excerpt": "I visited Dr. Lee."},
            }
        ]
    }

    assert _repair_proposition_span_references(payload, _evidence()) == 1
    assert "citation" not in payload["propositions"][0]
    assert _citation_issues(
        _session(), _evidence().spans, require_stable_anchor=True
    ) == []
