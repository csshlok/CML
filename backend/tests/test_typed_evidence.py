from __future__ import annotations

import json

from backend.app.core.typed_evidence import (
    SCHEMA_HASH,
    Citation,
    EvidenceRecord,
    NumericValue,
    PreferenceSignal,
    QueryPlan,
    extract_evidence,
    plan_query,
    reduce_evidence,
    source_content_hash,
)


def _record(
    claim_id: str,
    *,
    speaker: str = "user",
    provenance: str = "user_statement",
    mode: str = "completed",
    negated: bool = False,
    object: str = "orange",
    object_type: str = "citrus_fruit",
    date: str = "2025-01-01",
    numeric: NumericValue | None = None,
    preference: PreferenceSignal | None = None,
    semantic_tags: list[str] | None = None,
    confidence: float = 0.95,
) -> EvidenceRecord:
    return EvidenceRecord(
        claim_id=claim_id,
        citation=Citation(
            session_id=f"session-{claim_id}",
            turn_index=0,
            speaker=speaker,
            session_date=date,
            excerpt=f"evidence for {claim_id}",
            source_content_hash="a" * 64,
        ),
        provenance=provenance,
        primary_mode=mode,
        negated=negated,
        subject="user",
        predicate="used_in_cocktail_preparation",
        object=object,
        object_type=object_type,
        numeric=numeric,
        preference=preference,
        semantic_tags=(
            semantic_tags
            if semantic_tags is not None
            else ["demonstrated_experience"]
            if mode == "completed"
            else ["stated_goal_or_interest"]
            if mode in {"current", "goal", "planned"}
            else []
        ),
        confidence=confidence,
    )


def test_schema_hash_is_derived_and_stable() -> None:
    assert len(SCHEMA_HASH) == 64
    assert set(SCHEMA_HASH) <= set("0123456789abcdef")


def test_distinct_count_filters_suggestions_negation_and_low_confidence() -> None:
    records = [
        _record("orange", object="orange"),
        _record("lime", object="lime"),
        _record(
            "sangria",
            object="sangria_with_orange_and_lemon",
            object_type="cocktail",
        ).model_copy(
            update={
                "citation": Citation(
                    session_id="session-sangria",
                    turn_index=0,
                    speaker="user",
                    session_date="2025-01-01",
                    excerpt="I served Sangria with slices of orange and lemon.",
                    source_content_hash="a" * 64,
                )
            }
        ),
        _record(
            "grapefruit-suggestion",
            speaker="assistant",
            provenance="assistant_suggestion",
            mode="suggested",
            object="grapefruit",
        ),
        _record("grapefruit-rejected", mode="planned", negated=True, object="grapefruit"),
        _record("pomelo-uncertain", object="pomelo", confidence=0.4),
    ]

    result = reduce_evidence(
        QueryPlan(intent="distinct_count", target_entity_type="citrus_fruit"),
        records,
        question="How many different types of citrus fruits have I used?",
    )

    assert result.status == "resolved"
    assert result.answer == "3: lemon, lime, orange."


def test_latest_state_compares_only_matching_numeric_role_context_and_unit() -> None:
    ratio = lambda value: NumericValue(  # noqa: E731
        value=value,
        unit="oz_per_tbsp",
        role="ratio",
        context="french_press_water",
        denominator_value=1,
        denominator_unit="tbsp",
    )
    records = [
        _record("old", date="2025-01-01", numeric=ratio(6), object="6"),
        _record("new", date="2025-02-01", numeric=ratio(5), object="5"),
        _record(
            "unrelated-price",
            numeric=NumericValue(value=20, unit="usd", role="price", context="coffee"),
            object="20",
        ),
    ]

    result = reduce_evidence(
        QueryPlan(intent="latest_state_comparison"),
        records,
        question="Did I switch to more or less water?",
    )

    assert result.status == "resolved"
    assert result.answer == "Less: from 6 to 5 oz per tbsp."
    assert result.evidence_claim_ids == ["old", "new"]


def test_personalized_advice_requires_experience_and_interest() -> None:
    only_experience = [_record("stew", object="beef_stew")]
    missing = reduce_evidence(
        QueryPlan(
            intent="personalized_advice",
            allowed_primary_modes=["completed", "current", "goal"],
        ),
        only_experience,
        question="What should I cook next?",
    )
    assert missing.status == "fallback"
    assert missing.contract is not None
    assert missing.contract.missing_required_anchor_types == [
        "same_session_demonstrated_experience_and_interest"
    ]

    shared_experience = only_experience[0].model_copy(
        update={
            "citation": only_experience[0].citation.model_copy(
                update={"session_id": "slow-cooker-session"}
            )
        }
    )
    shared_interest = _record(
        "yogurt",
        mode="goal",
        object="slow_cooker_yogurt",
        preference=PreferenceSignal(
            polarity="positive", strength="soft", topic="slow_cooker_yogurt"
        ),
    )
    shared_interest = shared_interest.model_copy(
        update={
            "citation": shared_interest.citation.model_copy(
                update={"session_id": "slow-cooker-session"}
            )
        }
    )
    complete = reduce_evidence(
        QueryPlan(
            intent="personalized_advice",
            allowed_primary_modes=["completed", "current", "goal"],
        ),
        [shared_experience, shared_interest],
        question="What should I cook next?",
    )
    assert complete.status == "needs_generation"
    assert complete.contract is not None
    assert complete.contract.required_claim_ids == ["stew", "yogurt"]


def test_query_planner_limits_typed_layer_to_proven_operations() -> None:
    assert plan_query(
        {
            "question_type": "multi-session",
            "question": "How many different types of citrus fruits have I used?",
        }
    ).model_dump()["target_entity_type"] == "citrus_fruit"
    assert plan_query(
        {
            "question_type": "knowledge-update",
            "question": "Did I switch to more or less water?",
        }
    ).intent == "latest_state_comparison"
    assert plan_query(
        {"question_type": "single-session-preference", "question": "What should I cook?"}
    ).intent == "personalized_advice"
    assert plan_query(
        {"question_type": "single-session-user", "question": "Where did I travel?"}
    ).intent == "unsupported"


def test_extraction_validates_citations_and_reuses_schema_hashed_cache(tmp_path) -> None:
    reference = {
        "haystack_session_ids": ["session-1"],
        "haystack_dates": ["2025-01-01"],
        "haystack_sessions": [
            [
                {"role": "user", "content": "I made orange bitters."},
                {"role": "assistant", "content": "Try grapefruit next."},
            ]
        ],
    }
    digest = source_content_hash(
        "session-1", "2025-01-01", reference["haystack_sessions"][0]
    )
    calls = 0

    def extractor(_prompt: str) -> tuple[str, dict]:
        nonlocal calls
        calls += 1
        payload = {
            "sessions": [
                {
                    "session_id": "session-1",
                    "records": [
                        {
                            "claim_id": "valid-orange",
                            "citation": {
                                "session_id": "model-invented-session",
                                "turn_index": 0,
                                "speaker": "assistant",
                                "session_date": "January 1, 2025",
                                "excerpt": "I definitely made orange bitters yesterday",
                                "source_content_hash": "0" * 64,
                            },
                            "provenance": "user_statement",
                            "primary_mode": "completed",
                            "negated": False,
                            "subject": "user",
                            "predicate": "made",
                            "object": "orange",
                            "object_type": "citrus_fruit",
                            "event_date": None,
                            "numeric": None,
                            "preference": None,
                            "confidence": 0.95,
                        },
                        {
                            "claim_id": "invalid-pomelo",
                            "citation": {
                                "session_id": "session-1",
                                "turn_index": 1,
                                "speaker": "assistant",
                                "session_date": "2025-01-01",
                                "excerpt": "not present in the turn",
                                "source_content_hash": digest,
                            },
                            "provenance": "assistant_suggestion",
                            "primary_mode": "suggested",
                            "negated": False,
                            "subject": "user",
                            "predicate": "try",
                            "object": "pomelo",
                            "object_type": "citrus_fruit",
                            "event_date": None,
                            "numeric": None,
                            "preference": None,
                            "confidence": 0.95,
                        },
                    ],
                }
            ]
        }
        return json.dumps(payload), {"prompt_tokens": 10, "completion_tokens": 5}

    first, first_diagnostics = extract_evidence(
        reference,
        ["session-1"],
        model="fixture-model",
        cache_dir=tmp_path,
        extractor=extractor,
    )
    second, second_diagnostics = extract_evidence(
        reference,
        ["session-1"],
        model="fixture-model",
        cache_dir=tmp_path,
        extractor=extractor,
    )

    assert calls == 1
    assert "valid-orange" in {record.claim_id for record in first}
    valid_orange = next(record for record in first if record.claim_id == "valid-orange")
    assert valid_orange.citation.excerpt == "I made orange bitters."
    assert {record.claim_id for record in second} == {record.claim_id for record in first}
    assert any(record.extraction_origin == "deterministic_envelope" for record in first)
    assert first_diagnostics.invalid_claim_count == 1
    assert first_diagnostics.invalid_by_evidence_type == {"citrus_fruit": 1}
    assert second_diagnostics.cache_hit_count == 1
