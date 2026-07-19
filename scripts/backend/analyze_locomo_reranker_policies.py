from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate saved cross-encoder scores under bounded ranking policies."
    )
    parser.add_argument("--retrieval-report", type=Path, required=True)
    parser.add_argument("--reranker-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--depths", type=int, nargs="+", default=[10, 20, 30])
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--max-mean-total-seconds", type=float, default=0.5)
    parser.add_argument("--max-p95-total-seconds", type=float, default=0.85)
    parser.add_argument("--min-recall-improvement", type=float, default=0.05)
    parser.add_argument("--max-category-drop", type=float, default=0.01)
    return parser.parse_args()


def _session_id(item: dict[str, Any]) -> str:
    return str(item.get("evidence_id") or "").split(":", 1)[0]


def _select(
    candidates: list[dict[str, Any]],
    *,
    depth: int,
    top_k: int,
    cross_weight: float,
    max_per_session: int,
) -> list[dict[str, Any]]:
    available = [item for item in candidates if int(item["retrieval_rank"]) <= depth]
    cross_rank = {
        str(item["source_id"]): rank
        for rank, item in enumerate(available, start=1)
    }
    ranked = sorted(
        available,
        key=lambda item: (
            cross_weight / (60 + cross_rank[str(item["source_id"])])
            + (1.0 - cross_weight) / (60 + int(item["retrieval_rank"])),
            -int(item["retrieval_rank"]),
        ),
        reverse=True,
    )
    selected: list[dict[str, Any]] = []
    per_session: dict[str, int] = defaultdict(int)
    for item in ranked:
        session_id = _session_id(item)
        if per_session[session_id] >= max_per_session:
            continue
        selected.append(item)
        per_session[session_id] += 1
        if len(selected) >= top_k:
            break
    return selected


def analyze(
    retrieval_report: dict[str, Any],
    reranker_report: dict[str, Any],
    *,
    depths: list[int],
    top_k: int,
    max_mean_total_seconds: float,
    max_p95_total_seconds: float,
    min_recall_improvement: float,
    max_category_drop: float,
) -> dict[str, Any]:
    retrieval = {str(row["question_id"]): row for row in retrieval_report.get("results") or []}
    reranked = {str(row["question_id"]): row for row in reranker_report.get("results") or []}
    if set(retrieval) != set(reranked):
        raise ValueError("retrieval and reranker reports do not contain identical question IDs")
    baseline_rows = [row for row in retrieval.values() if row.get("evidence")]
    def baseline_value(row: dict[str, Any]) -> float:
        gold = {str(value) for value in row.get("evidence") or []}
        found = {
            str(item.get("evidence_id") or "")
            for item in list(row.get("retrieved") or [])[:top_k]
        }
        return len(gold & found) / len(gold)

    baseline_recall = statistics.fmean(baseline_value(row) for row in baseline_rows)
    baseline_by_category: dict[int, list[float]] = defaultdict(list)
    for row in baseline_rows:
        baseline_by_category[int(row["category"])].append(baseline_value(row))
    baseline_category = {
        category: statistics.fmean(values)
        for category, values in baseline_by_category.items()
    }

    total_latencies = [
        float(retrieval[question_id].get("latency_seconds") or 0.0)
        + float(row.get("reranker_seconds") or 0.0)
        for question_id, row in reranked.items()
    ]
    mean_total = statistics.fmean(total_latencies)
    p95_total = sorted(total_latencies)[max(0, math.ceil(len(total_latencies) * 0.95) - 1)]
    policies: list[dict[str, Any]] = []
    for depth in sorted(set(depths)):
        for cross_weight in (0.5, 0.65, 0.8, 0.9, 1.0):
            for cap in (1, 2, 3, 5, 10):
                recalls: list[float] = []
                by_category: dict[int, list[float]] = defaultdict(list)
                for question_id, retrieval_row in retrieval.items():
                    gold = {str(value) for value in retrieval_row.get("evidence") or []}
                    if not gold:
                        continue
                    selected = _select(
                        list(reranked[question_id].get("reranked_candidates") or []),
                        depth=depth,
                        top_k=top_k,
                        cross_weight=cross_weight,
                        max_per_session=cap,
                    )
                    found = gold & {str(item.get("evidence_id") or "") for item in selected}
                    recall = len(found) / len(gold)
                    recalls.append(recall)
                    by_category[int(retrieval_row["category"])].append(recall)
                category_recall = {
                    category: statistics.fmean(values)
                    for category, values in by_category.items()
                }
                category_drops = {
                    category: baseline_category[category] - value
                    for category, value in category_recall.items()
                }
                macro = statistics.fmean(recalls)
                checks = {
                    "recall_improvement": macro - baseline_recall >= min_recall_improvement,
                    "category_non_regression": max(category_drops.values(), default=0.0) <= max_category_drop,
                    "mean_latency": mean_total <= max_mean_total_seconds,
                    "p95_latency": p95_total <= max_p95_total_seconds,
                }
                policies.append(
                    {
                        "candidate_depth": depth,
                        "cross_weight": cross_weight,
                        "max_per_session": cap,
                        "macro_recall_at_k": round(macro, 6),
                        "recall_improvement": round(macro - baseline_recall, 6),
                        "recall_by_category": {
                            str(key): round(value, 6) for key, value in sorted(category_recall.items())
                        },
                        "maximum_category_drop": round(max(category_drops.values(), default=0.0), 6),
                        "checks": checks,
                        "passed": all(checks.values()),
                    }
                )
    policies.sort(
        key=lambda item: (
            bool(item["passed"]),
            float(item["macro_recall_at_k"]),
            -int(item["candidate_depth"]),
        ),
        reverse=True,
    )
    return {
        "schema_version": 1,
        "question_count": len(retrieval),
        "top_k": top_k,
        "baseline_macro_recall_at_k": round(baseline_recall, 6),
        "mean_total_retrieval_and_reranker_seconds": round(mean_total, 4),
        "p95_total_retrieval_and_reranker_seconds": round(p95_total, 4),
        "promotion_gate_passed": any(item["passed"] for item in policies),
        "best_policy": policies[0],
        "policies": policies,
    }


def main() -> int:
    args = parse_args()
    payload = analyze(
        json.loads(args.retrieval_report.read_text(encoding="utf-8")),
        json.loads(args.reranker_report.read_text(encoding="utf-8")),
        depths=[max(1, value) for value in args.depths],
        top_k=max(1, args.top_k),
        max_mean_total_seconds=max(0.0, args.max_mean_total_seconds),
        max_p95_total_seconds=max(0.0, args.max_p95_total_seconds),
        min_recall_improvement=max(0.0, args.min_recall_improvement),
        max_category_drop=max(0.0, args.max_category_drop),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in payload.items() if key != "policies"}, indent=2))
    return 0 if payload["promotion_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
