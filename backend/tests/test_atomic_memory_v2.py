from __future__ import annotations

import json
from pathlib import Path

from backend.app.core.atomic_memory_v2 import (
    ATOMIC_MEMORY_V2_CONTRACT_VERSION,
    AtomicMemoryV2EvidencePassResponse,
    AtomicMemoryV2PropositionPassResponse,
    AtomicMemoryV2SessionCandidate,
    CandidateCitation,
    _repair_citation,
    atomic_memory_v2_evidence_pass_json_schema,
    atomic_memory_v2_evidence_pass_prompt,
    atomic_memory_v2_deterministic_turn_indices,
    atomic_memory_v2_json_schema,
    atomic_memory_v2_entity_pass_json_schema,
    atomic_memory_v2_entity_pass_prompt,
    atomic_memory_v2_event_pass_json_schema,
    atomic_memory_v2_event_pass_prompt,
    atomic_memory_v2_prompt,
    atomic_memory_v2_proposition_pass_json_schema,
    atomic_memory_v2_proposition_pass_prompt,
    atomic_memory_v2_relation_table_pass_json_schema,
    atomic_memory_v2_relation_table_pass_prompt,
    compile_atomic_memory_v2_propositions,
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


def _flat_proposition(**overrides: object) -> dict:
    payload: dict[str, object] = {
        "proposition_id": "p1",
        "memory_text": "The user completed a durable event.",
        "citation": {"turn_index": 0, "excerpt": "durable fact"},
        "proposition_kind": "event",
        "predicate": "event",
        "modality": "completed",
        "subject_text": "",
        "subject_kind": "none",
        "subject_categories": [],
        "subject_role": "actor",
        "object_text": "",
        "object_kind": "none",
        "object_categories": [],
        "object_role": "object",
        "participants": [],
        "event_date": None,
        "quantities": [],
        "supersession_scope": None,
        "confidence": 1.0,
    }
    payload.update(overrides)
    return payload


def test_v2_normalizer_preserves_source_proposed_alias_categories() -> None:
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
    assert normalized.entities[0].categories == ["doctor", "physician"]
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
    assert complete.coverage.closed_category_scopes == ["physicians"]


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
                        "excerpt": (
                            "| Employee | Sunday |\n| --- | --- |\n"
                            "| Admon | 8am-4pm |"
                        ),
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


def test_v2_modality_safety_generalizes_beyond_fixture_verbs() -> None:
    cases = [
        ("If I saw Dr. Lee, I would ask about sleep.", "hypothetical"),
        ("I might have visited Dr. Lee last year.", "uncertain"),
        ("I am currently planning to visit Kyoto.", "planned"),
    ]

    for source, expected in cases:
        session = _session(source)
        response = AtomicMemoryV2PropositionPassResponse.model_validate(
            {
                "session_id": "session-1",
                "propositions": [
                    _flat_proposition(
                        citation={"turn_index": 0, "excerpt": source},
                        predicate="visit",
                        modality="completed",
                        subject_text="user",
                        subject_kind="speaker",
                    )
                ],
            }
        )

        normalized = normalize_atomic_memory_v2(
            session, compile_atomic_memory_v2_propositions(session, response)
        )

        assert normalized.events[0].status == expected


def test_v2_citation_anchor_never_replaces_an_unsupported_excerpt() -> None:
    session = _session("The sky is blue.")
    session["turns"][0].update(
        {
            "source_turn_id": "turn-1",
            "source_char_start": 0,
            "source_char_end": 16,
        }
    )
    unsupported = CandidateCitation(
        turn_index=0,
        excerpt="The user chose cobalt.",
        source_turn_id="turn-1",
        start_char=0,
        end_char=16,
    )

    repaired = _repair_citation(session, unsupported)

    assert repaired == unsupported


def test_v2_prompt_and_schema_do_not_allow_model_owned_closure_or_entity_ids() -> None:
    prompt = atomic_memory_v2_prompt(_session("I saw Dr. Lee."))
    schema_text = json.dumps(atomic_memory_v2_json_schema(), sort_keys=True)

    assert "backend owns both" in prompt
    assert "canonical IDs" in prompt
    assert "closed_category_scopes" not in schema_text
    assert "entity_key" not in schema_text


def test_v2_decomposed_schemas_and_prompts_keep_pass_responsibilities_separate() -> None:
    session = _session("I visited Dr. Lee.")
    entity_schema = json.dumps(atomic_memory_v2_entity_pass_json_schema())
    event_schema = json.dumps(atomic_memory_v2_event_pass_json_schema())
    relation_schema = json.dumps(atomic_memory_v2_relation_table_pass_json_schema())
    entity_prompt = atomic_memory_v2_entity_pass_prompt(session)
    event_prompt = atomic_memory_v2_event_pass_prompt(session, [])
    relation_prompt = atomic_memory_v2_relation_table_pass_prompt(session, [])

    assert '"entities"' in entity_schema
    assert '"events"' not in entity_schema
    assert '"events"' in event_schema
    assert '"relations"' not in event_schema
    assert '"relations"' in relation_schema and '"table_cells"' in relation_schema
    assert "shortest exact surface phrase" in entity_prompt
    assert "one record for every distinct referring phrase" in entity_prompt
    assert "Do not make an entity its own alias" in entity_prompt
    assert "Advice, wants, plans" in event_prompt
    assert "explicitly supported function in the event" in event_prompt
    assert "Never turn prose into a table" in relation_prompt
    assert "do not emit header cells as data" in relation_prompt


def test_v2_flat_propositions_compile_alias_categories_and_event_references() -> None:
    session = _session("I saw Dr. Lee today. My physician said I should rest.")
    response = AtomicMemoryV2PropositionPassResponse.model_validate(
        {
            "session_id": "session-1",
            "propositions": [
                {
                    "proposition_id": "p1",
                    "memory_text": "The user led Project Aurora.",
                    "citation": {
                        "turn_index": 0,
                        "excerpt": "I saw Dr. Lee today. My physician said I should rest.",
                    },
                    "proposition_kind": "alias",
                    "predicate": "same_as",
                    "modality": "asserted",
                    "subject_text": "Dr. Lee",
                    "subject_kind": "person",
                    "subject_categories": ["doctor"],
                    "subject_role": "canonical",
                    "object_text": "My physician",
                    "object_kind": "person",
                    "object_categories": ["physician"],
                    "object_role": "alias",
                    "participants": [],
                    "event_date": None,
                    "quantities": [],
                    "supersession_scope": None,
                    "confidence": 0.99,
                },
                {
                    "proposition_id": "p2",
                    "memory_text": "The Aurora migration was the user's main project.",
                    "citation": {
                        "turn_index": 0,
                        "excerpt": "I saw Dr. Lee today.",
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
                },
            ],
        }
    )

    candidate = compile_atomic_memory_v2_propositions(session, response)
    normalized = normalize_atomic_memory_v2(session, candidate)
    signatures = semantic_signatures(normalized)

    assert "category|dr. lee|doctor" in signatures
    assert "alias|dr. lee|my physician" in signatures
    assert "event|medical_visit|completed" in signatures
    assert "event_participant|medical_visit|completed|doctor|dr. lee" in signatures


def test_v2_compiler_resolves_proposition_evidence_span_reference() -> None:
    source = "I saw Dr. Lee today."
    session = _session(source)
    session["turns"][0].update(
        {
            "source_turn_id": "conversation-42-turn-7",
            "source_char_start": 100,
            "source_char_end": 120,
        }
    )
    evidence = AtomicMemoryV2EvidencePassResponse.model_validate(
        {
            "session_id": "session-1",
            "spans": [
                {
                    "span_id": "visit",
                    "citation": {"turn_index": 0, "excerpt": source},
                    "memory_text": "The user saw Dr. Lee today.",
                    "attributed_to": "user",
                    "evidence_kinds": ["event"],
                    "confidence": 0.99,
                }
            ],
        }
    )
    proposition = _flat_proposition(
        evidence_span_id="visit",
        citation=None,
        proposition_kind="event",
        predicate="medical_visit",
        modality="completed",
        subject_text="user",
        subject_kind="speaker",
        object_text="Dr. Lee",
        object_kind="person",
        object_categories=["doctor"],
    )
    response = AtomicMemoryV2PropositionPassResponse.model_validate(
        {"session_id": "session-1", "propositions": [proposition]}
    )

    candidate = compile_atomic_memory_v2_propositions(
        session, response, evidence.spans
    )
    normalized = normalize_atomic_memory_v2(session, candidate)

    assert normalized.invalid_by_reason == {}
    assert normalized.events[0].citation.excerpt == source
    assert normalized.events[0].citation.source_turn_id == "conversation-42-turn-7"
    assert normalized.events[0].citation.start_char == 100
    assert normalized.events[0].citation.end_char == 120


def test_v2_compiler_narrows_completed_fact_before_uncertain_contrast_clause() -> None:
    source = (
        "I agreed to give Michael early script access on October 4 with the condition "
        "that he can't make any edits before November 1, but I'm not sure if I'm ready "
        "for his feedback"
    )
    session = _session(source)
    response = AtomicMemoryV2PropositionPassResponse.model_validate(
        {
            "session_id": "session-1",
            "propositions": [
                _flat_proposition(
                    citation={"turn_index": 0, "excerpt": source},
                    proposition_kind="event",
                    predicate="agree_to_script_access",
                    modality="completed",
                    subject_text="user",
                    subject_kind="speaker",
                    subject_categories=[],
                    object_text="Michael",
                    object_kind="person",
                    object_categories=[],
                )
            ],
        }
    )

    candidate = compile_atomic_memory_v2_propositions(session, response)
    normalized = normalize_atomic_memory_v2(session, candidate)

    assert normalized.invalid_by_reason == {}
    assert len(normalized.events) == 1
    assert normalized.events[0].status == "completed"
    assert normalized.events[0].citation.excerpt.endswith("November 1")


def test_v2_compiler_narrows_completed_choice_before_followup_question_clause() -> None:
    source = (
        "I chose to prioritize tone calibration over plot complexity for my first draft "
        "revisions, and I'm hoping you can help me understand if that was the right decision"
    )
    session = _session(source)
    response = AtomicMemoryV2PropositionPassResponse.model_validate(
        {
            "session_id": "session-1",
            "propositions": [
                _flat_proposition(
                    citation={"turn_index": 0, "excerpt": source},
                    proposition_kind="event",
                    predicate="prioritize",
                    modality="completed",
                    subject_text="tone calibration",
                    subject_kind="concept",
                    subject_categories=[],
                    object_text="plot complexity",
                    object_kind="concept",
                    object_categories=[],
                )
            ],
        }
    )

    candidate = compile_atomic_memory_v2_propositions(session, response)
    normalized = normalize_atomic_memory_v2(session, candidate)

    assert normalized.invalid_by_reason == {}
    assert len(normalized.events) == 1
    assert normalized.events[0].citation.excerpt.endswith("revisions")


def test_v2_compiler_does_not_infer_domain_predicate_or_coreference() -> None:
    session = _session("I saw Dr. Lee today. My physician said I should rest.")
    response = AtomicMemoryV2PropositionPassResponse.model_validate(
        {
            "session_id": "session-1",
            "propositions": [
                _flat_proposition(
                    citation={
                        "turn_index": 0,
                        "excerpt": "I saw Dr. Lee today. My physician said I should rest.",
                    },
                    predicate="visit",
                    subject_text="Dr. Lee",
                    subject_kind="person",
                    subject_categories=["doctor"],
                    subject_role="doctor",
                    participants=[
                        {
                            "role": "actor",
                            "value_text": "user",
                            "value_kind": "speaker",
                            "categories": [],
                        }
                    ],
                )
            ],
        }
    )

    signatures = semantic_signatures(
        normalize_atomic_memory_v2(
            session, compile_atomic_memory_v2_propositions(session, response)
        )
    )

    assert "event|visit|completed" in signatures
    assert "event_participant|visit|completed|doctor|dr. lee" in signatures
    assert "event|medical_visit|completed" not in signatures
    assert "alias|dr. lee|my physician" not in signatures


def test_v2_compiler_only_repairs_modality_and_preserves_proposed_state_semantics() -> None:
    ownership_session = _session("I do not own a Tesla.")
    ownership_response = AtomicMemoryV2PropositionPassResponse.model_validate(
        {
            "session_id": "session-1",
            "propositions": [
                _flat_proposition(
                    citation={"turn_index": 0, "excerpt": "I do not own a Tesla."},
                    proposition_kind="relation",
                    predicate="does_not_own",
                    modality="asserted",
                    subject_text="user",
                    subject_kind="speaker",
                    object_text="Tesla",
                    object_kind="product",
                )
            ],
        }
    )
    ownership_signatures = semantic_signatures(
        normalize_atomic_memory_v2(
            ownership_session,
            compile_atomic_memory_v2_propositions(
                ownership_session, ownership_response
            ),
        )
    )

    balance_session = _session(
        "My account balance is now USD 400, up from USD 350."
    )
    balance_response = AtomicMemoryV2PropositionPassResponse.model_validate(
        {
            "session_id": "session-1",
            "propositions": [
                _flat_proposition(
                    citation={
                        "turn_index": 0,
                        "excerpt": "My account balance is now USD 400, up from USD 350.",
                    },
                    proposition_kind="relation",
                    predicate="current_balance",
                    modality="asserted",
                    subject_text="user",
                    subject_kind="speaker",
                    object_text="USD 400",
                    object_kind="literal",
                    quantities=[
                        {"value": 400, "unit": "usd", "role": "current_balance"},
                        {"value": 350, "unit": "usd", "role": "previous_balance"},
                    ],
                    supersession_scope="account_balance",
                )
            ],
        }
    )
    balance_signatures = semantic_signatures(
        normalize_atomic_memory_v2(
            balance_session,
            compile_atomic_memory_v2_propositions(balance_session, balance_response),
        )
    )

    assert "relation|does_not_own|user|tesla|negated" in ownership_signatures
    assert "relation|owns|user|tesla|negated" not in ownership_signatures
    assert "relation|current_balance|user|usd 400|asserted" in balance_signatures
    assert (
        "quantity|relation|current_balance|current_balance|400|usd"
        in balance_signatures
    )
    assert "supersession|current_balance|user" in balance_signatures


def test_v2_deterministic_structured_text_compiles_tables_and_ordered_lists() -> None:
    table_session = _session(
        "| Employee | Sunday |\n| --- | --- |\n| Admon | 8am-4pm |"
    )
    empty_table_response = AtomicMemoryV2PropositionPassResponse(
        session_id="session-1", propositions=[]
    )
    table_candidate = compile_atomic_memory_v2_propositions(
        table_session, empty_table_response
    )
    table_signatures = semantic_signatures(
        normalize_atomic_memory_v2(table_session, table_candidate)
    )

    list_session = _session("Packing list: 1. passport 2. charger 3. medication.")
    empty_list_response = AtomicMemoryV2PropositionPassResponse(
        session_id="session-1", propositions=[]
    )
    list_candidate = compile_atomic_memory_v2_propositions(
        list_session, empty_list_response
    )
    list_signatures = semantic_signatures(
        normalize_atomic_memory_v2(list_session, list_candidate)
    )

    assert table_signatures == {"table|admon|sunday|8am-4pm"}
    assert atomic_memory_v2_deterministic_turn_indices(table_session) == {0}
    assert {
        "relation|includes_item|packing list|passport|asserted",
        "relation|includes_item|packing list|charger|asserted",
        "relation|includes_item|packing list|medication|asserted",
    }.issubset(list_signatures)
    assert atomic_memory_v2_deterministic_turn_indices(list_session) == {0}


def test_v2_flat_evidence_and_proposition_contracts_are_memory_first_and_id_free() -> None:
    session = _session("I currently live in Pune.")
    evidence_prompt = atomic_memory_v2_evidence_pass_prompt(session)
    proposition_prompt = atomic_memory_v2_proposition_pass_prompt(session, [])
    evidence_schema = json.dumps(atomic_memory_v2_evidence_pass_json_schema())
    proposition_schema = json.dumps(atomic_memory_v2_proposition_pass_json_schema())

    assert "self-contained natural language statement" in evidence_prompt
    assert '"spans"' in evidence_schema
    assert '"memory_text"' in evidence_schema
    assert '"attributed_to"' in evidence_schema
    assert "must never be used as a graph or entity reference" in proposition_prompt
    assert "one concise, self-contained natural-language sentence" in proposition_prompt
    assert '"memory_text"' in proposition_schema
    assert '"subject_text"' in proposition_schema
    assert '"object_ref"' not in proposition_schema
    assert '"entity_ref"' not in proposition_schema
    assert "turn by turn and clause by clause" in evidence_prompt
    assert "do not use plan as its predicate" in proposition_prompt


def test_v2_normalizer_rejects_unsupported_literal_values() -> None:
    session = _session("I repaired the porch light.")
    candidate = AtomicMemoryV2SessionCandidate.model_validate(
        {
            "session_id": "session-1",
            "events": [
                {
                    "event_id": "e1",
                    "citation": {
                        "turn_index": 0,
                        "excerpt": "I repaired the porch light.",
                    },
                    "event_type": "repair",
                    "status": "completed",
                    "participants": [
                        {"role": "actor", "entity_ref": "user"},
                        {"role": "object", "literal_value": "garage door"},
                    ],
                    "confidence": 1.0,
                }
            ],
            "relations": [
                {
                    "relation_id": "r1",
                    "citation": {
                        "turn_index": 0,
                        "excerpt": "I repaired the porch light.",
                    },
                    "subject_ref": "user",
                    "predicate": "prefers",
                    "object_text": "blue paint",
                    "confidence": 1.0,
                }
            ],
        }
    )

    normalized = normalize_atomic_memory_v2(session, candidate)

    assert normalized.events == []
    assert normalized.relations == []
    assert normalized.invalid_by_reason == {
        "event_literal_not_in_citation": 1,
        "relation_literal_not_in_citation": 1,
    }
    assert normalized.coverage.source_coverage_complete is False


def test_v2_fixture_and_gate_manifests_are_frozen_and_complete() -> None:
    fixtures = json.loads(
        (FIXTURE_ROOT / "atomic_memory_v2_extraction.json").read_text(encoding="utf-8")
    )
    gates = json.loads(
        (FIXTURE_ROOT / "atomic_memory_v2_gates.json").read_text(encoding="utf-8")
    )

    assert fixtures["fixture_version"] == "atomic-memory-v2-fixtures-v2-development"
    assert fixtures["evaluation_role"] == "development"
    assert len(fixtures["fixtures"]) == 30
    assert len({fixture["id"] for fixture in fixtures["fixtures"]}) == 30
    assert sum(bool(fixture["critical"]) for fixture in fixtures["fixtures"]) >= 10
    assert gates["gate_version"] == "atomic-memory-v2-default-extractor-gates-v2"
    assert gates["policy"]["cpu_fallback_allowed"] is False
    assert gates["policy"]["fixture_data_may_be_used_for_training"] is False

    holdout = json.loads(
        (FIXTURE_ROOT / "atomic_memory_v2_holdout.json").read_text(encoding="utf-8")
    )
    assert holdout["evaluation_role"] == "holdout"
    assert holdout["minimum_fixture_count"] == 30
    assert len(holdout["fixtures"]) == 30
    assert len({fixture["id"] for fixture in holdout["fixtures"]}) == 30
    assert all(
        isinstance(fixture["reference_memories"], list)
        for fixture in holdout["fixtures"]
    )
