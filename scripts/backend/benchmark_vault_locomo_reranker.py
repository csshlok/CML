from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from scripts.backend.benchmark_vault_memory import _flatten_locomo
from scripts.backend.check_vault_memory_regression import canonical_question_ids


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rerank a saved LOCOMO candidate report with a local cross-encoder; "
            "no reader or judge API calls are made."
        )
    )
    parser.add_argument("--locomo", type=Path, required=True)
    parser.add_argument("--retrieval-report", type=Path, required=True)
    parser.add_argument("--cross-encoder", type=Path, required=True)
    parser.add_argument("--backend", choices=("torch", "onnx"), default="torch")
    parser.add_argument("--onnx-file", default="onnx/model_quint8_avx2.onnx")
    parser.add_argument("--questions", type=int, default=100)
    parser.add_argument("--candidate-depth", type=int, default=50)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def rerank_with_cross_encoder(
    model,
    *,
    question: str,
    candidates: list[dict[str, Any]],
    text_by_source_id: dict[str, str],
    top_k: int,
    batch_size: int,
) -> list[dict[str, Any]]:
    available = [
        {**candidate, "retrieval_rank": rank}
        for rank, candidate in enumerate(candidates, start=1)
        if str(candidate.get("source_id") or "") in text_by_source_id
    ]
    pairs = [
        [question, text_by_source_id[str(candidate["source_id"])]]
        for candidate in available
    ]
    if not pairs:
        return []
    predicted = model.predict(
        pairs,
        batch_size=max(1, int(batch_size)),
        show_progress_bar=False,
    )
    scored = [
        {**candidate, "reranker_score": float(score)}
        for candidate, score in zip(available, predicted, strict=True)
    ]
    scored.sort(key=lambda item: item["reranker_score"], reverse=True)
    return scored[: max(1, int(top_k))]


def evaluate(
    model,
    *,
    retrieval_report: dict[str, Any],
    text_by_source_id: dict[str, str],
    question_count: int,
    candidate_depth: int,
    top_k: int,
    batch_size: int,
) -> dict[str, Any]:
    rows = retrieval_report.get("results") or []
    selected_ids = set(canonical_question_ids(rows, question_count))
    selected = [row for row in rows if str(row["question_id"]) in selected_ids]
    results = []
    per_question_seconds: list[float] = []
    started = time.perf_counter()
    for row in selected:
        candidates = list(row.get("retrieved") or [])[: max(1, candidate_depth)]
        question_started = time.perf_counter()
        all_reranked = rerank_with_cross_encoder(
            model,
            question=str(row["question"]),
            candidates=candidates,
            text_by_source_id=text_by_source_id,
            top_k=len(candidates),
            batch_size=batch_size,
        )
        reranker_seconds = time.perf_counter() - question_started
        per_question_seconds.append(reranker_seconds)
        reranked = all_reranked[:top_k]
        gold = {str(value) for value in row.get("evidence") or []}
        baseline_ids = {
            str(item.get("evidence_id") or "") for item in candidates[:top_k]
        }
        reranked_ids = {
            str(item.get("evidence_id") or "") for item in reranked
        }
        baseline_recall = len(gold & baseline_ids) / len(gold) if gold else None
        reranked_recall = len(gold & reranked_ids) / len(gold) if gold else None
        results.append(
            {
                "question_id": row["question_id"],
                "category": row.get("category"),
                "baseline_recall_at_k": baseline_recall,
                "reranked_recall_at_k": reranked_recall,
                "reranked_source_ids": [item["source_id"] for item in reranked],
                "reranker_seconds": round(reranker_seconds, 4),
                "reranked_candidates": [
                    {
                        "source_id": item["source_id"],
                        "evidence_id": item.get("evidence_id"),
                        "retrieval_rank": item["retrieval_rank"],
                        "retrieval_score": item.get("score"),
                        "reranker_score": item["reranker_score"],
                    }
                    for item in all_reranked
                ],
            }
        )
        if len(results) % 25 == 0:
            print(f"reranked {len(results)}/{len(selected)}", flush=True)
    scorable = [row for row in results if row["reranked_recall_at_k"] is not None]
    by_category: dict[int, list[float]] = defaultdict(list)
    baseline_by_category: dict[int, list[float]] = defaultdict(list)
    for row in scorable:
        by_category[int(row["category"])].append(float(row["reranked_recall_at_k"]))
        baseline_by_category[int(row["category"])].append(float(row["baseline_recall_at_k"]))
    return {
        "schema_version": 1,
        "protocol": {
            "question_selection": "canonical SHA-256 ordering",
            "question_count": len(selected),
            "candidate_depth": candidate_depth,
            "top_k": top_k,
            "reader_or_judge_api_calls": 0,
        },
        "summary": {
            "baseline_macro_recall_at_k": round(
                statistics.fmean(float(row["baseline_recall_at_k"]) for row in scorable),
                6,
            ),
            "reranked_macro_recall_at_k": round(
                statistics.fmean(float(row["reranked_recall_at_k"]) for row in scorable),
                6,
            ),
            "reranked_recall_by_category": {
                str(category): round(statistics.fmean(values), 6)
                for category, values in sorted(by_category.items())
            },
            "baseline_recall_by_category": {
                str(category): round(statistics.fmean(values), 6)
                for category, values in sorted(baseline_by_category.items())
            },
            "mean_reranker_seconds": round(statistics.fmean(per_question_seconds), 4),
            "p95_reranker_seconds": round(
                sorted(per_question_seconds)[
                    max(0, math.ceil(len(per_question_seconds) * 0.95) - 1)
                ],
                4,
            ),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        },
        "results": results,
    }


def main() -> int:
    args = parse_args()
    if not args.cross_encoder.is_dir():
        raise RuntimeError(
            "Cross-encoder must be a local model directory; network downloads are disabled."
        )
    from sentence_transformers import CrossEncoder

    dataset = json.loads(args.locomo.read_text(encoding="utf-8"))
    documents, _ = _flatten_locomo(dataset)
    text_by_source_id = {
        str(document["source_id"]): str(document["text"]) for document in documents
    }
    retrieval_report = json.loads(args.retrieval_report.read_text(encoding="utf-8"))
    model_kwargs = None
    if args.backend == "onnx":
        model_kwargs = {
            "file_name": args.onnx_file,
            "provider": "CPUExecutionProvider",
            "export": False,
        }
    model = CrossEncoder(
        str(args.cross_encoder),
        backend=args.backend,
        local_files_only=True,
        model_kwargs=model_kwargs,
    )
    report = evaluate(
        model,
        retrieval_report=retrieval_report,
        text_by_source_id=text_by_source_id,
        question_count=max(1, args.questions),
        candidate_depth=max(1, args.candidate_depth),
        top_k=max(1, args.top_k),
        batch_size=max(1, args.batch_size),
    )
    report["protocol"]["cross_encoder"] = str(args.cross_encoder.resolve())
    report["protocol"]["backend"] = args.backend
    report["protocol"]["onnx_file"] = args.onnx_file if args.backend == "onnx" else None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
