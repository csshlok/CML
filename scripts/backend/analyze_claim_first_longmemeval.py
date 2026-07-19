from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.backend.evaluate_vault_longmemeval_api import _pack_reader_context


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze claim-first LongMemEval packing without model or API calls."
    )
    parser.add_argument("--retrieval", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reader-token-budget", type=int, default=10_000)
    parser.add_argument("--reader-budget-safety-factor", type=float, default=1.0)
    parser.add_argument("--max-context-chars", type=int, default=500_000)
    return parser.parse_args()


def _containment(answer: str, context: str) -> bool:
    normalized_answer = " ".join(str(answer or "").casefold().split()).strip(" .!?")
    normalized_context = " ".join(str(context or "").casefold().split())
    return bool(normalized_answer and normalized_answer in normalized_context)


def main() -> int:
    args = parse_args()
    retrieval = json.loads(args.retrieval.read_text(encoding="utf-8"))
    references_list = json.loads(args.dataset.read_text(encoding="utf-8"))
    references = {str(row["question_id"]): row for row in references_list}
    runtime_args = SimpleNamespace(
        context_packing="claim-first-v1",
        reader_token_budget=args.reader_token_budget,
        reader_budget_safety_factor=args.reader_budget_safety_factor,
        max_context_chars=args.max_context_chars,
        reader_prompt="typed-v1",
    )
    rows: list[dict] = []
    for retrieval_row in retrieval["results"]:
        question_id = str(retrieval_row["question_id"])
        reference = references[question_id]
        context, meta = _pack_reader_context(
            runtime_args,
            reference,
            [str(item) for item in retrieval_row["retrieved_session_ids"]],
        )
        answer_ids = {str(item) for item in reference.get("answer_session_ids") or []}
        included_ids = {str(item) for item in meta.get("included_session_ids") or []}
        rows.append(
            {
                "question_id": question_id,
                "question_type": reference.get("question_type"),
                "prepack_prompt_tokens_estimate": meta["prepack_prompt_tokens_estimate"],
                "packed_prompt_tokens_estimate": meta["packed_prompt_tokens_estimate"],
                "prepack_over_budget": meta["prepack_prompt_tokens_estimate"] > args.reader_token_budget,
                "packed_over_budget": meta["packed_prompt_tokens_estimate"] > args.reader_token_budget,
                "candidate_claim_count": meta["candidate_claim_count"],
                "selected_claim_count": meta["selected_claim_count"],
                "answer_session_count": len(answer_ids),
                "answer_sessions_retained": len(answer_ids & included_ids),
                "answer_session_recall": (
                    len(answer_ids & included_ids) / len(answer_ids) if answer_ids else None
                ),
                "normalized_gold_contained": _containment(reference.get("answer", ""), context),
            }
        )

    answer_rows = [row for row in rows if row["answer_session_recall"] is not None]
    report = {
        "protocol": "claim-first-longmemeval-offline-analysis-v1",
        "reader_token_budget": args.reader_token_budget,
        "question_count": len(rows),
        "prepack_over_budget_count": sum(row["prepack_over_budget"] for row in rows),
        "packed_over_budget_count": sum(row["packed_over_budget"] for row in rows),
        "mean_prepack_prompt_tokens_estimate": round(
            statistics.fmean(row["prepack_prompt_tokens_estimate"] for row in rows), 2
        ),
        "mean_packed_prompt_tokens_estimate": round(
            statistics.fmean(row["packed_prompt_tokens_estimate"] for row in rows), 2
        ),
        "estimated_prompt_token_reduction_percent": round(
            100
            * (
                1
                - statistics.fmean(row["packed_prompt_tokens_estimate"] for row in rows)
                / statistics.fmean(row["prepack_prompt_tokens_estimate"] for row in rows)
            ),
            2,
        ),
        "macro_answer_session_recall": round(
            statistics.fmean(row["answer_session_recall"] for row in answer_rows), 6
        ),
        "perfect_answer_session_retention_count": sum(
            row["answer_session_recall"] == 1.0 for row in answer_rows
        ),
        "normalized_gold_containment_rate": round(
            statistics.fmean(row["normalized_gold_contained"] for row in rows), 6
        ),
        "prepack_over_budget_by_type": dict(
            Counter(
                str(row["question_type"])
                for row in rows
                if row["prepack_over_budget"]
            )
        ),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
