from __future__ import annotations

import pytest

from backend.app.core.claim_evidence_packing import Claim
from backend.app.core.multi_session_ledger import (
    build_evidence_ledger,
    ledger_anchor_keys,
)


def _claim(key: int, date: str, text: str, *, speaker: str = "user") -> Claim:
    return Claim(
        session_id=f"session-{key}",
        date=date,
        retrieval_rank=key,
        turn_index=0,
        sentence_index=0,
        speaker=speaker,
        text=text,
        tokens=10,
    )


def test_ledger_distinguishes_cumulative_snapshot_from_delta() -> None:
    claims = [
        _claim(0, "2025-01-01", "I attended three support group sessions."),
        _claim(1, "2025-02-01", "I now remember attending five sessions in total."),
        _claim(2, "2025-03-01", "I attended another session."),
    ]
    plan, entries = build_evidence_ledger(
        "How many support group sessions did I attend?", "knowledge-update", claims
    )

    assert plan.operation == "aggregate"
    assert entries[claims[0].key].numeric_role == "cumulative_snapshot"
    assert entries[claims[1].key].numeric_role == "cumulative_snapshot"
    assert entries[claims[2].key].numeric_role == "unknown"
    assert claims[1].key in ledger_anchor_keys(entries, plan)


@pytest.mark.skip(
    reason="DEAD EXPERIMENT: alternate numeric semantics failed reader accuracy gates"
)
def test_legacy_numeric_semantics_remain_available_for_paired_reader_benchmark() -> None:
    claim = _claim(0, "2025-01-01", "I attended three support group sessions.")

    _, current = build_evidence_ledger("How many sessions did I attend?", "multi-session", [claim])
    _, legacy = build_evidence_ledger(
        "How many sessions did I attend?",
        "multi-session",
        [claim],
        numeric_semantics="legacy",
    )

    assert current[claim.key].numeric_role == "delta"
    assert legacy[claim.key].numeric_role == "cumulative_snapshot"


def test_ledger_preserves_dated_start_and_end_anchors() -> None:
    claims = [
        _claim(0, "2025-05-15", "I started my Yosemite camping trip today."),
        _claim(1, "2025-05-17", "I got back from my Yosemite camping trip today."),
    ]
    plan, entries = build_evidence_ledger(
        "How many days was my Yosemite camping trip?", "temporal-reasoning", claims
    )

    assert plan.operation == "duration"
    assert entries[claims[0].key].event_role == "start"
    assert entries[claims[1].key].event_role == "end"
    assert set(ledger_anchor_keys(entries, plan)) == {claim.key for claim in claims}


def test_assistant_numbers_are_lower_authority_for_user_facts() -> None:
    user = _claim(0, "2025-01-01", "I attended five sessions.")
    assistant = _claim(
        1,
        "2025-01-02",
        "You could attend another eight sessions.",
        speaker="assistant",
    )
    plan, entries = build_evidence_ledger(
        "How many sessions did I attend?", "multi-session", [user, assistant]
    )

    assert entries[user.key].provenance_authority == 1
    assert entries[assistant.key].provenance_authority == 0
    assert entries[assistant.key].assertion_mode == "suggested"
