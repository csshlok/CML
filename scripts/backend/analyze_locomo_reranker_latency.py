from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Characterize saved LoCoMo reranker latency outliers without inference."
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--retrieval-report", type=Path, required=True)
    parser.add_argument("--reranker-report", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _percentile(values: list[float], percentile: float) -> float:
    return sorted(values)[max(0, math.ceil(len(values) * percentile) - 1)]


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2 or len(left) != len(right):
        return None
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right, strict=True))
    left_scale = math.sqrt(sum((x - left_mean) ** 2 for x in left))
    right_scale = math.sqrt(sum((y - right_mean) ** 2 for y in right))
    if not left_scale or not right_scale:
        return None
    return round(numerator / (left_scale * right_scale), 4)


def _document_text(dataset: list[dict[str, Any]]) -> dict[str, str]:
    output: dict[str, str] = {}
    for conversation in dataset:
        sample_id = str(conversation.get("sample_id") or "")
        for key, turns in (conversation.get("conversation") or {}).items():
            if not key.startswith("session_") or key.endswith("_date_time") or not isinstance(turns, list):
                continue
            date = str((conversation.get("conversation") or {}).get(f"{key}_date_time") or "")
            for turn in turns:
                evidence_id = str(turn.get("dia_id") or "")
                output[f"locomo:{sample_id}:{evidence_id}"] = (
                    f"Date: {date}\n{turn.get('speaker', '')}: {turn.get('text', '')} "
                    f"{turn.get('blip_caption', '')}"
                )
    return output


def analyze(
    dataset: list[dict[str, Any]],
    retrieval_report: dict[str, Any],
    reranker_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    retrieval = {str(row["question_id"]): row for row in retrieval_report.get("results") or []}
    text_by_source = _document_text(dataset)
    runs: list[dict[str, Any]] = []
    outlier_sets: list[set[str]] = []
    latency_maps: list[dict[str, float]] = []
    for report in reranker_reports:
        rows = list(report.get("results") or [])
        depth = int((report.get("protocol") or {}).get("candidate_depth") or 0)
        observations: list[dict[str, Any]] = []
        for row in rows:
            question_id = str(row["question_id"])
            retrieval_row = retrieval[question_id]
            candidate_ids = [
                str(item.get("source_id") or "")
                for item in list(retrieval_row.get("retrieved") or [])[:depth]
            ]
            observations.append(
                {
                    "question_id": question_id,
                    "question": str(retrieval_row.get("question") or ""),
                    "seconds": float(row.get("reranker_seconds") or 0.0),
                    "question_words": len(re.findall(r"\w+", str(retrieval_row.get("question") or ""))),
                    "candidate_chars": sum(len(text_by_source.get(source_id, "")) for source_id in candidate_ids),
                }
            )
        latencies = [item["seconds"] for item in observations]
        threshold = _percentile(latencies, 0.95)
        outliers = [item for item in observations if item["seconds"] >= threshold]
        normal = [item for item in observations if item["seconds"] < threshold]
        outlier_ids = {item["question_id"] for item in outliers}
        outlier_sets.append(outlier_ids)
        latency_maps.append({item["question_id"]: item["seconds"] for item in observations})
        runs.append(
            {
                "candidate_depth": depth,
                "question_count": len(observations),
                "latency_seconds": {
                    "mean": round(statistics.fmean(latencies), 4),
                    "p50": round(_percentile(latencies, 0.50), 4),
                    "p90": round(_percentile(latencies, 0.90), 4),
                    "p95": round(threshold, 4),
                    "p99": round(_percentile(latencies, 0.99), 4),
                    "max": round(max(latencies), 4),
                },
                "correlations": {
                    "question_words": _pearson(
                        [float(item["question_words"]) for item in observations], latencies
                    ),
                    "candidate_chars": _pearson(
                        [float(item["candidate_chars"]) for item in observations], latencies
                    ),
                },
                "p95_outlier_characteristics": {
                    "count": len(outliers),
                    "mean_question_words": round(statistics.fmean(item["question_words"] for item in outliers), 3),
                    "non_outlier_mean_question_words": round(statistics.fmean(item["question_words"] for item in normal), 3),
                    "mean_candidate_chars": round(statistics.fmean(item["candidate_chars"] for item in outliers), 1),
                    "non_outlier_mean_candidate_chars": round(statistics.fmean(item["candidate_chars"] for item in normal), 1),
                    "question_ids": sorted(outlier_ids),
                },
                "slowest_questions": sorted(observations, key=lambda item: item["seconds"], reverse=True)[:20],
            }
        )
    comparisons: list[dict[str, Any]] = []
    for left_index in range(len(runs)):
        for right_index in range(left_index + 1, len(runs)):
            shared_ids = sorted(set(latency_maps[left_index]) & set(latency_maps[right_index]))
            intersection = outlier_sets[left_index] & outlier_sets[right_index]
            union = outlier_sets[left_index] | outlier_sets[right_index]
            comparisons.append(
                {
                    "left_depth": runs[left_index]["candidate_depth"],
                    "right_depth": runs[right_index]["candidate_depth"],
                    "latency_correlation": _pearson(
                        [latency_maps[left_index][value] for value in shared_ids],
                        [latency_maps[right_index][value] for value in shared_ids],
                    ),
                    "p95_outlier_overlap_count": len(intersection),
                    "p95_outlier_jaccard": round(len(intersection) / len(union), 4) if union else 1.0,
                }
            )
    return {"schema_version": 1, "runs": runs, "comparisons": comparisons}


def main() -> int:
    args = parse_args()
    payload = analyze(
        json.loads(args.dataset.read_text(encoding="utf-8")),
        json.loads(args.retrieval_report.read_text(encoding="utf-8")),
        [json.loads(path.read_text(encoding="utf-8")) for path in args.reranker_report],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"runs": [{key: value for key, value in run.items() if key != "slowest_questions"} for run in payload["runs"]], "comparisons": payload["comparisons"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
