from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.claim_evidence_packing import SessionEnvelope, pack_claim_evidence
from backend.app.core.claim_semantics import extract_structured_claims


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the deterministic claim extraction and consolidation protocol."
    )
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--token-budget", type=int, default=2_000)
    return parser.parse_args()


def evaluate_cases(cases: list[dict], *, token_budget: int = 2_000) -> dict:
    rows: list[dict] = []
    true_positive = 0
    false_positive = 0
    false_negative = 0
    citation_count = 0
    valid_citation_count = 0
    retained_expected_citations = 0
    expected_citation_count = 0
    for case in cases:
        sessions: list[SessionEnvelope] = []
        observed: set[str] = set()
        expected = {str(item) for item in case.get("expected_claims") or []}
        expected_citations: list[str] = []
        for rank, source_session in enumerate(case["sessions"]):
            turns = list(source_session["turns"])
            sessions.append(
                SessionEnvelope(
                    session_id=str(source_session["id"]),
                    date=str(source_session["date"]),
                    turns=turns,
                    retrieval_rank=rank,
                )
            )
            for turn in turns:
                normalized_source = " ".join(str(turn["content"]).split())
                for claim in extract_structured_claims(normalized_source, str(turn["role"])):
                    key = f"{claim.assertion_kind}|{claim.predicate_key}|{claim.object_text}"
                    observed.add(key)
                    citation_count += 1
                    if claim.citation_excerpt in normalized_source:
                        valid_citation_count += 1
                    if key in expected:
                        expected_citations.append(claim.citation_excerpt)

        context, meta = pack_claim_evidence(
            question=str(case["question"]),
            question_type=str(case.get("question_type") or ""),
            sessions=sessions,
            token_budget=token_budget,
            consolidate=True,
        )
        ledger = meta.get("ledger") or {}
        tp = len(observed & expected)
        fp = len(observed - expected)
        fn = len(expected - observed)
        true_positive += tp
        false_positive += fp
        false_negative += fn
        expected_citation_count += len(expected_citations)
        retained = sum(citation in context for citation in expected_citations)
        retained_expected_citations += retained
        group_match = int(ledger.get("consolidation_group_count") or 0) == int(
            case.get("expected_groups") or 0
        )
        conflict_match = int(ledger.get("conflicting_preference_group_count") or 0) == int(
            case.get("expected_conflicting_preference_groups") or 0
        )
        passed = fp == 0 and fn == 0 and group_match and conflict_match and retained == len(expected_citations)
        rows.append(
            {
                "id": case["id"],
                "passed": passed,
                "true_positive": tp,
                "false_positive": fp,
                "false_negative": fn,
                "expected_citations_retained": retained,
                "expected_citation_count": len(expected_citations),
                "consolidation_group_count": int(ledger.get("consolidation_group_count") or 0),
                "conflicting_preference_group_count": int(
                    ledger.get("conflicting_preference_group_count") or 0
                ),
                "packed_tokens_estimate": int(meta["packed_tokens_estimate"]),
            }
        )

    precision_denominator = true_positive + false_positive
    recall_denominator = true_positive + false_negative
    return {
        "protocol": "vault-claim-consolidation-provenance-v2",
        "case_count": len(rows),
        "passed_case_count": sum(row["passed"] for row in rows),
        "case_pass_rate": round(sum(row["passed"] for row in rows) / len(rows), 6) if rows else 0.0,
        "claim_precision": round(true_positive / precision_denominator, 6) if precision_denominator else 1.0,
        "claim_recall": round(true_positive / recall_denominator, 6) if recall_denominator else 1.0,
        "citation_validity_rate": round(valid_citation_count / citation_count, 6) if citation_count else 1.0,
        "expected_source_retention_rate": round(
            retained_expected_citations / expected_citation_count, 6
        ) if expected_citation_count else 1.0,
        "paid_api_calls": 0,
        "rows": rows,
    }


def main() -> int:
    args = parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    report = evaluate_cases(cases, token_budget=max(256, args.token_budget))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, indent=2))
    return 0 if report["case_pass_rate"] == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
