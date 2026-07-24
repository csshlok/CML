from __future__ import annotations

from scripts.backend.prepare_beam_ingestion_evaluation import (
    _split_turn,
    conversation_windows,
    deterministic_split,
)


def test_beam_split_is_deterministic_disjoint_and_conversation_level() -> None:
    identifiers = [str(value) for value in range(1, 21)]

    first = deterministic_split(identifiers)
    second = deterministic_split(reversed(identifiers))

    assert first == second
    assert len(first["development"]) == 10
    assert len(first["validation"]) == 4
    assert len(first["sealed_test"]) == 6
    assert set(first["development"]).isdisjoint(first["validation"])
    assert set(first["development"]).isdisjoint(first["sealed_test"])
    assert set(first["validation"]).isdisjoint(first["sealed_test"])


def test_beam_oversized_turn_slices_are_lossless_and_bounded() -> None:
    content = "First sentence. " + ("x" * 700) + "\n\n" + ("y" * 700)
    turn = {
        "role": "user",
        "content": content,
        "source_turn_id": 7,
        "source_index": "1,7",
        "time_anchor": "March-15-2024",
    }

    pieces = _split_turn(turn, max_chars=512)

    assert "".join(piece["content"] for piece in pieces) == content
    assert all(len(piece["content"]) <= 512 for piece in pieces)
    assert pieces[0]["source_char_start"] == 0
    assert pieces[-1]["source_char_end"] == len(content)
    assert all(
        left["source_char_end"] == right["source_char_start"]
        for left, right in zip(pieces, pieces[1:])
    )


def test_beam_windows_keep_source_offsets_and_respect_character_budget() -> None:
    row = {
        "conversation_id": "42",
        "chat": [
            [
                {
                    "role": "user" if index % 2 == 0 else "assistant",
                    "content": f"turn-{index}-" + ("z" * 450),
                    "id": index,
                    "index": f"1,{index}",
                    "time_anchor": "March-15-2024",
                }
                for index in range(8)
            ]
        ],
    }

    windows = conversation_windows(
        row,
        source_split="100K",
        window_turns=6,
        overlap_turns=1,
        max_window_chars=1_200,
    )

    assert len(windows) > 1
    assert all(
        sum(len(turn["content"]) for turn in window["turns"]) <= 1_200
        for window in windows
    )
    assert all(window["source_slices"] for window in windows)
    assert all(
        source_slice["source_char_end"] > source_slice["source_char_start"]
        for window in windows
        for source_slice in window["source_slices"]
    )


def test_beam_role_scope_is_applied_before_nonoverlapping_windowing() -> None:
    row = {
        "conversation_id": "scope",
        "chat": [
            [
                {
                    "role": role,
                    "content": content,
                    "id": index,
                    "index": f"1,{index}",
                    "time_anchor": "March-15-2024",
                }
                for index, (role, content) in enumerate(
                    [
                        ("user", "first user fact"),
                        ("assistant", "a" * 2_000),
                        ("user", "second user fact"),
                        ("assistant", "b" * 2_000),
                    ]
                )
            ]
        ],
    }

    windows = conversation_windows(
        row,
        source_split="100K",
        window_turns=6,
        overlap_turns=0,
        max_window_chars=512,
        included_roles={"user"},
    )

    assert len(windows) == 1
    assert [turn["content"] for turn in windows[0]["turns"]] == [
        "first user fact",
        "second user fact",
    ]
    assert [item["source_turn_id"] for item in windows[0]["source_slices"]] == [0, 2]
