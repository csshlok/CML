from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path


PROTOCOL = "vault-evolving-memory-v1"
SEED = 20260720


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the frozen evolving-memory benchmark.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".tmp/vault-odin-memory-benchmark/evolving-memory-v1.json"),
    )
    return parser.parse_args()


def _session(session_id: str, date: str, statement: str) -> dict:
    return {
        "session_id": session_id,
        "date": date,
        "turns": [{"role": "user", "content": statement}],
    }


def _distractors(case_index: int) -> list[dict]:
    topics = [
        "I reviewed the quarterly budget and archived the spreadsheet.",
        "I watered the balcony plants before breakfast.",
        "I finished reading a history book about navigation.",
        "I reorganized the photos from last summer.",
        "I replaced the kitchen light bulb after work.",
        "I wrote meeting notes and sent them to the team.",
        "I practiced a new chord progression on guitar.",
        "I compared train schedules for a future trip.",
        "I cleaned the coffee grinder and the pantry shelf.",
        "I watched a documentary about deep sea exploration.",
        "I backed up old receipts to an external drive.",
        "I prepared a checklist for the neighborhood event.",
        "I fixed a loose handle on the hallway cabinet.",
        "I sorted the recycling before the evening pickup.",
    ]
    output = []
    for offset, text in enumerate(topics):
        day = 2 + ((case_index + offset) % 24)
        output.append(
            _session(
                f"d-{case_index:02d}-{offset:02d}",
                f"2025-03-{day:02d}T09:00:00+00:00",
                text,
            )
        )
    return output


def build_cases() -> list[dict]:
    cases: list[dict] = []
    favorites = [
        ("editor", "Vim", "VS Code"),
        ("browser", "Firefox", "Brave"),
        ("notebook", "Moleskine", "Leuchtturm1917"),
        ("terminal", "Command Prompt", "PowerShell"),
        ("music app", "Spotify", "Tidal"),
        ("calendar", "Google Calendar", "Fantastical"),
        ("tea", "Earl Grey", "Jasmine tea"),
        ("database", "MySQL", "PostgreSQL"),
        ("task manager", "Trello", "Linear"),
        ("design tool", "Sketch", "Figma"),
    ]
    locations = [
        ("Berlin", "Lisbon"), ("Osaka", "Kyoto"), ("Toronto", "Montreal"),
        ("Austin", "Seattle"), ("Paris", "Lyon"), ("Dublin", "Cork"),
        ("Pune", "Bengaluru"), ("Boston", "Chicago"), ("Rome", "Milan"),
        ("Sydney", "Melbourne"),
    ]
    visits = [
        "Kyoto", "Jaipur", "Reykjavik", "Prague", "Seoul",
        "Cusco", "Tallinn", "Marrakesh", "Hanoi", "Edinburgh",
    ]

    for index, (category, old, new) in enumerate(favorites):
        sessions = [
            _session(f"p-{index}-old", "2025-01-05T10:00:00+00:00", f"My favorite {category} is {old}."),
            *_distractors(index),
            _session(f"p-{index}-new", "2025-04-18T10:00:00+00:00", f"My favorite {category} is {new}."),
        ]
        cases.append({
            "id": f"preference-current-{index + 1:02d}",
            "category": "preference_current",
            "question": f"What is my favorite {category} now?",
            "reference_answer": new,
            "required_groups": [[new]],
            "sessions": sessions,
        })
        cases.append({
            "id": f"preference-history-{index + 1:02d}",
            "category": "preference_history",
            "question": f"How has my favorite {category} changed over time?",
            "reference_answer": f"It changed from {old} to {new}.",
            "required_groups": [[old], [new]],
            "sessions": sessions,
        })

    for index, (old, new) in enumerate(locations):
        cases.append({
            "id": f"state-history-{index + 1:02d}",
            "category": "state_history",
            "question": "Where did I live before, and where do I live now?",
            "reference_answer": f"You lived in {old} before and now live in {new}.",
            "required_groups": [[old], [new]],
            "sessions": [
                _session(f"s-{index}-old", "2025-01-08T10:00:00+00:00", f"I live in {old}."),
                *_distractors(20 + index),
                _session(f"s-{index}-new", "2025-05-09T10:00:00+00:00", f"I now live in {new}."),
            ],
        })

    for index, place in enumerate(visits):
        day = 10 + index
        observed = f"2025-06-{day:02d}T12:00:00+00:00"
        expected_day = day - 1
        cases.append({
            "id": f"temporal-action-{index + 1:02d}",
            "category": "temporal_action",
            "question": f"On what date did I visit {place}?",
            "reference_answer": f"You visited {place} on 2025-06-{expected_day:02d}.",
            "required_groups": [[f"2025-06-{expected_day:02d}"]],
            "sessions": [
                *_distractors(30 + index),
                _session(f"t-{index}-visit", observed, f"I visited {place} yesterday."),
            ],
        })

    random.Random(SEED).shuffle(cases)
    return cases


def main() -> None:
    args = parse_args()
    payload = {"protocol": PROTOCOL, "seed": SEED, "cases": build_cases()}
    encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encoded + b"\n")
    print(json.dumps({
        "output": str(args.output),
        "case_count": len(payload["cases"]),
        "sha256": hashlib.sha256(encoded + b"\n").hexdigest(),
    }, indent=2))


if __name__ == "__main__":
    main()
