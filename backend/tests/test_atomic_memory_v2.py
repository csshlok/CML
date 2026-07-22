from __future__ import annotations

import json
from pathlib import Path

from backend.app.core.atomic_memory_v2 import (
    ATOMIC_MEMORY_V2_CONTRACT_VERSION,
    AtomicMemoryV2SessionCandidate,
    atomic_memory_v2_json_schema,
    atomic_memory_v2_prompt,
    normalize_atomic_memory_v2,
    semantic_signatures,
)


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"


def _session(content: str) -> dict:
    return {
        "session_id": "session-1",
        "date": "2026-07-22",
        "turns": [{"role": "user", "content": content}],
    }


def test_v2_normalizer_assigns_backend_entity_key_and_normalizes_alias_category() -> None:
    session = _session("I saw Dr. Lee today. My physician said I should rest.")
    candidate = AtomicMemoryV2SessionCandidate.model_validate(
        {
            "session_id": "session-1",
            "entities": [
                {
                    "mention_id": "m1",
                    "citation": {"turn_index": 0, "excerpt": "I saw Dr. Lee today."},
                    "surface_text": "Dr. Lee",
                    "entity_kind": "person",
                    "categories": ["physician"],
                    "confidence": 0.99,
                },
                {
                    "mention_id": "m2",
                    "citation": {
                        "turn_index": 0,
                        "excerpt": "My physician said I should rest.",
                    },
                    "surface_text": "My physician",
                    "entity_kind": "person",
                    "categories": ["doctor"],
                    "alias_of_mention_id": "m1",
                    "confidence": 0.95,
                },
            ],
        }
    )

    normalized = normalize_atomic_memory_v2(session, candidate)

    assert normalized.contract_version == ATOMIC_MEMORY_V2_CONTRACT_VERSION
    assert len(normalized.entities) == 1
    assert normalized.entities[0].entity_key == "entity:person:dr_lee"
    assert normalized.entities[0].categories == ["doctor"]
    assert normalized.coverage.source_coverage_complete is True
    assert normalized.invalid_by_reason == {}
    assert normalized.model_dump_json() == normalize_atomic_memory_v2(
        session, candidate
    ).model_dump_json()


def test_v2_normalizer_rejects_bad_reference_and_withholds_closure() -> None:
    session = _session("I visited Dr. Lee.")
    candidate = AtomicMemoryV2SessionCandidate.model_validate(
        {
            "session_id": "session-1",
            "events": [
                {
                    "event_id": "e1",
                    "citation": {"turn_index": 0, "excerpt": "I visited Dr. Lee."},
                    "event_type": "medical visit",
                    "status": "completed",
                    "participants": [{"role": "doctor", "entity_ref": "missing"}],
                    "confidence": 0.9,
                }
            ],
        }
    )

    normalized = normalize_atomic_memory_v2(
        session,
        candidate,
        category_classification_complete=True,
        category_scopes=["doctors"],
    )

    assert normalized.events == []
    assert normalized.invalid_by_reason == {"event_participant_reference_missing": 1}
    assert normalized.coverage.source_coverage_complete is False
    assert normalized.coverage.closed_category_scopes == []


def test_v2_closure_is_pipeline_owned_and_requires_complete_processing() -> None:
    session = {
        "session_id": "session-1",
        "date": "2026-07-22",
        "turns": [
            {"role": "user", "content": "I saw Dr. Lee."},
            {"role": "assistant", "content": "You should rest."},
        ],
    }
    candidate = AtomicMemoryV2SessionCandidate(session_id="session-1")

    incomplete = normalize_atomic_memory_v2(
        session,
        candidate,
        processed_turn_indices=[0],
        category_classification_complete=True,
        category_scopes=["physicians"],
    )
    complete = normalize_atomic_memory_v2(
        session,
        candidate,
        processed_turn_indices=[0, 1],
        category_classification_complete=True,
        category_scopes=["physicians"],
    )

    assert incomplete.coverage.closed_category_scopes == []
    assert "source_turns_incomplete" in incomplete.coverage.reasons
    assert complete.coverage.closed_category_scopes == ["doctor"]


def test_v2_preserves_recommended_status_and_linked_table_cell() -> None:
    session = _session(
        "You should schedule an appointment.\n"
        "| Employee | Sunday |\n| --- | --- |\n| Admon | 8am-4pm |"
    )
    candidate = AtomicMemoryV2SessionCandidate.model_validate(
        {
            "session_id": "session-1",
            "events": [
                {
                    "event_id": "e1",
                    "citation": {
                        "turn_index": 0,
                        "excerpt": "You should schedule an appointment.",
                    },
                    "event_type": "schedule appointment",
                    "status": "recommended",
                    "participants": [{"role": "patient", "entity_ref": "user"}],
                    "confidence": 0.99,
                }
            ],
            "table_cells": [
                {
                    "cell_id": "c1",
                    "citation": {
                        "turn_index": 0,
                        "excerpt": "| Admon | 8am-4pm |",
                    },
                    "table_id": "weekly schedule",
                    "row_label": "Admon",
                    "column_label": "Sunday",
                    "value_text": "8am-4pm",
                    "confidence": 0.99,
                }
            ],
        }
    )

    signatures = semantic_signatures(normalize_atomic_memory_v2(session, candidate))

    assert "event|schedule_appointment|recommended" in signatures
    assert "event|schedule_appointment|completed" not in signatures
    assert "table|admon|sunday|8am-4pm" in signatures


def test_v2_rejects_completed_action_when_source_only_recommends_it() -> None:
    session = _session("You should schedule an appointment.")
    candidate = AtomicMemoryV2SessionCandidate.model_validate(
        {
            "session_id": "session-1",
            "events": [
                {
                    "event_id": "e1",
                    "citation": {
                        "turn_index": 0,
                        "excerpt": "You should schedule an appointment.",
                    },
                    "event_type": "schedule appointment",
                    "status": "completed",
                    "participants": [{"role": "patient", "entity_ref": "user"}],
                    "confidence": 0.99,
                }
            ],
        }
    )

    normalized = normalize_atomic_memory_v2(session, candidate)

    assert normalized.events == []
    assert normalized.invalid_by_reason == {
        "completed_event_not_supported_by_modality": 1
    }
    assert normalized.coverage.source_coverage_complete is False


def test_v2_normalizes_event_identity_quantities_and_supersession() -> None:
    session = _session(
        "I bought three dresses. That purchase left my balance at $400,000."
    )
    candidate = AtomicMemoryV2SessionCandidate.model_validate(
        {
            "session_id": "session-1",
            "events": [
                {
                    "event_id": "e1",
                    "citation": {"turn_index": 0, "excerpt": "I bought three dresses."},
                    "event_type": "purchase",
                    "status": "completed",
                    "participants": [
                        {"role": "buyer", "entity_ref": "user"},
                        {"role": "item", "literal_value": "three dresses"},
                    ],
                    "quantities": [
                        {"value": 3, "unit": "dresses", "role": "item count"}
                    ],
                    "confidence": 0.99,
                },
                {
                    "event_id": "e2",
                    "same_as_event_id": "e1",
                    "citation": {
                        "turn_index": 0,
                        "excerpt": "That purchase left my balance at $400,000.",
                    },
                    "event_type": "purchase",
                    "status": "completed",
                    "participants": [{"role": "buyer", "entity_ref": "user"}],
                    "confidence": 0.9,
                },
            ],
            "relations": [
                {
                    "relation_id": "r1",
                    "citation": {
                        "turn_index": 0,
                        "excerpt": "my balance at $400,000",
                    },
                    "subject_ref": "user",
                    "predicate": "current balance",
                    "object_text": "$400,000",
                    "quantity": {"value": 400000, "unit": "USD", "role": "balance"},
                    "supersession_scope": "account balance",
                    "assertion_mode": "asserted",
                    "confidence": 0.99,
                }
            ],
        }
    )

    normalized = normalize_atomic_memory_v2(session, candidate)
    signatures = semantic_signatures(normalized)

    assert len({event.event_identity_key for event in normalized.events}) == 1
    assert "quantity|event|purchase|item_count|3|dresses" in signatures
    assert "quantity|relation|current_balance|balance|400000|usd" in signatures
    assert "supersession|current_balance|user" in signatures


def test_v2_does_not_mistake_may_date_for_uncertain_modality() -> None:
    session = _session("I graduated on May 5.")
    candidate = AtomicMemoryV2SessionCandidate.model_validate(
        {
            "session_id": "session-1",
            "events": [
                {
                    "event_id": "e1",
                    "citation": {"turn_index": 0, "excerpt": "I graduated on May 5."},
                    "event_type": "graduate",
                    "status": "completed",
                    "participants": [{"role": "graduate", "entity_ref": "user"}],
                    "event_date": "2026-05-05",
                    "confidence": 0.99,
                }
            ],
        }
    )

    normalized = normalize_atomic_memory_v2(session, candidate)

    assert len(normalized.events) == 1
    assert normalized.invalid_by_reason == {}


def test_v2_prompt_and_schema_do_not_allow_model_owned_closure_or_entity_ids() -> None:
    prompt = atomic_memory_v2_prompt(_session("I saw Dr. Lee."))
    schema_text = json.dumps(atomic_memory_v2_json_schema(), sort_keys=True)

    assert "backend owns both" in prompt
    assert "canonical IDs" in prompt
    assert "closed_category_scopes" not in schema_text
    assert "entity_key" not in schema_text


def test_v2_fixture_and_gate_manifests_are_frozen_and_complete() -> None:
    fixtures = json.loads(
        (FIXTURE_ROOT / "atomic_memory_v2_extraction.json").read_text(encoding="utf-8")
    )
    gates = json.loads(
        (FIXTURE_ROOT / "atomic_memory_v2_gates.json").read_text(encoding="utf-8")
    )

    assert fixtures["fixture_version"] == "atomic-memory-v2-fixtures-v1"
    assert len(fixtures["fixtures"]) == 30
    assert len({fixture["id"] for fixture in fixtures["fixtures"]}) == 30
    assert sum(bool(fixture["critical"]) for fixture in fixtures["fixtures"]) >= 10
    assert gates["gate_version"] == "atomic-memory-v2-default-extractor-gates-v1"
    assert gates["policy"]["cpu_fallback_allowed"] is False
    assert gates["policy"]["fixture_data_may_be_used_for_training"] is False
