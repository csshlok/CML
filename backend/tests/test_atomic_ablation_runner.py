from __future__ import annotations

import json
from types import SimpleNamespace

import scripts.backend.run_longmemeval_atomic_ablation as ablation


def test_bounded_semantic_extraction_is_cached_and_reported(
    monkeypatch, tmp_path
) -> None:
    provider = SimpleNamespace(name="kimi", model="extractor")
    monkeypatch.setattr(ablation, "_provider", lambda *_args: provider)
    calls: list[str] = []

    def fake_chat(_provider, prompt, **_kwargs):
        calls.append(prompt)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "sessions": [
                                    {
                                        "session_id": "s1",
                                        "facts": [
                                            {
                                                "fact_id": "visit",
                                                "citation": {
                                                    "turn_index": 0,
                                                    "excerpt": "I visited Dr. Lee.",
                                                },
                                                "subject": "user",
                                                "predicate": "visited_doctor",
                                                "object_text": "Dr. Lee",
                                                "fact_kind": "event",
                                                "confidence": 0.98,
                                            }
                                        ],
                                    }
                                ]
                            }
                        )
                    }
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

    monkeypatch.setattr(ablation, "_chat", fake_chat)
    monkeypatch.setattr(
        ablation,
        "_provider_cost",
        lambda _provider, usages: {
            "prompt_tokens": sum(row.get("prompt_tokens", 0) for row in usages)
        },
    )
    manifest = {
        "questions": [
            {"question_id": "q1", "retrieved_session_ids": ["s1"]}
        ]
    }
    references = {
        "q1": {
            "haystack_session_ids": ["s1"],
            "haystack_dates": ["2026-01-01"],
            "haystack_sessions": [
                [{"role": "user", "content": "I visited Dr. Lee."}]
            ],
        }
    }
    args = SimpleNamespace(
        run_dir=tmp_path,
        semantic_extraction=True,
        extractor_provider="kimi",
        extractor_model="extractor",
        extraction_max_tokens=1024,
        extraction_max_source_chars=1000,
        extraction_max_facts_per_chunk=8,
        extraction_roles="all",
        timeout=10,
        retries=1,
        max_extraction_sessions=0,
        workers=1,
    )

    ablation.extract_sessions(args, manifest, references)
    ablation.extract_sessions(args, manifest, references)

    report = json.loads(
        (tmp_path / "semantic-extraction-report.json").read_text(encoding="utf-8")
    )
    assert len(calls) == 1
    assert report["completed_session_count"] == 1
    assert report["fact_count"] == 1
    assert report["cost"]["prompt_tokens"] == 10


def test_label_evidence_retries_malformed_provider_json(monkeypatch, tmp_path) -> None:
    manifest = {
        "questions": [
            {
                "question_id": "q1",
                "question_type": "knowledge-update",
                "split": "evaluation",
            }
        ]
    }
    references = {
        "q1": {
            "question": "What changed?",
            "answer": "four engineers",
            "answer_session_ids": ["s1"],
            "haystack_session_ids": ["s1"],
            "haystack_dates": ["2026-01-01"],
            "haystack_sessions": [
                [{"role": "user", "content": "I now lead four engineers."}]
            ],
        }
    }
    responses = iter(
        [
            '{"evidence":[{"session_id":"s1" "turn_index":0}]}',
            (
                '{"evidence":[{"session_id":"s1","turn_index":0,'
                '"speaker":"user","excerpt":"I now lead four engineers.",'
                '"role":"proves the current team size"}]}'
            ),
        ]
    )

    monkeypatch.setattr(
        ablation,
        "_provider",
        lambda name, model: SimpleNamespace(name=name, model=model),
    )
    monkeypatch.setattr(
        ablation,
        "_chat",
        lambda *_args, **_kwargs: {
            "choices": [{"message": {"content": next(responses)}}],
            "usage": {},
        },
    )
    args = SimpleNamespace(
        run_dir=tmp_path,
        extractor_provider="kimi",
        extractor_model="extractor",
        timeout=10,
        retries=1,
        workers=1,
    )

    rows = ablation.label_evidence(args, manifest, references)

    assert rows[0]["invalid_label_count"] == 1
    assert rows[0]["evidence"][0]["excerpt"] == "I now lead four engineers."


def test_adaptive_arm_generates_only_safe_atomic_routes(
    monkeypatch, tmp_path
) -> None:
    manifest = {
        "selection_mode": "representative",
        "questions": [
            {
                "question_id": "preference",
                "question_type": "single-session-preference",
                "split": "evaluation",
            },
            {
                "question_id": "update",
                "question_type": "knowledge-update",
                "split": "evaluation",
            },
        ],
    }
    references = {
        "preference": {"question_type": "single-session-preference"},
        "update": {"question_type": "knowledge-update"},
    }

    def fake_load(path):
        name = path.name
        if name.endswith("hypotheses.jsonl"):
            return [
                {
                    "question_id": "preference",
                    "hypothesis": "baseline preference",
                    "reader_prompt_tokens": 100,
                    "reader_finish_reason": "stop",
                },
                {
                    "question_id": "update",
                    "hypothesis": "baseline update",
                    "reader_prompt_tokens": 100,
                    "reader_finish_reason": "stop",
                },
            ]
        if name.endswith("evaluated.jsonl"):
            return [
                {"question_id": "preference", "autoeval_label": {"label": True}},
                    {"question_id": "update", "autoeval_label": {"label": False}},
            ]
        raise AssertionError(f"Unexpected checkpoint read: {path}")

    generated_item_ids: list[str] = []

    def fake_answer(_args, _provider, arm, items, _references):
        assert arm == "adaptive"
        generated_item_ids.extend(item["question_id"] for item in items)
        return [
            {
                "question_id": item["question_id"],
                "question_type": item["question_type"],
                "hypothesis": "atomic fact",
                "usage": {"prompt_tokens": 80},
            }
            for item in items
        ]

    def fake_judge(_args, _provider, _arm, answers, _references):
        return [
            {"question_id": answer["question_id"], "label": True}
            for answer in answers
        ]

    monkeypatch.setattr(ablation, "_load_jsonl", fake_load)
    monkeypatch.setattr(
        ablation, "_provider", lambda name, _model: SimpleNamespace(name=name)
    )
    monkeypatch.setattr(ablation, "_answer_arm", fake_answer)
    monkeypatch.setattr(ablation, "_judge_arm", fake_judge)
    monkeypatch.setattr(
        ablation,
        "_adaptive_decision",
        lambda _args, item, _reference: (
            item["question_id"] == "update",
            {"route": {"path": "atomic" if item["question_id"] == "update" else "claim-first"}},
        ),
    )
    args = SimpleNamespace(
        artifact_dir=tmp_path,
        run_dir=tmp_path,
        reader_provider="kimi",
        reader_model="reader",
        primary_judge_provider="kimi",
        primary_judge_model="judge",
        independent_judge_provider="openai",
        independent_judge_model="judge",
        evaluation_arms="adaptive",
    )

    report = ablation.evaluate(args, manifest, references)

    assert generated_item_ids == ["update"]
    assert report["summary"]["adaptive"]["dual_judge_correct_count"] == 2
    assert report["summary"]["adaptive"]["wins_vs_claim_first"] == 1
    assert report["summary"]["adaptive"]["losses_vs_claim_first"] == 0


def test_coverage_stage_fingerprint_is_stable_and_configuration_sensitive() -> None:
    manifest = {"questions": [{"question_id": "q1"}]}
    labels = [{"question_id": "q1", "evidence": []}]
    args = SimpleNamespace(
        fact_token_budget=7800,
        claim_first_token_budget=10000,
        semantic_extraction=False,
        extractor_model="unused",
    )
    first = ablation._coverage_stage_fingerprint(args, manifest, labels)
    second = ablation._coverage_stage_fingerprint(args, manifest, labels)
    changed = ablation._coverage_stage_fingerprint(
        SimpleNamespace(**{**vars(args), "fact_token_budget": 7000}),
        manifest,
        labels,
    )
    assert first == second
    assert first != changed


def test_reader_stage_reuses_only_matching_content_fingerprint(monkeypatch, tmp_path) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        ablation,
        "_reader_context",
        lambda *_args: ("evidence", {"packing": "test"}),
    )
    monkeypatch.setattr(
        ablation,
        "_answer_prompt",
        lambda _reference, context: f"prompt:{context}",
    )
    monkeypatch.setattr(
        ablation,
        "_chat",
        lambda _provider, prompt, **_kwargs: (
            calls.append(prompt)
            or {
                "choices": [{"message": {"content": "answer"}, "finish_reason": "stop"}],
                "usage": {},
            }
        ),
    )
    args = SimpleNamespace(
        run_dir=tmp_path,
        answer_max_tokens=100,
        timeout=10,
        retries=1,
        workers=1,
    )
    provider = SimpleNamespace(name="local", model="reader")
    items = [{"question_id": "q1", "question_type": "test", "retrieved_session_ids": []}]
    references = {"q1": {"question": "Question?"}}

    first = ablation._answer_arm(args, provider, "adaptive", items, references)
    second = ablation._answer_arm(args, provider, "adaptive", items, references)
    args.answer_max_tokens = 101
    third = ablation._answer_arm(args, provider, "adaptive", items, references)

    assert first[0]["stage_fingerprint"] == second[0]["stage_fingerprint"]
    assert third[0]["stage_fingerprint"] != first[0]["stage_fingerprint"]
    assert calls == ["prompt:evidence", "prompt:evidence"]


def test_reader_retries_length_limit_and_keeps_final_answer(monkeypatch, tmp_path) -> None:
    responses = iter(
        [
            {
                "choices": [
                    {"message": {"content": "unfinished"}, "finish_reason": "length"}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            },
            {
                "choices": [
                    {"message": {"content": "complete answer"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3},
            },
        ]
    )
    limits: list[int] = []
    monkeypatch.setattr(
        ablation,
        "_reader_context",
        lambda *_args: ("evidence", {"packing": "test"}),
    )
    monkeypatch.setattr(
        ablation,
        "_answer_prompt",
        lambda _reference, context: f"prompt:{context}",
    )

    def fake_chat(_provider, _prompt, *, max_tokens, **_kwargs):
        limits.append(max_tokens)
        return next(responses)

    monkeypatch.setattr(ablation, "_chat", fake_chat)
    args = SimpleNamespace(
        run_dir=tmp_path,
        answer_max_tokens=512,
        timeout=10,
        retries=1,
        workers=1,
    )
    items = [
        {"question_id": "q1", "question_type": "test", "retrieved_session_ids": []}
    ]
    rows = ablation._answer_arm(
        args,
        SimpleNamespace(name="kimi", model="reader"),
        "facts-only",
        items,
        {"q1": {"question": "Question?"}},
    )

    assert limits == [512, 1024]
    assert rows[0]["hypothesis"] == "complete answer"
    assert rows[0]["finish_reason"] == "stop"
    assert rows[0]["attempt_count"] == 2
    assert rows[0]["usage"]["prompt_tokens"] == 20
