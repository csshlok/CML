from __future__ import annotations

import pytest

from scripts.backend.benchmark_fact_extraction_local import (
    _compact_chunks,
    _metrics,
    _session_rows,
)

pytestmark = pytest.mark.skip(
    reason="DEAD EXPERIMENT: Qwen fact extraction reduced accuracy versus raw RAG"
)


def test_session_rows_use_only_fixed_retrieval_ids_and_keep_rank_order() -> None:
    reference = {
        "haystack_session_ids": ["a", "b", "c"],
        "haystack_dates": ["2026-01-01", "2026-01-02", "2026-01-03"],
        "haystack_sessions": [[{"role": "user", "content": value}] for value in "abc"],
    }
    rows = _session_rows(reference, ["c", "a"])
    assert [row["session_id"] for row in rows] == ["c", "a"]


def test_metrics_report_paired_fact_wins_and_losses() -> None:
    rows = [
        {
            "question_id": "q1",
            "arm": "raw",
            "judge_label": False,
            "token_f1": 0.1,
            "gold_contained": False,
            "reader_wall_seconds": 1,
        },
        {
            "question_id": "q2",
            "arm": "raw",
            "judge_label": True,
            "token_f1": 0.8,
            "gold_contained": True,
            "reader_wall_seconds": 1,
        },
        {
            "question_id": "q1",
            "arm": "facts-only",
            "judge_label": True,
            "token_f1": 0.7,
            "gold_contained": True,
            "reader_wall_seconds": 1,
        },
        {
            "question_id": "q2",
            "arm": "facts-only",
            "judge_label": False,
            "token_f1": 0.2,
            "gold_contained": False,
            "reader_wall_seconds": 1,
        },
    ]
    metrics = _metrics(rows)
    assert metrics["facts-only"]["wins_vs_raw"] == 1
    assert metrics["facts-only"]["losses_vs_raw"] == 1


def test_compact_chunks_preserve_original_turn_indices() -> None:
    session = {
        "turns": [
            {"role": "user", "content": "a" * 6},
            {"role": "assistant", "content": "b" * 3},
        ]
    }
    chunks = _compact_chunks(session, 4)
    assert [turn["turn_index"] for chunk in chunks for turn in chunk] == [0, 0, 1]
