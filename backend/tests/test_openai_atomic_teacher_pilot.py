from __future__ import annotations

from scripts.backend.run_openai_atomic_teacher_pilot import (
    _canonicalize_and_deduplicate_propositions,
    _canonicalize_evidence,
    _response_text,
    _strict_schema,
    select_stratified_records,
    usage_cost_usd,
)
from backend.app.core.atomic_memory_v2 import (
    AtomicMemoryV2EvidencePassResponse,
    AtomicMemoryV2PropositionPassResponse,
)


def test_stratified_selection_is_deterministic_and_balanced() -> None:
    rows = [
        {"source_id": source, "record_id": f"{source}-{index}"}
        for source in ("a", "b", "c")
        for index in range(5)
    ]

    first = select_stratified_records(rows, per_source=2, seed=7)
    second = select_stratified_records(list(reversed(rows)), per_source=2, seed=7)

    assert [row["record_id"] for row in first] == [
        row["record_id"] for row in second
    ]
    assert len(first) == 6
    assert {source: sum(row["source_id"] == source for row in first) for source in "abc"} == {
        "a": 2,
        "b": 2,
        "c": 2,
    }


def test_strict_schema_requires_every_property_and_removes_defaults() -> None:
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "title": "Name"},
            "value": {"anyOf": [{"type": "number"}, {"type": "null"}], "default": None},
        },
    }

    strict = _strict_schema(schema)

    assert strict["additionalProperties"] is False
    assert strict["required"] == ["name", "value"]
    assert "title" not in strict["properties"]["name"]
    assert "default" not in strict["properties"]["value"]


def test_response_text_extracts_responses_api_message_content() -> None:
    response = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": '{"ok":true}'}],
            }
        ]
    }

    assert _response_text(response) == '{"ok":true}'


def test_usage_cost_applies_cached_input_discount() -> None:
    cost = usage_cost_usd(
        "gpt-5.6-sol",
        {
            "input_tokens": 1_000_000,
            "cached_input_tokens": 200_000,
            "output_tokens": 100_000,
        },
    )

    assert cost == 7.1


def test_mechanical_normalization_repairs_offsets_and_exact_duplicates() -> None:
    session = {
        "session_id": "s1",
        "date": "",
        "turns": [
            {"role": "user", "content": "I live in Pune.", "source_turn_id": "t0"}
        ],
    }
    evidence = AtomicMemoryV2EvidencePassResponse.model_validate(
        {
            "session_id": "s1",
            "spans": [
                {
                    "span_id": "e1",
                    "citation": {
                        "turn_index": 0,
                        "excerpt": "live in Pune",
                        "source_turn_id": "wrong",
                        "start_char": 0,
                        "end_char": 99,
                    },
                    "memory_text": "The user lives in Pune.",
                    "attributed_to": "user",
                    "evidence_kinds": ["relation"],
                    "confidence": 1.0,
                }
            ],
        }
    )
    proposition = {
        "memory_text": "The user lives in Pune.",
        "evidence_span_id": "e1",
        "citation": None,
        "proposition_kind": "relation",
        "predicate": "lives_in",
        "modality": "asserted",
        "subject_text": "user",
        "subject_kind": "speaker",
        "subject_categories": [],
        "subject_role": "resident",
        "object_text": "Pune",
        "object_kind": "place",
        "object_categories": ["city"],
        "object_role": "residence",
        "participants": [],
        "event_date": None,
        "quantities": [],
        "supersession_scope": "user residence",
        "confidence": 1.0,
    }
    propositions = AtomicMemoryV2PropositionPassResponse.model_validate(
        {
            "session_id": "s1",
            "propositions": [
                {"proposition_id": "p1", **proposition},
                {"proposition_id": "p2", **proposition},
            ],
        }
    )

    normalized_evidence, evidence_repairs = _canonicalize_evidence(
        session, evidence
    )
    normalized_propositions, proposition_repairs, removed = (
        _canonicalize_and_deduplicate_propositions(session, propositions)
    )

    assert evidence_repairs == 1
    assert normalized_evidence.spans[0].citation.start_char == 2
    assert normalized_evidence.spans[0].citation.end_char == 14
    assert normalized_evidence.spans[0].citation.source_turn_id == "t0"
    assert proposition_repairs == 0
    assert removed == 1
    assert len(normalized_propositions.propositions) == 1
