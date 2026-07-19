from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze saved LoCoMo candidates at several cutoffs without model calls."
    )
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cutoffs", type=int, nargs="+", default=[10, 20, 30, 50])
    return parser.parse_args()


def _evidence_ids(row: dict[str, Any], limit: int) -> set[str]:
    sample_id = str(row.get("sample_id") or "")
    return {
        str(item.get("evidence_id") or "")
        for item in list(row.get("retrieved") or [])[:limit]
        if str(item.get("sample_id") or "") == sample_id
    }


def _metrics(rows: list[dict[str, Any]], cutoff: int) -> dict[str, Any]:
    scorable = [row for row in rows if row.get("evidence")]
    recalls: list[float] = []
    hits: list[float] = []
    by_category: dict[int, list[float]] = defaultdict(list)
    for row in scorable:
        gold = {str(item) for item in row["evidence"]}
        found = gold & _evidence_ids(row, cutoff)
        recall = len(found) / len(gold)
        recalls.append(recall)
        hits.append(float(bool(found)))
        by_category[int(row["category"])].append(recall)
    return {
        "cutoff": cutoff,
        "macro_recall": round(statistics.fmean(recalls), 6),
        "any_evidence_hit_rate": round(statistics.fmean(hits), 6),
        "perfect_recall_count": sum(value == 1.0 for value in recalls),
        "zero_recall_count": sum(value == 0.0 for value in recalls),
        "recall_by_category": {
            str(category): round(statistics.fmean(values), 6)
            for category, values in sorted(by_category.items())
        },
    }


def _session_id(candidate: dict[str, Any]) -> str:
    return str(candidate.get("evidence_id") or "").split(":", 1)[0]


_STOPWORDS = {
    "about", "after", "before", "could", "from", "have", "their", "there",
    "these", "they", "this", "those", "what", "when", "where", "which",
    "with", "would", "the", "and", "for", "was", "were", "did", "does",
}
_TEMPORAL_RE = re.compile(
    r"\b(when|before|after|first|last|earlier|later|day|week|month|year|"
    r"yesterday|tomorrow|ago|since|until|during|long)\b",
    re.IGNORECASE,
)
_REFERENCE_RE = re.compile(
    r"\b(it|that|this|they|them|he|she|his|her|their|there)\b", re.IGNORECASE
)


def _terms(value: str) -> set[str]:
    return {
        term
        for term in re.findall(r"[a-z0-9]+", str(value or "").casefold())
        if len(term) >= 3 and term not in _STOPWORDS
    }


def _dataset_evidence_text(dataset: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    output: dict[tuple[str, str], str] = {}
    for conversation in dataset:
        sample_id = str(conversation.get("sample_id") or "")
        for key, turns in (conversation.get("conversation") or {}).items():
            if not key.startswith("session_") or key.endswith("_date_time") or not isinstance(turns, list):
                continue
            for turn in turns:
                evidence_id = str(turn.get("dia_id") or "")
                text = " ".join(
                    part for part in (str(turn.get("text") or ""), str(turn.get("blip_caption") or "")) if part
                )
                output[(sample_id, evidence_id)] = text
    return output


def _group_characteristics(
    rows: list[dict[str, Any]], evidence_text: dict[tuple[str, str], str]
) -> dict[str, Any]:
    if not rows:
        return {"question_count": 0}
    question_lengths: list[int] = []
    evidence_counts: list[int] = []
    overlaps: list[float] = []
    temporal = 0
    reference_heavy = 0
    for row in rows:
        question = str(row.get("question") or "")
        question_terms = _terms(question)
        gold_text = " ".join(
            evidence_text.get((str(row.get("sample_id") or ""), str(evidence_id)), "")
            for evidence_id in row.get("evidence") or []
        )
        gold_terms = _terms(gold_text)
        question_lengths.append(len(re.findall(r"\w+", question)))
        evidence_counts.append(len(row.get("evidence") or []))
        overlaps.append(
            len(question_terms & gold_terms) / len(question_terms)
            if question_terms
            else 0.0
        )
        temporal += bool(_TEMPORAL_RE.search(question))
        reference_heavy += bool(_REFERENCE_RE.search(question))
    return {
        "question_count": len(rows),
        "mean_question_words": round(statistics.fmean(question_lengths), 3),
        "p95_question_words": sorted(question_lengths)[
            max(0, math.ceil(len(question_lengths) * 0.95) - 1)
        ],
        "mean_gold_evidence_count": round(statistics.fmean(evidence_counts), 3),
        "mean_question_to_gold_lexical_overlap": round(statistics.fmean(overlaps), 4),
        "temporal_marker_rate": round(temporal / len(rows), 4),
        "pronoun_or_reference_marker_rate": round(reference_heavy / len(rows), 4),
    }


def _diverse_ids(row: dict[str, Any], *, top_k: int, max_per_session: int) -> set[str]:
    selected: list[dict[str, Any]] = []
    session_counts: dict[str, int] = defaultdict(int)
    for candidate in row.get("retrieved") or []:
        session = _session_id(candidate)
        if session_counts[session] >= max_per_session:
            continue
        selected.append(candidate)
        session_counts[session] += 1
        if len(selected) >= top_k:
            break
    return {str(item.get("evidence_id") or "") for item in selected}


def _diversity_grid(rows: list[dict[str, Any]], *, top_k: int = 10) -> list[dict[str, Any]]:
    scorable = [row for row in rows if row.get("evidence")]
    output: list[dict[str, Any]] = []
    for cap in (1, 2, 3, 4, 5, 10):
        recalls = []
        for row in scorable:
            gold = {str(item) for item in row["evidence"]}
            recalls.append(len(gold & _diverse_ids(row, top_k=top_k, max_per_session=cap)) / len(gold))
        output.append(
            {
                "max_per_session": cap,
                "macro_recall_at_10": round(statistics.fmean(recalls), 6),
                "perfect_recall_count": sum(value == 1.0 for value in recalls),
                "zero_recall_count": sum(value == 0.0 for value in recalls),
            }
        )
    return output


def analyze(
    report: dict[str, Any],
    cutoffs: list[int],
    *,
    dataset: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = list(report.get("results") or [])
    if not rows:
        raise ValueError("retrieval report has no results")
    maximum = max(cutoffs)
    if any(len(row.get("retrieved") or []) < maximum for row in rows):
        raise ValueError(f"retrieval report does not contain {maximum} candidates for every question")
    scorable = [row for row in rows if row.get("evidence")]
    candidate_generation_failures: list[str] = []
    ranking_failures: list[str] = []
    partial_at_max: list[str] = []
    decomposition_by_category: dict[int, dict[str, int]] = defaultdict(
        lambda: {
            "evidence_questions": 0,
            "candidate_generation_zero_at_max": 0,
            "partial_evidence_at_max": 0,
            "ranking_recoverable_between_10_and_max": 0,
        }
    )
    for row in scorable:
        category = int(row["category"])
        decomposition_by_category[category]["evidence_questions"] += 1
        gold = {str(item) for item in row["evidence"]}
        at_10 = gold & _evidence_ids(row, 10)
        at_max = gold & _evidence_ids(row, maximum)
        if not at_max:
            candidate_generation_failures.append(str(row["question_id"]))
            decomposition_by_category[category]["candidate_generation_zero_at_max"] += 1
        elif len(at_max) < len(gold):
            partial_at_max.append(str(row["question_id"]))
            decomposition_by_category[category]["partial_evidence_at_max"] += 1
        if len(at_10) < len(at_max):
            ranking_failures.append(str(row["question_id"]))
            decomposition_by_category[category]["ranking_recoverable_between_10_and_max"] += 1
    latencies = [float(row.get("latency_seconds") or 0.0) for row in rows]
    zero_ids = set(candidate_generation_failures)
    zero_rows = [row for row in scorable if str(row["question_id"]) in zero_ids]
    found_rows = [row for row in scorable if str(row["question_id"]) not in zero_ids]
    evidence_text = _dataset_evidence_text(dataset or [])
    sample_totals: dict[str, int] = defaultdict(int)
    sample_zero: dict[str, int] = defaultdict(int)
    for row in scorable:
        sample_id = str(row.get("sample_id") or "")
        sample_totals[sample_id] += 1
        if str(row["question_id"]) in zero_ids:
            sample_zero[sample_id] += 1
    sample_rates = [
        {
            "sample_id": sample_id,
            "evidence_questions": total,
            "zero_at_max_count": sample_zero[sample_id],
            "zero_at_max_rate": round(sample_zero[sample_id] / total, 4),
        }
        for sample_id, total in sample_totals.items()
    ]
    sample_rates.sort(key=lambda item: (item["zero_at_max_rate"], item["zero_at_max_count"]), reverse=True)
    return {
        "schema_version": 1,
        "question_count": len(rows),
        "evidence_question_count": len(scorable),
        "cutoffs": [_metrics(rows, cutoff) for cutoff in sorted(set(cutoffs))],
        "failure_decomposition": {
            "candidate_generation_zero_at_max_count": len(candidate_generation_failures),
            "candidate_generation_zero_at_max_question_ids": candidate_generation_failures,
            "partial_evidence_at_max_count": len(partial_at_max),
            "partial_evidence_at_max_question_ids": partial_at_max,
            "ranking_recoverable_between_10_and_max_count": len(ranking_failures),
            "ranking_recoverable_between_10_and_max_question_ids": ranking_failures,
            "by_category": {
                str(category): counts
                for category, counts in sorted(decomposition_by_category.items())
            },
        },
        "session_diversity_grid": _diversity_grid(rows),
        "zero_at_max_characterization": {
            "maximum_cutoff": maximum,
            "zero_group": _group_characteristics(zero_rows, evidence_text),
            "nonzero_group": _group_characteristics(found_rows, evidence_text),
            "by_conversation": sample_rates,
        },
        "latency": {
            "mean_seconds": round(statistics.fmean(latencies), 4),
            "p95_seconds": round(sorted(latencies)[max(0, math.ceil(len(latencies) * 0.95) - 1)], 4),
        },
    }


def main() -> int:
    args = parse_args()
    payload = analyze(
        json.loads(args.report.read_text(encoding="utf-8")),
        [max(1, value) for value in args.cutoffs],
        dataset=(
            json.loads(args.dataset.read_text(encoding="utf-8"))
            if args.dataset
            else None
        ),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in payload.items() if key != "failure_decomposition"}, indent=2))
    print(json.dumps({key: len(value) if isinstance(value, list) else value for key, value in payload["failure_decomposition"].items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
