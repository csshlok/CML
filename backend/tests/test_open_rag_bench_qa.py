from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from scripts.backend.evaluate_vault_longmemeval_api import _provider
from scripts.backend.evaluate_vault_open_rag_bench_api import (
    _evidence_context,
    _generate,
    _judge,
    _token_f1,
    _update_progress,
    _validate_retrieval,
)


def _retrieval_row() -> dict:
    return {
        "question_id": "q-1",
        "question": "What happened?",
        "question_type": "extractive",
        "source_modality": "text",
        "retrieved_source_ids": ["orb:paper:section:1"],
        "retrieved_evidence": [
            {
                "source_id": "orb:paper:section:1",
                "doc_id": "paper",
                "section_id": 1,
                "chunk_id": "chunk-1",
                "chunk_index": 0,
                "text": "The measured outcome increased by five percent.",
            }
        ],
    }


def test_retrieval_validation_requires_answer_blind_full_corpus_evidence() -> None:
    report = {
        "dataset": "vectara/open_ragbench",
        "protocol": {"answers_loaded": False, "full_corpus_search": True},
        "results": [_retrieval_row()],
    }

    assert _validate_retrieval(report) == report["results"]


def test_retrieval_validation_rejects_answer_leakage() -> None:
    row = {**_retrieval_row(), "answer": "leaked"}
    report = {
        "dataset": "vectara/open_ragbench",
        "protocol": {"answers_loaded": False, "full_corpus_search": True},
        "results": [row],
    }

    try:
        _validate_retrieval(report)
    except ValueError as exc:
        assert "answer-like" in str(exc)
    else:
        raise AssertionError("answer-bearing retrieval row should be rejected")


def test_qa_progress_failure_is_non_fatal(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    def fail_write(path: Path, payload: dict) -> None:
        raise PermissionError("simulated persistent sharing violation")

    monkeypatch.setattr(
        "scripts.backend.evaluate_vault_open_rag_bench_api._atomic_json",
        fail_write,
    )

    _update_progress(
        tmp_path / "qa.json",
        stage="reader",
        total=10,
        completed=4,
        detail="4/10",
    )

    assert "could not publish QA progress" in capsys.readouterr().err


def test_evidence_context_obeys_budget_and_preserves_citations() -> None:
    row = _retrieval_row()
    row["retrieved_evidence"].append(
        {
            **row["retrieved_evidence"][0],
            "source_id": "orb:paper-2:section:2",
            "doc_id": "paper-2",
            "section_id": 2,
            "text": "Second evidence " * 50,
        }
    )

    context, included = _evidence_context(row, max_chars=150)

    assert len(context) <= 150
    assert "paper=paper" in context
    assert included == ["orb:paper:section:1"]


def test_token_f1_accepts_paraphrase_overlap_without_becoming_binary_judge() -> None:
    exact = _token_f1(
        "The output increased by five percent.",
        "The output increased by five percent.",
    )
    partial = _token_f1(
        "The output increased by five percent.",
        "Output increased five percent after treatment.",
    )
    wrong = _token_f1(
        "The output increased by five percent.",
        "No change was observed.",
    )

    assert exact == 1.0
    assert 0.0 < partial < 1.0
    assert wrong == 0.0


def test_reader_and_judge_checkpoints_resume_without_duplicate_calls(
    tmp_path, monkeypatch
) -> None:
    calls = []

    def fake_chat(_provider, prompt, **_kwargs):
        calls.append(prompt)
        content = "Yes" if "Return exactly Yes or No" in prompt else "Five percent."
        return {
            "choices": [{"finish_reason": "stop", "message": {"content": content}}],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 2,
                "total_tokens": 22,
            },
        }

    monkeypatch.setattr(
        "scripts.backend.evaluate_vault_open_rag_bench_api._chat", fake_chat
    )
    args = Namespace(
        output=tmp_path / "report.json",
        max_context_chars=1_000,
        max_answer_tokens=64,
        timeout=1.0,
        retries=0,
    )
    selected = [
        {
            **_retrieval_row(),
            "section_hit_at_10": 1.0,
            "document_hit_at_10": 1.0,
        }
    ]
    answers = {"q-1": "The outcome increased by five percent."}
    reader_path = tmp_path / "reader.jsonl"
    judge_path = tmp_path / "judge.jsonl"
    provider = _provider("kimi", "kimi-k2.6")

    hypotheses = _generate(
        args, provider, selected, answers, reader_path, "reader-fingerprint"
    )
    first_call_count = len(calls)
    resumed = _generate(
        args, provider, selected, answers, reader_path, "reader-fingerprint"
    )
    judged = _judge(
        args,
        provider,
        hypotheses,
        judge_path,
        "judge-fingerprint",
        stage="primary_judge",
    )
    judged_call_count = len(calls)
    resumed_judgments = _judge(
        args,
        provider,
        hypotheses,
        judge_path,
        "judge-fingerprint",
        stage="primary_judge",
    )

    assert first_call_count == 1
    assert resumed == hypotheses
    assert judged[0]["autoeval_label"]["label"] is True
    assert judged_call_count == 2
    assert resumed_judgments == judged
    assert len(calls) == judged_call_count
