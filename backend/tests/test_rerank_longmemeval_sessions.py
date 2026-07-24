from __future__ import annotations

from scripts.backend.rerank_longmemeval_sessions import _chunks, rerank


class FakeCrossEncoder:
    def predict(self, pairs, *, batch_size, show_progress_bar):
        del batch_size, show_progress_bar
        return [
            10.0 if "relevant evidence" in passage else 0.0
            for _, passage in pairs
        ]


def test_chunks_are_bounded_and_overlapping() -> None:
    chunks = _chunks("abcdefghijklmnopqrstuvwxyz", 10, 2)
    assert chunks == ["abcdefghij", "ijklmnopqr", "qrstuvwxyz"]
    assert all(len(chunk) <= 10 for chunk in chunks)


def test_reranker_is_answer_blind_and_preserves_source_metadata() -> None:
    session_ids = ["noise-a", "gold", "noise-b"]
    dataset = [
        {
            "question_id": "q1",
            "haystack_session_ids": session_ids,
            "haystack_dates": ["2024-01-01"] * 3,
            "haystack_sessions": [
                [{"role": "user", "content": "irrelevant"}],
                [{"role": "user", "content": "relevant evidence"}],
                [{"role": "assistant", "content": "irrelevant"}],
            ],
        }
    ]
    retrieval = {
        "results": [
            {
                "question_id": "q1",
                "question": "generic query",
                "question_type": "multi-session",
                "answer": "must not be passed to the model",
                "answer_session_ids": ["gold"],
                "retrieved_session_ids": session_ids,
                "rank": session_ids,
            }
        ]
    }
    report = rerank(
        FakeCrossEncoder(),
        dataset=dataset,
        retrieval=retrieval,
        top_k=2,
        chunk_chars=1_200,
        chunk_overlap=200,
        batch_size=4,
    )
    row = report["results"][0]
    assert "gold" in row["retrieved_session_ids"]
    assert row["answer"] == "must not be passed to the model"
    assert report["protocol"]["answer_or_gold_used_for_ranking"] is False
    assert row["recall_at_k"] == 1.0
