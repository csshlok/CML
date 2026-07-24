from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.backend.benchmark_vault_longmemeval import _prepare
from scripts.backend.benchmark_vault_memory import _flatten_locomo, _select_questions
from scripts.backend.benchmark_vault_locomo_reranker import rerank_with_cross_encoder
from scripts.backend.check_vault_memory_regression import (
    canonical_question_ids,
    compare_reports,
)
from scripts.backend.evaluate_vault_locomo_api import (
    ProductionTemporalContext,
    _official_locomo_score,
    _parse_binary_verdict,
)
from scripts.backend.evaluate_vault_longmemeval_api import _ensure_manifest
from scripts.backend.evaluate_vault_longmemeval_api import (
    Provider,
    ProviderContentFilterError,
    _chat,
    _generate as generate_longmemeval,
    _holdout_gate_metrics,
    _usage_attempts,
)
from scripts.backend.evaluate_vault_longmemeval_local import (
    _pack_retrieved_context,
    _reader_route,
    _routed_answer_prompt,
    _structured_answer_prompt,
    _structured_answer_prompt_v2,
)
from backend.app.core.embeddings import _embedding_safe_chunks


_TYPED_EVIDENCE_FIXTURE = (
    Path(__file__).parent / "fixtures" / "typed_evidence_scoping_cases.json"
)


def _typed_evidence_cases() -> dict[str, dict]:
    payload = json.loads(_TYPED_EVIDENCE_FIXTURE.read_text(encoding="utf-8"))
    return {case["question_id"]: case for case in payload["cases"]}


class _IdentityStemmer:
    @staticmethod
    def stem(value: str) -> str:
        return value


class _WhitespaceTokenizer:
    @staticmethod
    def num_special_tokens_to_add(*, pair: bool) -> int:
        assert pair is False
        return 2

    @staticmethod
    def __call__(text: str, **kwargs) -> dict:
        import re

        matches = list(re.finditer(r"\S+", text))
        payload = {"input_ids": list(range(len(matches)))}
        if kwargs.get("return_offsets_mapping"):
            payload["offset_mapping"] = [(match.start(), match.end()) for match in matches]
        return payload


class _CharacterTokenizer(_WhitespaceTokenizer):
    @staticmethod
    def __call__(text: str, **kwargs) -> dict:
        offsets = [(index, index + 1) for index, value in enumerate(text) if not value.isspace()]
        payload = {"input_ids": list(range(len(offsets)))}
        if kwargs.get("return_offsets_mapping"):
            payload["offset_mapping"] = offsets
        return payload


class _FakeCrossEncoder:
    @staticmethod
    def predict(pairs, **kwargs):
        assert kwargs["show_progress_bar"] is False
        return [float("gold evidence" in passage) for _, passage in pairs]


def test_locomo_production_temporal_context_uses_shared_preference_scope(tmp_path: Path) -> None:
    dataset = [
        {
            "sample_id": "sample-1",
            "conversation": {
                "session_1_date_time": "10:00 AM on 01 January, 2025",
                "session_1": [
                    {"speaker": "Melanie", "text": "I prefer tea.", "dia_id": "d1"}
                ],
                "session_2_date_time": "10:00 AM on 01 February, 2025",
                "session_2": [
                    {"speaker": "Melanie", "text": "I avoid coffee.", "dia_id": "d2"}
                ],
            },
        }
    ]
    adapter = ProductionTemporalContext(
        dataset=dataset,
        dataset_sha256="fixture",
        database_path=tmp_path / "temporal.sqlite3",
    )
    try:
        unchanged, bounded = adapter.context(
            sample_id="sample-1",
            question="What was Melanie's favorite childhood book?",
            retrieved_context="ordinary retrieval",
        )
        augmented, aggregate = adapter.context(
            sample_id="sample-1",
            question="What are Melanie's preferences?",
            retrieved_context="ordinary retrieval",
        )
    finally:
        adapter.close()

    assert unchanged == "ordinary retrieval"
    assert bounded["contract_injected"] is False
    assert bounded["memory_item_count"] == 0
    assert bounded["added_context_chars"] == 0
    assert aggregate["contract_injected"] is True
    assert aggregate["memory_item_count"] >= 1
    assert aggregate["added_context_chars"] > 0
    assert "Vault structured memory" in augmented


def test_typed_evidence_scoping_fixture_enforces_architecture_boundary() -> None:
    cases = _typed_evidence_cases()

    citrus = cases["c4a1ceb8"]
    included_citrus = {
        claim["object"]
        for claim in citrus["evidence"]
        if claim["speaker"] == "user"
        and claim["provenance"] == "user_statement"
        and claim["assertion_mode"] == "completed"
        and claim["object_type"] == "citrus_fruit"
    }
    assert included_citrus == {"lemon", "lime", "orange"}
    assert citrus["deterministic_result"]["value"] == len(included_citrus) == 3
    assert "citrus-grapefruit-suggestion" in citrus["deterministic_result"][
        "excluded_claim_ids"
    ]

    ratio = cases["6071bd76"]
    snapshots = sorted(ratio["evidence"], key=lambda claim: claim["session_date"])
    previous = snapshots[-2]["numeric"]["value"]
    current = snapshots[-1]["numeric"]["value"]
    assert current - previous == -1
    assert ratio["deterministic_result"]["direction"] == "less"

    slow_cooker = cases["caf03d32"]
    known_claim_ids = {claim["claim_id"] for claim in slow_cooker["evidence"]}
    required_claim_ids = set(
        slow_cooker["deterministic_result"]["required_anchor_claim_ids"]
    )
    assert required_claim_ids == {
        "slow-cooker-beef-stew-success",
        "slow-cooker-yogurt-goal",
    }
    assert required_claim_ids <= known_claim_ids
    assert slow_cooker["deterministic_result"]["answer_is_unambiguous"] is False


def test_embedding_safe_chunks_preserve_text_and_fit_token_budget() -> None:
    source_text = " ".join(f"word-{index}" for index in range(600))
    chunks = _embedding_safe_chunks(
        [
            {
                "text": source_text,
                "content_profile": "conversation",
                "chunk_strategy": "turn_group",
                "chunk_meta_json": '{"source":"fixture"}',
            }
        ],
        tokenizer=_WhitespaceTokenizer(),
        max_seq_length=256,
    )

    assert len(chunks) == 3
    assert all(len(chunk["text"].split()) + 2 <= 240 for chunk in chunks)
    assert chunks[0]["text"].startswith("word-0 ")
    assert chunks[-1]["text"].endswith(" word-599")
    recovered = {
        value for chunk in chunks for value in str(chunk["text"]).split()
    }
    assert recovered == set(source_text.split())
    assert all(chunk["chunk_strategy"] == "turn_group" for chunk in chunks)
    metadata = [json.loads(chunk["chunk_meta_json"]) for chunk in chunks]
    assert [item["embedding_segment_index"] for item in metadata] == [0, 1, 2]
    assert all(item["embedding_segment_count"] == 3 for item in metadata)
    assert all(item["embedding_original_content_tokens"] == 600 for item in metadata)


def test_embedding_safe_chunks_leave_short_structural_chunk_unchanged() -> None:
    chunk = {
        "text": "short structural chunk",
        "content_profile": "code",
        "chunk_strategy": "python_ast_symbol",
        "chunk_meta_json": "{}",
    }

    assert _embedding_safe_chunks(
        [chunk], tokenizer=_WhitespaceTokenizer(), max_seq_length=256
    ) == [chunk]


def test_embedding_safe_chunks_split_a_single_oversized_word() -> None:
    chunks = _embedding_safe_chunks(
        [
            {
                "text": "x" * 600,
                "content_profile": "log",
                "chunk_strategy": "log_event",
                "chunk_meta_json": "{}",
            }
        ],
        tokenizer=_CharacterTokenizer(),
        max_seq_length=256,
    )

    assert len(chunks) == 3
    assert all(len(chunk["text"]) + 2 <= 240 for chunk in chunks)
    assert chunks[0]["text"].startswith("x")
    assert chunks[-1]["text"].endswith("x")


def test_memory_regression_selection_is_order_independent() -> None:
    rows = [{"question_id": f"q{index}"} for index in range(20)]

    assert canonical_question_ids(rows, 10) == canonical_question_ids(
        list(reversed(rows)), 10
    )


def test_memory_regression_gate_rejects_recall_loss() -> None:
    protocol = {"dataset_sha256": "abc", "selection_mode": "all", "seed": None}
    baseline = {
        "protocol": protocol,
        "results": [
            {"question_id": "q1", "recall_at_k": 1.0, "any_evidence_at_k": True},
            {"question_id": "q2", "recall_at_k": 1.0, "any_evidence_at_k": True},
        ],
    }
    candidate = {
        "protocol": protocol,
        "results": [
            {"question_id": "q1", "recall_at_k": 0.0, "any_evidence_at_k": False},
            {"question_id": "q2", "recall_at_k": 1.0, "any_evidence_at_k": True},
        ],
    }

    with pytest.raises(RuntimeError, match="memory retrieval regression"):
        compare_reports(baseline, candidate, count=2)


def test_cross_encoder_reranker_uses_local_candidate_text() -> None:
    reranked = rerank_with_cross_encoder(
        _FakeCrossEncoder(),
        question="What happened?",
        candidates=[
            {"source_id": "s1", "evidence_id": "e1"},
            {"source_id": "s2", "evidence_id": "e2"},
        ],
        text_by_source_id={"s1": "noise", "s2": "gold evidence"},
        top_k=1,
        batch_size=8,
    )

    assert [row["source_id"] for row in reranked] == ["s2"]
    assert reranked[0]["reranker_score"] == 1.0


def test_locomo_flatten_preserves_protocol_fields_and_image_caption() -> None:
    dataset = [
        {
            "sample_id": "conv-1",
            "conversation": {
                "session_1_date_time": "1 January 2025",
                "session_1": [
                    {
                        "dia_id": "D1:1",
                        "speaker": "A",
                        "text": "Look at this.",
                        "blip_caption": "a red bicycle",
                    }
                ],
            },
            "qa": [
                {
                    "question": "What was shown?",
                    "category": 4,
                    "answer": "a red bicycle",
                    "evidence": ["D1:1"],
                },
                {
                    "question": "What was not discussed?",
                    "category": 5,
                    "adversarial_answer": "a boat",
                    "evidence": ["D1:1"],
                },
            ],
        }
    ]

    documents, questions = _flatten_locomo(dataset)

    assert documents[0]["cluster_id"] == "locomo:conv-1"
    assert "Shared image: a red bicycle" in documents[0]["text"]
    assert questions[0]["answer"] == "a red bicycle"
    assert questions[1]["answer"] is None
    assert questions[1]["adversarial_answer"] == "a boat"


def test_locomo_standard_and_adversarial_selection_are_separate() -> None:
    questions = [
        {"question_id": f"q{category}", "category": category}
        for category in (1, 2, 3, 4, 5)
    ]

    standard = _select_questions(
        questions, 99, category_scope="standard", selection="all", seed=42
    )
    adversarial = _select_questions(
        questions, 99, category_scope="adversarial", selection="all", seed=42
    )

    assert [row["category"] for row in standard] == [1, 2, 3, 4]
    assert [row["category"] for row in adversarial] == [5]


def test_longmemeval_all_selection_preserves_official_file_order() -> None:
    rows = [
        {
            "question_id": f"q{index}",
            "question_type": "single-session-user",
            "question": "Question?",
            "answer": "Answer",
            "answer_session_ids": [f"s{index}"],
            "haystack_session_ids": [f"s{index}"],
            "haystack_dates": ["2025-01-01"],
            "haystack_sessions": [[{"role": "user", "content": "text"}]],
        }
        for index in range(3)
    ]

    _, questions = _prepare(rows, 1, selection="all", seed=999)

    assert [row["question_id"] for row in questions] == ["q0", "q1", "q2"]


def test_longmemeval_context_packing_never_slices_a_session() -> None:
    reference = {
        "haystack_session_ids": ["s1", "s2"],
        "haystack_dates": ["2025-01-01", "2025-01-02"],
        "haystack_sessions": [
            [{"role": "user", "content": "first"}],
            [{"role": "user", "content": "second session is longer"}],
        ],
    }
    first_only, first_meta = _pack_retrieved_context(reference, ["s1"], 10_000)
    context, metadata = _pack_retrieved_context(
        reference, ["s1", "s2"], len(first_only) + 1
    )

    assert context == first_only
    assert context.endswith("first")
    assert metadata["context_truncated"] is True
    assert metadata["included_session_ids"] == ["s1"]
    assert metadata["omitted_session_ids"] == ["s2"]
    assert first_meta["context_truncated"] is False


def test_structured_reader_prompt_exposes_temporal_and_conflict_rules() -> None:
    prompt = _structured_answer_prompt(
        {
            "question": "What does the user prefer now?",
            "question_date": "2025-02-01",
            "question_type": "single-session-preference",
        },
        "Session s1 — 2025-01-01\nuser: tea",
    )

    assert "oldest to newest" in prompt
    assert "prefer the latest explicit update" in prompt
    assert "repeated preferences from one-off events" in prompt
    assert "Question type: single-session-preference" in prompt


def test_structured_reader_v2_distinguishes_agreement_conflict_and_enumeration() -> None:
    prompt = _structured_answer_prompt_v2(
        {
            "question": "How many times did the user exercise?",
            "question_date": "2025-02-01",
            "question_type": "multi-session",
        },
        "Session s1 - 2025-01-01\nuser: exercised",
    )

    assert "Agreement:" in prompt
    assert "Conflict or update:" in prompt
    assert "Enumeration:" in prompt
    assert "Count repeated occurrences" in prompt
    assert "Do not treat contributions as conflicts" in prompt
    assert "unless the question explicitly asks for distinct categories" in prompt


def test_v2_holdout_gate_metrics_keep_retention_and_recovery_separate() -> None:
    selected = [
        {
            "question_id": "control",
            "v2_holdout_stratum": "baseline_correct_enumeration",
            "baseline_primary_correct": True,
            "baseline_independent_correct": True,
        },
        {
            "question_id": "recovery",
            "v2_holdout_stratum": "baseline_incorrect_recovery",
            "baseline_primary_correct": False,
            "baseline_independent_correct": False,
        },
    ]
    primary = [
        {"question_id": "control", "autoeval_label": {"label": True}},
        {"question_id": "recovery", "autoeval_label": {"label": False}},
    ]
    independent = [
        {"question_id": "control", "autoeval_label": {"label": True}},
        {"question_id": "recovery", "autoeval_label": {"label": False}},
    ]

    metrics = _holdout_gate_metrics(
        selected,
        primary,
        independent,
        {"pass_gates": {"required_retained": 1, "required_recovered": 1}},
    )

    assert metrics is not None
    assert metrics["retention_gate_passed"] is True
    assert metrics["recovery_gate_passed"] is False
    assert metrics["promotion_gate_passed"] is False


def test_routed_holdout_gate_metrics_include_efficiency_and_route_checks() -> None:
    selected = [
        {
            "question_id": "control",
            "holdout_stratum": "baseline_correct_preference",
            "baseline_primary_correct": True,
            "baseline_independent_correct": True,
            "baseline_reader_prompt_tokens": 100,
            "baseline_reader_wall_seconds": 10.0,
            "expected_reader_route": "preference",
        },
        {
            "question_id": "recovery",
            "holdout_stratum": "baseline_incorrect_aggregation",
            "baseline_primary_correct": False,
            "baseline_independent_correct": False,
            "baseline_reader_prompt_tokens": 100,
            "baseline_reader_wall_seconds": 10.0,
            "expected_reader_route": "aggregation",
        },
    ]
    judged = [
        {"question_id": "control", "autoeval_label": {"label": True}},
        {"question_id": "recovery", "autoeval_label": {"label": True}},
    ]
    hypotheses = [
        {
            "question_id": "control",
            "reader_route": "preference",
            "reader_wall_seconds": 8.0,
            "reader_attempt_history": [{"usage": {"prompt_tokens": 90}}],
        },
        {
            "question_id": "recovery",
            "reader_route": "aggregation",
            "reader_wall_seconds": 8.0,
            "reader_attempt_history": [{"usage": {"prompt_tokens": 90}}],
        },
    ]

    metrics = _holdout_gate_metrics(
        selected,
        judged,
        judged,
        {
            "pass_gates": {
                "required_retained": 1,
                "required_recovered": 1,
                "minimum_control_stratum_retention": 0.8,
                "minimum_judge_agreement": 0.9,
                "maximum_prompt_token_ratio": 1.1,
                "maximum_mean_latency_ratio": 1.5,
            }
        },
        hypotheses,
    )

    assert metrics is not None
    assert metrics["promotion_gate_passed"] is True
    assert metrics["efficiency"]["prompt_token_ratio"] == pytest.approx(0.9)
    assert metrics["efficiency"]["mean_latency_ratio"] == pytest.approx(0.8)
    assert metrics["route_mismatch_question_ids"] == []


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        (
            {
                "question_type": "single-session-preference",
                "question": "What should I do in Miami?",
            },
            "preference",
        ),
        (
            {"question_type": "multi-session", "question": "How many trips did I take?"},
            "aggregation",
        ),
        (
            {
                "question_type": "temporal-reasoning",
                "question": "How long had I been watching comedy?",
            },
            "aggregation",
        ),
        (
            {"question_type": "knowledge-update", "question": "Where do I work now?"},
            "synthesis-update",
        ),
    ],
)
def test_routed_reader_selects_question_specific_protocols(
    reference: dict, expected: str
) -> None:
    assert _reader_route(reference) == expected


def test_routed_reader_preference_prompt_applies_context_to_new_requests() -> None:
    prompt = _routed_answer_prompt(
        {
            "question_type": "single-session-preference",
            "question": "What should I do in Miami?",
            "question_date": "2025-02-01",
        },
        "The user likes hotels with ocean views.",
    )

    assert "new recommendation request is answerable" in prompt
    assert "resources the user already owns" in prompt
    assert "Transfer a demonstrated preference across analogous contexts" in prompt
    assert "Do not ask the user to choose a topic" in prompt
    assert "hard filters" in prompt
    assert "remove any violation" in prompt


def test_routed_reader_aggregation_prompt_types_numbers_before_summing() -> None:
    prompt = _routed_answer_prompt(
        {
            "question_type": "multi-session",
            "question": "What was the total reach?",
            "question_date": "2025-02-01",
        },
        "The campaign reached 2,000 people and received 50 clicks.",
    )

    assert "exact target quantity" in prompt
    assert "clicks when the question asks for people reached" in prompt
    assert "Deduplicate only" in prompt
    assert "Never add cumulative snapshots together" in prompt


def test_routed_reader_synthesis_prompt_orders_events_by_resolved_date() -> None:
    prompt = _routed_answer_prompt(
        {
            "question_type": "temporal-reasoning",
            "question": "Which event happened first?",
            "question_date": "2025-02-01",
        },
        "Session s1 - 2025-01-01\nuser: event",
    )

    assert "chronological event ledger" in prompt
    assert "resolve its relative date against the session date" in prompt


def test_checkpoint_manifest_rejects_changed_protocol(tmp_path) -> None:
    path = tmp_path / "run.manifest.json"
    first = _ensure_manifest(path, {"dataset": "a", "model": "m1"})
    assert json.loads(path.read_text(encoding="utf-8")) == first

    with pytest.raises(RuntimeError, match="manifest mismatch"):
        _ensure_manifest(path, {"dataset": "a", "model": "m2"})


@pytest.mark.parametrize(
    ("raw", "expected"), (("yes", True), (" YES. ", True), ("no", False), ("No!", False))
)
def test_binary_judge_parser_accepts_only_binary_verdicts(raw: str, expected: bool) -> None:
    assert _parse_binary_verdict(raw) is expected


def test_binary_judge_parser_rejects_explanations() -> None:
    with pytest.raises(RuntimeError, match="non-binary"):
        _parse_binary_verdict("Yes, because the answer matches")


def test_locomo_official_score_keeps_multi_answer_partial_credit() -> None:
    score = _official_locomo_score(
        {"category": 1, "answer": "red bicycle, blue helmet"},
        "red bicycle",
        _IdentityStemmer(),
    )

    assert score == pytest.approx(0.5)


def test_longmemeval_reader_retries_length_and_records_paid_attempts(
    monkeypatch, tmp_path
) -> None:
    responses = iter(
        [
            {
                "choices": [
                    {"message": {"content": "unfinished"}, "finish_reason": "length"}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 256},
            },
            {
                "choices": [
                    {"message": {"content": "finished"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            },
        ]
    )
    requested_budgets: list[int] = []

    def fake_chat(_provider, _prompt, *, max_tokens, timeout, retries):
        del timeout, retries
        requested_budgets.append(max_tokens)
        return next(responses)

    monkeypatch.setattr(
        "scripts.backend.evaluate_vault_longmemeval_api._chat", fake_chat
    )
    args = SimpleNamespace(
        max_context_chars=10_000,
        max_answer_tokens=256,
        timeout=1.0,
        retries=0,
    )
    provider = Provider("test", "https://invalid", "model", "KEY", 0.0, 0.0)
    reference = {
        "question_id": "q1",
        "question_type": "single-session-user",
        "question": "What happened?",
        "question_date": "2025-01-02",
        "answer": "finished",
        "haystack_session_ids": ["s1"],
        "haystack_dates": ["2025-01-01"],
        "haystack_sessions": [[{"role": "user", "content": "finished"}]],
    }
    rows = generate_longmemeval(
        args,
        provider,
        [{"question_id": "q1", "retrieved_session_ids": ["s1"]}],
        {"q1": reference},
        tmp_path / "answers.jsonl",
        "run-fingerprint",
    )

    assert requested_budgets == [256, 512]
    assert rows[0]["hypothesis"] == "finished"
    assert rows[0]["reader_attempt_count"] == 2
    assert len(_usage_attempts(rows, kind="reader")) == 2


def test_longmemeval_reader_records_provider_content_filter(monkeypatch, tmp_path) -> None:
    def fake_chat(_provider, _prompt, *, max_tokens, timeout, retries):
        del max_tokens, timeout, retries
        raise ProviderContentFilterError("blocked")

    monkeypatch.setattr(
        "scripts.backend.evaluate_vault_longmemeval_api._chat", fake_chat
    )
    args = SimpleNamespace(
        max_context_chars=10_000,
        max_answer_tokens=256,
        timeout=1.0,
        retries=0,
    )
    provider = Provider("test", "https://invalid", "model", "KEY", 0.0, 0.0)
    reference = {
        "question_id": "q1",
        "question_type": "single-session-user",
        "question": "What happened?",
        "question_date": "2025-01-02",
        "answer": "an event",
        "haystack_session_ids": ["s1"],
        "haystack_dates": ["2025-01-01"],
        "haystack_sessions": [[{"role": "user", "content": "an event"}]],
    }

    rows = generate_longmemeval(
        args,
        provider,
        [{"question_id": "q1", "retrieved_session_ids": ["s1"]}],
        {"q1": reference},
        tmp_path / "answers.jsonl",
        "run-fingerprint",
    )

    assert rows[0]["reader_content_filtered"] is True
    assert rows[0]["reader_finish_reason"] == "content_filter"
    assert rows[0]["reader_usage"]["total_tokens"] == 0


def test_longmemeval_reader_retries_through_1024_and_reuses_checkpoint(monkeypatch, tmp_path) -> None:
    responses = iter(
        [
            {"choices": [{"message": {"content": "a"}, "finish_reason": "length"}], "usage": {}},
            {"choices": [{"message": {"content": "b"}, "finish_reason": "length"}], "usage": {}},
            {"choices": [{"message": {"content": "done"}, "finish_reason": "stop"}], "usage": {}},
        ]
    )
    budgets: list[int] = []

    def fake_chat(_provider, _prompt, *, max_tokens, timeout, retries):
        del timeout, retries
        budgets.append(max_tokens)
        return next(responses)

    monkeypatch.setattr("scripts.backend.evaluate_vault_longmemeval_api._chat", fake_chat)
    args = SimpleNamespace(max_context_chars=10_000, max_answer_tokens=256, timeout=1.0, retries=0)
    provider = Provider("test", "https://invalid", "model", "KEY", 0.0, 0.0)
    reference = {
        "question_id": "q1", "question_type": "single-session-user",
        "question": "What happened?", "question_date": "2025-01-02", "answer": "done",
        "haystack_session_ids": ["s1"], "haystack_dates": ["2025-01-01"],
        "haystack_sessions": [[{"role": "user", "content": "done"}]],
    }
    checkpoint = tmp_path / "answers.jsonl"
    first = generate_longmemeval(
        args, provider, [{"question_id": "q1", "retrieved_session_ids": ["s1"]}],
        {"q1": reference}, checkpoint, "run-fingerprint",
    )
    resumed = generate_longmemeval(
        args, provider, [{"question_id": "q1", "retrieved_session_ids": ["s1"]}],
        {"q1": reference}, checkpoint, "run-fingerprint",
    )

    assert budgets == [256, 512, 1024]
    assert first[0]["reader_finish_reason"] == "stop"
    assert resumed[0]["hypothesis"] == "done"
    assert resumed[0]["reader_attempt_count"] == 3


def test_longmemeval_reader_uses_concise_recovery_after_large_length_response(
    monkeypatch, tmp_path
) -> None:
    responses = iter(
        [
            {
                "choices": [
                    {
                        "message": {"content": "long unfinished analysis"},
                        "finish_reason": "length",
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 2_048},
            },
            {
                "choices": [
                    {
                        "message": {"content": "The concise final answer."},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 120, "completion_tokens": 6},
            },
        ]
    )
    prompts: list[str] = []
    budgets: list[int] = []

    def fake_chat(_provider, prompt, *, max_tokens, timeout, retries):
        del timeout, retries
        prompts.append(prompt)
        budgets.append(max_tokens)
        return next(responses)

    monkeypatch.setattr(
        "scripts.backend.evaluate_vault_longmemeval_api._chat", fake_chat
    )
    args = SimpleNamespace(
        max_context_chars=10_000,
        max_answer_tokens=2_048,
        length_recovery_tokens=256,
        timeout=1.0,
        retries=0,
    )
    provider = Provider("test", "https://invalid", "model", "KEY", 0.0, 0.0)
    reference = {
        "question_id": "q1",
        "question_type": "single-session-user",
        "question": "What happened?",
        "question_date": "2025-01-02",
        "answer": "The concise final answer.",
        "haystack_session_ids": ["s1"],
        "haystack_dates": ["2025-01-01"],
        "haystack_sessions": [
            [{"role": "user", "content": "The concise final answer."}]
        ],
    }

    rows = generate_longmemeval(
        args,
        provider,
        [{"question_id": "q1", "retrieved_session_ids": ["s1"]}],
        {"q1": reference},
        tmp_path / "answers.jsonl",
        "run-fingerprint",
    )

    assert budgets == [2_048, 256]
    assert "return only the concise final answer" in prompts[1]
    assert rows[0]["hypothesis"] == "The concise final answer."
    assert rows[0]["reader_finish_reason"] == "stop"
    assert rows[0]["reader_length_recovery_attempted"] is True
    assert rows[0]["reader_length_recovery_succeeded"] is True
    assert rows[0]["reader_billed_prompt_tokens"] == 220


def test_longmemeval_chat_retries_socket_timeout(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read() -> bytes:
            return b'{"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}'

    calls = iter([TimeoutError("read timed out"), Response()])

    def fake_urlopen(_request, timeout):
        del timeout
        result = next(calls)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setenv("TEST_API_KEY", "secret")
    monkeypatch.setattr(
        "scripts.backend.evaluate_vault_longmemeval_api.urlopen", fake_urlopen
    )
    monkeypatch.setattr(
        "scripts.backend.evaluate_vault_longmemeval_api.time.sleep", lambda _seconds: None
    )
    provider = Provider("test", "https://invalid", "model", "TEST_API_KEY", 0.0, 0.0)

    response = _chat(provider, "prompt", max_tokens=10, timeout=1.0, retries=1)

    assert response["choices"][0]["message"]["content"] == "ok"
