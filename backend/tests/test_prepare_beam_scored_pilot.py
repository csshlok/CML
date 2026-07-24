from __future__ import annotations

from scripts.backend.prepare_beam_scored_pilot import (
    QUESTION_CATEGORIES,
    normalize_questions,
    select_pilot_conversations,
)


def test_pilot_conversation_selection_is_deterministic_and_order_independent() -> None:
    identifiers = [str(value) for value in range(10)]

    assert select_pilot_conversations(identifiers) == select_pilot_conversations(
        list(reversed(identifiers))
    )
    assert len(select_pilot_conversations(identifiers)) == 5


def test_question_normalization_is_balanced_and_flattens_source_ids() -> None:
    payload = {}
    answer_fields = {
        "abstention": "ideal_response",
        "contradiction_resolution": "ideal_answer",
        "instruction_following": "expected_compliance",
        "preference_following": "expected_compliance",
        "summarization": "ideal_summary",
    }
    for category in QUESTION_CATEGORIES:
        answer_field = answer_fields.get(category, "answer")
        payload[category] = [
            {
                "question": f"{category} question {index}",
                answer_field: f"{category} answer {index}",
                "rubric": [f"rubric {index}"],
                "source_chat_ids": (
                    {"first": [1], "second": [2]}
                    if category == "contradiction_resolution"
                    else [[1], [2]]
                ),
            }
            for index in range(2)
        ]

    questions = normalize_questions(
        {"conversation_id": "42", "probing_questions": repr(payload)}
    )

    assert len(questions) == 20
    assert {item["category"] for item in questions} == set(QUESTION_CATEGORIES)
    assert all(item["source_chat_ids"] == [1, 2] for item in questions)
    assert sum(item["is_abstention"] for item in questions) == 2
