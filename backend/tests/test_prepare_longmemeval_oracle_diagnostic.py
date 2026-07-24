from __future__ import annotations

from scripts.backend.prepare_longmemeval_oracle_diagnostic import (
    DEFAULT_CONTROL_BY_TYPE,
    DEFAULT_RECOVERY_BY_TYPE,
    prepare,
)


def _row(question_id: str, question_type: str) -> dict:
    return {
        "question_id": question_id,
        "question_type": question_type,
        "question": "Generic question",
        "answer": "Hidden answer",
        "answer_session_ids": [f"gold-{question_id}"],
        "retrieved_session_ids": [f"gold-{question_id}", f"noise-{question_id}"],
        "found_session_ids": [f"gold-{question_id}"],
        "rank": [f"gold-{question_id}", f"noise-{question_id}"],
        "recall_at_k": 1.0,
        "any_evidence_at_k": True,
        "abstention": False,
    }


def test_oracle_panel_is_deterministic_stratified_and_answer_blind() -> None:
    rows: list[dict] = []
    primary: list[dict] = []
    independent: list[dict] = []
    allocations = {
        key: max(
            DEFAULT_RECOVERY_BY_TYPE.get(key, 0),
            DEFAULT_CONTROL_BY_TYPE.get(key, 0),
        )
        for key in set(DEFAULT_RECOVERY_BY_TYPE) | set(DEFAULT_CONTROL_BY_TYPE)
    }
    for bucket, count in allocations.items():
        question_type = "single-session-user" if bucket == "other" else bucket
        for label, correct in (("failure", False), ("control", True)):
            for index in range(count + 2):
                question_id = f"{bucket}-{label}-{index}"
                row = _row(question_id, question_type)
                row["answer"] = f"Never inspect this answer {question_id}"
                rows.append(row)
                judgment = {
                    "question_id": question_id,
                    "autoeval_label": {"label": correct},
                }
                primary.append(judgment)
                independent.append(judgment)

    retrieval = {"protocol": {"top_k": 10}, "results": rows}
    first = prepare(
        retrieval=retrieval,
        primary_rows=primary,
        independent_rows=independent,
        seed=123,
    )
    second = prepare(
        retrieval=retrieval,
        primary_rows=primary,
        independent_rows=independent,
        seed=123,
    )
    assert first == second

    baseline, oracle, manifest = first
    assert baseline["summary"]["recovery_count"] == sum(
        DEFAULT_RECOVERY_BY_TYPE.values()
    )
    assert baseline["summary"]["control_count"] == sum(
        DEFAULT_CONTROL_BY_TYPE.values()
    )
    assert baseline["protocol"]["answer_text_used_for_selection"] is False
    assert manifest["promotion_eligible"] is False
    assert oracle["protocol"]["answer_session_ids_used_for_context"] is True
    for row in oracle["results"]:
        assert row["retrieved_session_ids"] == row["answer_session_ids"]
        assert all("noise-" not in item for item in row["retrieved_session_ids"])


def test_oracle_panel_excludes_incomplete_retrieval_and_abstentions() -> None:
    rows: list[dict] = []
    primary: list[dict] = []
    independent: list[dict] = []
    for bucket, count in DEFAULT_RECOVERY_BY_TYPE.items():
        question_type = "single-session-user" if bucket == "other" else bucket
        for index in range(count):
            question_id = f"{bucket}-failure-{index}"
            rows.append(_row(question_id, question_type))
            label = {"question_id": question_id, "autoeval_label": {"label": False}}
            primary.append(label)
            independent.append(label)
    for bucket, count in DEFAULT_CONTROL_BY_TYPE.items():
        question_type = "single-session-user" if bucket == "other" else bucket
        for index in range(count):
            question_id = f"{bucket}-control-{index}"
            rows.append(_row(question_id, question_type))
            label = {"question_id": question_id, "autoeval_label": {"label": True}}
            primary.append(label)
            independent.append(label)
    excluded = _row("excluded", "multi-session")
    excluded["recall_at_k"] = 0.5
    rows.append(excluded)
    label = {"question_id": "excluded", "autoeval_label": {"label": False}}
    primary.append(label)
    independent.append(label)

    baseline, _, _ = prepare(
        retrieval={"results": rows},
        primary_rows=primary,
        independent_rows=independent,
        seed=123,
    )
    assert "excluded" not in {
        str(row["question_id"]) for row in baseline["results"]
    }
