from __future__ import annotations

import argparse
import hashlib
import json
import math
import pickle
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.backend.benchmark_vault_memory import (  # noqa: E402
    _file_sha256,
    _flatten_locomo,
    _select_questions,
)
from backend.app.core.benchmark_gpu import require_cuda  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate exact ColBERT late-interaction retrieval on LoCoMo."
    )
    parser.add_argument("--locomo", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--questions", type=int, default=300)
    parser.add_argument(
        "--selection", choices=("seeded", "first", "all"), default="seeded"
    )
    parser.add_argument(
        "--category-scope", choices=("standard", "adversarial", "all"), default="standard"
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=32)
    return parser.parse_args()


def _cache_signature(model: Path, documents: list[dict[str, str]]) -> str:
    identity = {
        "model": str(model.resolve()),
        "documents": [document["source_id"] + "\0" + document["text"] for document in documents],
    }
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _encode_documents(
    model: Any,
    documents: list[dict[str, str]],
    *,
    cache_dir: Path,
    signature: str,
    batch_size: int,
) -> tuple[list[Any], float, bool, Path]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"locomo-colbert-documents-{signature[:16]}.pickle"
    if cache_path.exists():
        started = time.perf_counter()
        with cache_path.open("rb") as handle:
            embeddings = pickle.load(handle)  # noqa: S301 - trusted local benchmark cache
        return embeddings, time.perf_counter() - started, True, cache_path

    started = time.perf_counter()
    embeddings = model.encode(
        [document["text"] for document in documents],
        batch_size=max(1, batch_size),
        is_query=False,
        show_progress_bar=True,
    )
    elapsed = time.perf_counter() - started
    with cache_path.open("wb") as handle:
        pickle.dump(embeddings, handle, protocol=pickle.HIGHEST_PROTOCOL)
    return embeddings, elapsed, False, cache_path


def _embedding_storage(embeddings: list[Any], dense_dimension: int = 384) -> dict[str, Any]:
    token_count = sum(int(embedding.shape[0]) for embedding in embeddings)
    byte_count = sum(int(embedding.nbytes) for embedding in embeddings)
    dense_bytes = len(embeddings) * dense_dimension * 4
    return {
        "token_vector_count": token_count,
        "late_interaction_bytes": byte_count,
        "dense_384_float32_bytes": dense_bytes,
        "late_interaction_to_dense_ratio": round(byte_count / max(dense_bytes, 1), 4),
    }


def _evaluate(
    model: Any,
    documents: list[dict[str, str]],
    document_embeddings: list[Any],
    questions: list[dict[str, Any]],
    *,
    top_k: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from pylate import rank

    grouped: dict[str, list[int]] = defaultdict(list)
    for index, document in enumerate(documents):
        grouped[document["sample_id"]].append(index)
    by_id = {document["source_id"]: document for document in documents}

    results: list[dict[str, Any]] = []
    latencies: list[float] = []
    for position, question in enumerate(questions, start=1):
        candidate_indices = grouped[question["sample_id"]]
        candidate_ids = [documents[index]["source_id"] for index in candidate_indices]
        candidate_embeddings = [document_embeddings[index] for index in candidate_indices]
        started = time.perf_counter()
        query_embedding = model.encode([question["question"]], is_query=True)
        ranked = rank.rerank(
            documents_ids=[candidate_ids],
            queries_embeddings=query_embedding,
            documents_embeddings=[candidate_embeddings],
            device="cuda",
        )[0]
        latency = time.perf_counter() - started
        latencies.append(latency)

        retrieved = []
        for hit in ranked[: max(1, top_k)]:
            document = by_id[str(hit["id"])]
            retrieved.append(
                {
                    "source_id": document["source_id"],
                    "sample_id": document["sample_id"],
                    "evidence_id": document["evidence_id"],
                    "score": round(float(hit["score"]), 6),
                    "semantic_score": round(float(hit["score"]), 6),
                    "bm25_score": None,
                }
            )
        gold = set(question["evidence"])
        found = gold & {hit["evidence_id"] for hit in retrieved}
        recall = len(found) / len(gold) if gold else None
        results.append(
            {
                **question,
                "rank": position,
                "retrieved": retrieved,
                "found_evidence": sorted(found),
                "recall_at_k": recall,
                "any_evidence_at_k": bool(found) if gold else None,
                "latency_seconds": round(latency, 4),
            }
        )
        if position % 25 == 0:
            print(f"evaluated {position}/{len(questions)}", flush=True)

    evidence_rows = [row for row in results if row["recall_at_k"] is not None]
    by_category: dict[int, list[float]] = defaultdict(list)
    for row in evidence_rows:
        by_category[row["category"]].append(float(row["recall_at_k"]))
    ordered_latency = sorted(latencies)
    summary = {
        "question_count": len(results),
        "evidence_question_count": len(evidence_rows),
        "questions_without_evidence": len(results) - len(evidence_rows),
        "macro_recall_at_k": round(
            statistics.fmean(float(row["recall_at_k"]) for row in evidence_rows), 6
        ),
        "any_evidence_hit_rate_at_k": round(
            statistics.fmean(1.0 if row["any_evidence_at_k"] else 0.0 for row in evidence_rows),
            6,
        ),
        "category_counts": dict(sorted(Counter(row["category"] for row in results).items())),
        "macro_recall_by_category": {
            str(category): round(statistics.fmean(values), 6)
            for category, values in sorted(by_category.items())
        },
        "mean_query_latency_seconds": round(statistics.fmean(latencies), 4),
        "p50_query_latency_seconds": round(
            ordered_latency[max(0, math.ceil(len(ordered_latency) * 0.50) - 1)], 4
        ),
        "p95_query_latency_seconds": round(
            ordered_latency[max(0, math.ceil(len(ordered_latency) * 0.95) - 1)], 4
        ),
    }
    return results, summary


def main() -> int:
    args = parse_args()
    from pylate import models

    cuda_runtime = require_cuda()

    data = json.loads(args.locomo.read_text(encoding="utf-8"))
    documents, all_questions = _flatten_locomo(data)
    questions = _select_questions(
        all_questions,
        args.questions,
        category_scope=args.category_scope,
        selection=args.selection,
        seed=args.seed,
    )
    model = models.ColBERT(model_name_or_path=str(args.model.resolve()), device="cuda")
    signature = _cache_signature(args.model, documents)
    document_embeddings, indexing_seconds, cache_hit, cache_path = _encode_documents(
        model,
        documents,
        cache_dir=args.cache_dir,
        signature=signature,
        batch_size=args.batch_size,
    )
    results, summary = _evaluate(
        model,
        documents,
        document_embeddings,
        questions,
        top_k=max(1, args.top_k),
    )
    report = {
        "schema_version": 2,
        "cuda_runtime": cuda_runtime,
        "system": "Vault late-interaction retrieval prototype (Odin not applicable)",
        "dataset": "LOCOMO official locomo10.json",
        "protocol": {
            "selection": f"all {len(questions)} eligible questions in official file order"
            if args.selection == "all"
            else f"{args.selection} selection of {len(questions)} questions",
            "selection_mode": args.selection,
            "category_scope": args.category_scope,
            "seed": args.seed if args.selection == "seeded" else None,
            "dataset_sha256": _file_sha256(args.locomo),
            "question_ids": [question["question_id"] for question in questions],
            "top_k": args.top_k,
            "granularity": "dialog turn with released image caption when present",
            "retrieval_scope": "the question's conversation, matching the official RAG protocol",
            "retriever": "exact ColBERT MaxSim late interaction; semantic only",
            "embedding_model": str(args.model),
            "qa_reader": None,
            "qa_judge": None,
        },
        "index": {
            "document_count": len(documents),
            "embedding_seconds": round(indexing_seconds, 3),
            "embedding_cache_hit": cache_hit,
            "embedding_cache_signature": signature,
            "cache_path": str(cache_path),
            **_embedding_storage(document_embeddings),
        },
        "summary": summary,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**summary, "index": report["index"], "output": str(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
