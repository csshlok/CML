import json
from pathlib import Path

import scripts.backend.atomic_io as atomic_io
from scripts.backend.benchmark_vault_open_rag_bench import (
    _deduplicated_rankings,
    _evaluate,
    _first_rank,
    _parse_source_id,
    _rank_metrics,
    _section_text,
    _select_questions,
    _source_id,
    _write_progress,
)


def test_section_adapter_indexes_text_and_tables_but_never_images() -> None:
    marker = "data:image/png;base64,SECRET"
    rendered = _section_text(
        {
            "text": "Evidence paragraph.",
            "tables": {"table_1": "| A | B |\n| - | - |\n| 1 | 2 |"},
            "images": {"image.png": marker},
        }
    )

    assert "Evidence paragraph." in rendered
    assert "Table table_1" in rendered
    assert "| 1 | 2 |" in rendered
    assert marker not in rendered
    assert "image.png" not in rendered


def test_source_id_round_trip_preserves_gold_section_identity() -> None:
    source_id = _source_id("2410.14077v2", 17)

    assert source_id == "orb:2410.14077v2:section:17"
    assert _parse_source_id(source_id) == ("2410.14077v2", 17)


def test_seeded_query_selection_is_reproducible_and_answer_blind() -> None:
    queries = {
        f"q-{number}": {
            "query": f"Question {number}",
            "type": "extractive",
            "source": "text",
            "answer": f"must not be copied {number}",
        }
        for number in range(20)
    }

    first = _select_questions(queries, selection="seeded", count=5, seed=42)
    second = _select_questions(queries, selection="seeded", count=5, seed=42)

    assert first == second
    assert len(first) == 5
    assert all("answer" not in item for item in first)


def test_single_relevant_rank_metrics_are_exact() -> None:
    assert _first_rank(["a", "gold", "b"], "gold") == 2
    assert _first_rank(["a"], "gold") is None
    assert _rank_metrics(2, 5) == {
        "hit_at_5": 1.0,
        "mrr_at_5": 0.5,
        "ndcg_at_5": 1.0 / 1.584962500721156,
    }
    assert _rank_metrics(7, 5) == {
        "hit_at_5": 0.0,
        "mrr_at_5": 0.0,
        "ndcg_at_5": 0.0,
    }


def test_document_ranking_continues_past_first_top_k_sections() -> None:
    raw = [
        _source_id("paper-a", 0),
        _source_id("paper-a", 1),
        _source_id("paper-b", 0),
        _source_id("paper-c", 0),
    ]

    sections, documents = _deduplicated_rankings(raw, top_k=2)

    assert sections == [_source_id("paper-a", 0), _source_id("paper-a", 1)]
    assert documents == ["paper-a", "paper-b"]


def test_atomic_writer_retries_transient_replace_failure(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "progress.json"
    real_replace = atomic_io.os.replace
    attempts = 0

    def flaky_replace(source: Path, destination: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("simulated sharing violation")
        real_replace(source, destination)

    monkeypatch.setattr(atomic_io.os, "replace", flaky_replace)
    monkeypatch.setattr(atomic_io.time, "sleep", lambda _: None)

    atomic_io.atomic_write_text(output, '{"completed": 1}')

    assert attempts == 3
    assert json.loads(output.read_text(encoding="utf-8")) == {"completed": 1}
    assert not list(tmp_path.glob("*.tmp"))


def test_retrieval_progress_failure_is_non_fatal(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    def fail_write(path: Path, text: str) -> None:
        raise PermissionError("simulated persistent sharing violation")

    monkeypatch.setattr(
        "scripts.backend.benchmark_vault_open_rag_bench.atomic_write_text",
        fail_write,
    )

    _write_progress(
        tmp_path / "retrieval.json",
        total=10,
        completed=4,
        detail="4/10",
    )

    assert "could not publish retrieval progress" in capsys.readouterr().err


def test_evaluation_resumes_valid_checkpoint_without_retrieving_again(
    tmp_path: Path, monkeypatch
) -> None:
    fingerprint = "resume-fingerprint"
    question = {
        "question_id": "q-1",
        "question": "What happened?",
        "question_type": "extractive",
        "source_modality": "text",
    }
    checkpoint_row = {
        **question,
        "run_fingerprint": fingerprint,
        "latency_seconds": 0.5,
        "section_hit_at_10": 1.0,
        "document_hit_at_10": 1.0,
        "raw_chunk_section_hit_at_10": 1.0,
    }
    checkpoint = tmp_path / "retrieval.retrieval.jsonl"
    checkpoint.write_text(json.dumps(checkpoint_row) + "\n", encoding="utf-8")
    monkeypatch.setenv("CML_EMBEDDING_MODEL", str(tmp_path / "model"))
    monkeypatch.setenv("CML_EMBEDDING_CACHE_DIR", str(tmp_path / "cache"))

    class FakeModel:
        device = "cuda:0"

    monkeypatch.setattr(
        "backend.app.core.embeddings._get_sentence_transformer",
        lambda *_: FakeModel(),
    )

    def unexpected_retrieval(*args, **kwargs):
        raise AssertionError("a valid checkpoint row must not be retrieved again")

    monkeypatch.setattr(
        "backend.app.core.retrieval_scoring.scoring_ledger",
        unexpected_retrieval,
    )

    rows, summary = _evaluate(
        [question],
        {},
        top_k=10,
        checkpoint_path=checkpoint,
        output_path=tmp_path / "retrieval.json",
        run_fingerprint=fingerprint,
    )

    assert rows == [checkpoint_row]
    assert summary["question_count"] == 1
    assert len(checkpoint.read_text(encoding="utf-8").splitlines()) == 1
