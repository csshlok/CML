from __future__ import annotations

import json
from pathlib import Path

from scripts.backend.prepare_atomic_training_source_sessions import (
    SourceRecord,
    _compact_multiwoz_annotations,
    parse_persona_conversation,
    select_records,
)


def test_parse_persona_conversation_maps_only_selected_speaker_to_user() -> None:
    turns = parse_persona_conversation(
        "User 1: I own a bicycle.\n"
        "User 2: Nice.\n"
        "continued response\n"
        "User 1: I ride it daily.",
        user_number=1,
    )

    assert turns == [
        {"role": "user", "content": "I own a bicycle.", "source_turn_id": "0"},
        {
            "role": "assistant",
            "content": "Nice.\ncontinued response",
            "source_turn_id": "1",
        },
        {"role": "user", "content": "I ride it daily.", "source_turn_id": "2"},
    ]


def test_compact_multiwoz_annotations_retains_user_state_as_qa_metadata() -> None:
    annotations = _compact_multiwoz_annotations(
        {
            "turn_id": ["0", "1"],
            "speaker": [0, 1],
            "frames": [
                {
                    "service": ["hotel"],
                    "state": [
                        {
                            "active_intent": "book_hotel",
                            "requested_slots": ["hotel-phone"],
                            "slots_values": {
                                "slots_values_name": ["hotel-bookday"],
                                "slots_values_list": [["friday"]],
                            },
                        }
                    ],
                },
                {"service": [], "state": []},
            ],
        }
    )

    assert annotations == [
        {
            "source_turn_id": "0",
            "states": [
                {
                    "service": "hotel",
                    "active_intent": "book_hotel",
                    "requested_slots": ["hotel-phone"],
                    "slots": {"hotel-bookday": ["friday"]},
                }
            ],
        }
    ]


def test_selection_is_deterministic_deduplicated_and_protected() -> None:
    def record(row_id: str, text: str) -> SourceRecord:
        return SourceRecord(
            source_id="source",
            source_row_id=row_id,
            session={
                "date": "",
                "turns": [
                    {"role": "user", "content": text, "source_turn_id": "0"},
                    {"role": "assistant", "content": "a", "source_turn_id": "1"},
                    {"role": "user", "content": "b", "source_turn_id": "2"},
                    {"role": "assistant", "content": "c", "source_turn_id": "3"},
                ],
            },
            metadata={},
        )

    rows = [
        record("protected", "one"),
        record("duplicate-a", "same"),
        record("duplicate-b", "same"),
        record("eligible-a", "two"),
        record("eligible-b", "three"),
    ]
    selected, stats = select_records(
        rows,
        count=2,
        seed=7,
        minimum_turns=4,
        maximum_characters=100,
        protected_ids={"protected"},
        protected_session_hashes=set(),
        protected_content_hashes=set(),
        seen_content_hashes=set(),
    )
    selected_again, _ = select_records(
        rows,
        count=2,
        seed=7,
        minimum_turns=4,
        maximum_characters=100,
        protected_ids={"protected"},
        protected_session_hashes=set(),
        protected_content_hashes=set(),
        seen_content_hashes=set(),
    )

    assert [item.source_row_id for item in selected] == [
        item.source_row_id for item in selected_again
    ]
    assert stats["protected_id_overlap"] == 1
    assert stats["duplicate_content"] == 1


def test_registry_forbids_direct_raw_training() -> None:
    path = Path("backend/tests/fixtures/atomic_training_sources.json")
    registry = json.loads(path.read_text(encoding="utf-8"))

    assert registry["policy"]["requires_teacher_labels"] is True
    assert registry["policy"]["may_train_directly_from_raw_sources"] is False
    assert sum(
        source["row_count"] for source in registry["approved_sources"]
    ) == 19_635
