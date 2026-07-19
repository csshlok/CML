from __future__ import annotations

from backend.app.core.claim_evidence_packing import (
    CLAIM_PACKER_VERSION,
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
            " ".join(
                f"I discussed deployment target {index} item {item}."
                for item in range(20)
            )
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
        {"question_id": row["question_id"], "autoeval_label": {"label": True}}
        for row in hypotheses
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
