from __future__ import annotations

import pytest

from backend.app.core.claim_evidence_packing import (
    CLAIM_PACKER_VERSION,
    CONSOLIDATED_CLAIM_PACKER_VERSION,
    SessionEnvelope,
    pack_claim_evidence,
)
from backend.app.core.context_reduction import estimate_tokens
from scripts.backend.evaluate_vault_longmemeval_api import _budget_accuracy_metrics
from scripts.backend.evaluate_vault_longmemeval_api import _pack_reader_context


def _session(session_id: str, rank: int, text: str, *, role: str = "user") -> SessionEnvelope:
    return SessionEnvelope(
        session_id=session_id,
        date=f"2025-01-{rank + 1:02d}",
        turns=[{"role": role, "content": text}],
        retrieval_rank=rank,
    )


def test_claim_packer_respects_budget_and_preserves_session_coverage() -> None:
    sessions = [
        _session(
            f"session-{index}",
            index,
            " ".join(f"I discussed deployment target {index} item {item}." for item in range(20))
            + f"The release marker is value {index}.",
        )
        for index in range(5)
    ]
    context, meta = pack_claim_evidence(
        question="What release markers changed across deployment sessions?",
        sessions=sessions,
        token_budget=300,
        question_type="multi-session",
    )

    assert meta["packing"] == CLAIM_PACKER_VERSION
    assert estimate_tokens(context) <= 300
    assert meta["included_session_count"] == 5
    assert meta["selected_claim_count"] < meta["candidate_claim_count"]
    assert meta["context_truncated"] is True
    assert all(f"Session session-{index}" in context for index in range(5))


def test_claim_packer_preserves_speaker_and_sentence_citations() -> None:
    context, meta = pack_claim_evidence(
        question="What did the assistant recommend for coffee?",
        sessions=[
            _session(
                "session-a",
                0,
                "Use five ounces of water. Keep the temperature below boiling.",
                role="assistant",
            )
        ],
        token_budget=120,
        question_type="single-session-assistant",
    )
    assert "[assistant turn 0 sentence 0]" in context
    assert "five ounces" in context
    assert meta["omitted_session_ids"] == []


def test_consolidated_packer_splits_compound_claims_and_preserves_sources() -> None:
    context, meta = pack_claim_evidence(
        question="How did my preference for tea change?",
        sessions=[
            _session("session-old", 0, "I love tea, but I hate coffee."),
            SessionEnvelope(
                session_id="session-new",
                date="2025-03-01",
                turns=[{"role": "user", "content": "I no longer like tea."}],
                retrieval_rank=1,
            ),
        ],
        token_budget=240,
        question_type="single-session-preference",
        consolidate=True,
    )

    assert meta["packing"] == CONSOLIDATED_CLAIM_PACKER_VERSION
    assert "I love tea" in context
    assert "I no longer like tea" in context
    assert "I love tea, but I hate coffee" not in context
    assert "navigation only" in context
    assert meta["ledger"]["consolidation_group_count"] == 1
    assert meta["ledger"]["conflicting_preference_group_count"] == 1
    assert meta["ledger"]["cross_session_consolidated_claim_count"] == 2


@pytest.mark.skip(reason="DEAD EXPERIMENT: reader-evidence presentation failed accuracy gates")
def test_reader_evidence_packet_makes_temporal_updates_explicit_and_chronological() -> None:
    context, _ = pack_claim_evidence(
        question="What is my current reading choice?",
        sessions=[
            _session("old", 0, "I am currently reading Dune."),
            SessionEnvelope(
                session_id="new",
                date="2025-02-01",
                turns=[{"role": "user", "content": "I am now reading Foundation."}],
                retrieval_rank=1,
            ),
        ],
        token_budget=220,
        question_type="knowledge-update",
        consolidate=True,
        presentation="reader_evidence",
    )

    assert "task: latest state" in context
    assert context.index("Session old") < context.index("Session new")
    assert context.index("[E1]") < context.index("[E2]")
    assert "Dune" in context and "Foundation" in context
    assert "{current" not in context


@pytest.mark.skip(reason="DEAD EXPERIMENT: reader-evidence presentation failed accuracy gates")
def test_reader_evidence_packet_distinguishes_running_totals_from_contributions() -> None:
    context, _ = pack_claim_evidence(
        question="How many workshops have I attended in total?",
        sessions=[
            _session("first", 0, "I attended two workshops."),
            _session("latest", 1, "I have attended five workshops so far."),
        ],
        token_budget=220,
        question_type="multi-session",
        presentation="reader_evidence",
    )

    assert "task: aggregate" in context
    assert "increment=separate contribution" in context
    assert "total=running total" in context
    assert "[done; increment]" in context
    assert "[done; total]" in context


@pytest.mark.skip(reason="DEAD EXPERIMENT: reader-evidence presentation failed accuracy gates")
def test_reader_evidence_packet_scales_ids_without_repeating_claim_text() -> None:
    sessions = [
        _session(f"session-{index}", index, f"I completed project milestone {index}.")
        for index in range(12)
    ]

    context, meta = pack_claim_evidence(
        question="Which project milestones did I complete?",
        sessions=sessions,
        token_budget=600,
        question_type="multi-session",
        presentation="reader_evidence",
    )

    assert meta["included_session_count"] == 12
    for index in range(1, 13):
        assert context.count(f"[E{index}]") == 1
    for index in range(12):
        assert context.count(f"I completed project milestone {index}.") == 1


@pytest.mark.skip(reason="DEAD EXPERIMENT: reader-evidence presentation failed accuracy gates")
def test_reader_evidence_packet_does_not_force_task_labels_onto_generic_text() -> None:
    context, _ = pack_claim_evidence(
        question="What color was discussed?",
        sessions=[_session("generic", 0, "The notebook was blue.")],
        token_budget=100,
        question_type="single-session-user",
        presentation="reader_evidence",
    )

    assert "The notebook was blue." in context
    assert "[done" not in context
    assert "[total" not in context
    assert "[start" not in context


@pytest.mark.skip(reason="DEAD EXPERIMENT: paired reader benchmark is retired")
def test_legacy_presentation_is_frozen_for_local_ab_comparison() -> None:
    context, meta = pack_claim_evidence(
        question="How many workshops did I attend?",
        sessions=[_session("legacy", 0, "I attended three workshops.")],
        token_budget=120,
        question_type="multi-session",
        presentation="legacy",
    )

    assert meta["packing"] == "claim-first-cited-v3-ledger"
    assert "[user turn 0 sentence 0]" in context
    assert "{completed,cumulative_snapshot}" in context
    assert "Evidence packet - chronological" not in context


def test_budget_accuracy_reports_over_and_under_groups() -> None:
    hypotheses = [
        {
            "question_id": "over-correct",
            "reader_prompt_tokens": 10_500,
            "reader_attempt_history": [
                {"usage": {"prompt_tokens": 10_500}},
            ],
            "prepack_prompt_tokens_estimate": 20_000,
            "packed_prompt_tokens_estimate": 9_500,
        },
        {
            "question_id": "over-wrong",
            "reader_prompt_tokens": 11_000,
            "reader_attempt_history": [
                {"usage": {"prompt_tokens": 6_000}},
                {"usage": {"prompt_tokens": 6_000}},
            ],
            "prepack_prompt_tokens_estimate": 18_000,
            "packed_prompt_tokens_estimate": 9_600,
        },
        {
            "question_id": "under-correct",
            "reader_prompt_tokens": 8_000,
            "reader_attempt_history": [
                {"usage": {"prompt_tokens": 8_000}},
            ],
            "prepack_prompt_tokens_estimate": 8_000,
            "packed_prompt_tokens_estimate": 7_500,
        },
    ]
    primary = [
        {"question_id": "over-correct", "autoeval_label": {"label": True}},
        {"question_id": "over-wrong", "autoeval_label": {"label": False}},
        {"question_id": "under-correct", "autoeval_label": {"label": True}},
    ]
    independent = [
        {"question_id": row["question_id"], "autoeval_label": {"label": True}} for row in hypotheses
    ]
    metrics = _budget_accuracy_metrics(
        hypotheses,
        primary,
        independent,
        budget=10_000,
    )
    actual = metrics["actual_reader_prompt"]
    assert actual["over_budget"]["question_count"] == 2
    assert actual["over_budget"]["primary_accuracy_percent"] == 50.0
    assert actual["under_or_at_budget"]["question_count"] == 1
    assert actual["under_or_at_budget"]["primary_accuracy_percent"] == 100.0
    assert metrics["prepack_complete_session_prompt"]["over_budget"]["question_count"] == 2
    assert metrics["packed_prompt_estimate"]["over_budget"]["question_count"] == 0
    billed = metrics["all_reader_attempts_billed"]
    assert billed["over_budget"]["question_count"] == 2
    assert billed["under_or_at_budget"]["question_count"] == 1


def test_reader_context_reserves_tokenizer_safety_margin() -> None:
    from types import SimpleNamespace

    reference = {
        "question": "What deployment marker was discussed?",
        "question_type": "single-session-user",
        "haystack_session_ids": ["session-a"],
        "haystack_dates": ["2025-01-01"],
        "haystack_sessions": [[{"role": "user", "content": "Marker alpha was deployed. " * 400}]],
    }
    _, meta = _pack_reader_context(
        SimpleNamespace(
            context_packing="claim-first-v1",
            reader_token_budget=10_000,
            reader_budget_safety_factor=0.8,
            max_context_chars=500_000,
            reader_prompt="typed-v1",
        ),
        reference,
        ["session-a"],
    )

    assert meta["packing_target_tokens_estimate"] == 8_000
    assert meta["packed_prompt_tokens_estimate"] <= 8_000
