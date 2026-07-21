from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.claim_evidence_packing import estimate_claim_tokens
from backend.app.core.claim_semantics import extract_structured_claims


def _percent(numerator: int, denominator: int) -> float:
    return round(100 * numerator / denominator, 2) if denominator else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure LongMemEval coverage of Vault's write-time structured facts."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path(".tmp/vault-odin-memory-benchmark"),
    )
    args = parser.parse_args()
    root = args.artifact_dir

    with (root / "longmemeval_s_cleaned.json").open(encoding="utf-8") as stream:
        dataset = json.load(stream)
    with (root / "longmemeval-full500-retrieval.json").open(encoding="utf-8") as stream:
        retrieval_report = json.load(stream)
    retrieval = {row["question_id"]: row for row in retrieval_report["results"]}

    hypotheses: dict[str, dict] = {}
    with (root / "longmemeval-claim-first-10k-v2-full500.hypotheses.jsonl").open(
        encoding="utf-8"
    ) as stream:
        for line in stream:
            row = json.loads(line)
            hypotheses[row["question_id"]] = row

    rows: list[dict] = []
    by_type: dict[str, list[dict]] = defaultdict(list)
    uncovered_examples: list[dict] = []
    predicate_counts: Counter[str] = Counter()
    gold_predicate_counts: Counter[str] = Counter()

    for record in dataset:
        question_id = record["question_id"]
        retrieved = retrieval[question_id]
        session_map = dict(
            zip(
                record["haystack_session_ids"],
                zip(record["haystack_dates"], record["haystack_sessions"]),
            )
        )
        gold_session_ids = set(record.get("answer_session_ids") or [])
        facts: list[tuple[str, str, str, object]] = []
        gold_facts: list[tuple[str, str, str, object]] = []

        for session_id in retrieved["retrieved_session_ids"]:
            session = session_map.get(session_id)
            if session is None:
                continue
            date, turns = session
            session_facts: list[tuple[str, str, str, object]] = []
            for turn in turns:
                role = str(turn.get("role") or "")
                for claim in extract_structured_claims(
                    str(turn.get("content") or ""), role
                ):
                    session_facts.append((session_id, date, role, claim))
            facts.extend(session_facts)
            predicate_counts.update(claim.predicate_key for *_, claim in session_facts)
            if session_id in gold_session_ids:
                gold_facts.extend(session_facts)
                gold_predicate_counts.update(
                    claim.predicate_key for *_, claim in session_facts
                )

        rendered = "\n".join(
            f"[{date} | {session_id} | {role}] "
            f"{claim.subject_key} {claim.predicate_key} {claim.object_text} "
            f"(source: {claim.citation_excerpt})"
            for session_id, date, role, claim in facts
        )
        gold_text = " ".join(
            f"{claim.object_text} {claim.citation_excerpt}"
            for _, _, _, claim in gold_facts
        ).casefold()
        normalized_answer = " ".join(str(record.get("answer") or "").casefold().split())
        gold_sessions_with_facts = {session_id for session_id, _, _, _ in gold_facts}
        row = {
            "question_id": question_id,
            "question_type": record["question_type"],
            "abstention": bool(retrieved["abstention"]),
            "retrieval_hit": bool(retrieved["any_evidence_at_k"]),
            "fact_count": len(facts),
            "gold_fact_count": len(gold_facts),
            "any_gold_fact": bool(gold_facts),
            "all_gold_sessions_have_fact": bool(gold_session_ids)
            and gold_session_ids <= gold_sessions_with_facts,
            "literal_answer_in_gold_facts": bool(
                normalized_answer
                and normalized_answer in " ".join(gold_text.split())
            ),
            "fact_tokens": estimate_claim_tokens(rendered),
            "baseline_tokens": hypotheses[question_id]["packed_tokens_estimate"],
        }
        rows.append(row)
        by_type[row["question_type"]].append(row)

        if (
            row["retrieval_hit"]
            and not row["any_gold_fact"]
            and len(uncovered_examples) < 8
        ):
            uncovered_examples.append(
                {
                    "question_id": question_id,
                    "question_type": record["question_type"],
                    "question": record["question"],
                    "answer": record["answer"],
                }
            )

    answerable = [row for row in rows if not row["abstention"]]
    report = {
        "protocol": "longmemeval-existing-write-time-fact-coverage-v1",
        "question_count": len(rows),
        "answerable_question_count": len(answerable),
        "retrieved_arm": "same top-k sessions as claim-first-10k-v2",
        "fact_extractor": "backend.app.core.claim_semantics.extract_structured_claims",
        "summary": {
            "questions_with_any_retrieved_fact": sum(row["fact_count"] > 0 for row in rows),
            "questions_with_any_gold_session_fact": sum(
                row["any_gold_fact"] for row in answerable
            ),
            "questions_with_all_gold_sessions_fact": sum(
                row["all_gold_sessions_have_fact"] for row in answerable
            ),
            "questions_with_literal_answer_in_gold_facts": sum(
                row["literal_answer_in_gold_facts"] for row in answerable
            ),
            "any_gold_session_fact_percent": _percent(
                sum(row["any_gold_fact"] for row in answerable), len(answerable)
            ),
            "all_gold_sessions_fact_percent": _percent(
                sum(row["all_gold_sessions_have_fact"] for row in answerable),
                len(answerable),
            ),
            "literal_answer_in_gold_facts_percent": _percent(
                sum(row["literal_answer_in_gold_facts"] for row in answerable),
                len(answerable),
            ),
            "mean_fact_count": round(statistics.mean(row["fact_count"] for row in rows), 2),
            "median_fact_count": statistics.median(row["fact_count"] for row in rows),
            "mean_fact_tokens": round(statistics.mean(row["fact_tokens"] for row in rows), 2),
            "mean_claim_first_tokens": round(
                statistics.mean(row["baseline_tokens"] for row in rows), 2
            ),
            "fact_to_claim_first_token_ratio": round(
                statistics.mean(row["fact_tokens"] for row in rows)
                / statistics.mean(row["baseline_tokens"] for row in rows),
                4,
            ),
        },
        "predicate_counts": dict(predicate_counts.most_common()),
        "gold_session_predicate_counts": dict(gold_predicate_counts.most_common()),
        "by_question_type": {},
        "uncovered_examples": uncovered_examples,
        "rows": rows,
    }
    for question_type, type_rows in sorted(by_type.items()):
        answerable_type_rows = [row for row in type_rows if not row["abstention"]]
        report["by_question_type"][question_type] = {
            "question_count": len(type_rows),
            "answerable_question_count": len(answerable_type_rows),
            "any_gold_session_fact_percent": _percent(
                sum(row["any_gold_fact"] for row in answerable_type_rows),
                len(answerable_type_rows),
            ),
            "literal_answer_in_gold_facts_percent": _percent(
                sum(
                    row["literal_answer_in_gold_facts"]
                    for row in answerable_type_rows
                ),
                len(answerable_type_rows),
            ),
            "mean_fact_count": round(
                statistics.mean(row["fact_count"] for row in type_rows), 2
            ),
        }

    output = root / "longmemeval-write-time-fact-coverage.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**report["summary"], "by_question_type": report["by_question_type"]}, indent=2))
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
