from __future__ import annotations

import argparse
import gc
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.backend.benchmark_vault_colbert_compressed_scale import (  # noqa: E402
    ResourceSampler,
    _directory_bytes,
    _percentile,
    _write_json,
)
from scripts.backend.benchmark_vault_memory import (  # noqa: E402
    _flatten_locomo,
    _select_questions,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure scoped and global retrieval over compressed ColBERT shards."
    )
    parser.add_argument("--locomo", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--model-device", choices=("cuda",), default="cuda")
    parser.add_argument("--primary-report", type=Path, required=True)
    parser.add_argument("--primary-index-root", type=Path, required=True)
    parser.add_argument("--shard-report-dir", type=Path, required=True)
    parser.add_argument("--shard-index-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--questions", type=int, default=100)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--encode-batch-size", type=int, default=128)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def _index_descriptor(report_path: Path, index_root: Path, role: str) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    signature = str(report["configuration_signature"])
    configuration = report["configuration"]
    index_name = f"compressed-{configuration['nbits']}bit-{signature[:12]}"
    return {
        "role": role,
        "report_path": str(report_path.resolve()),
        "index_root": index_root.resolve(),
        "index_name": index_name,
        "configuration": configuration,
    }


def _metrics(
    *,
    questions: list[dict[str, Any]],
    candidates: list[list[dict[str, Any]]],
    latencies: list[float],
    documents: list[dict[str, str]],
    top_k: int,
) -> dict[str, Any]:
    by_source_id = {document["source_id"]: document for document in documents}
    recalls: list[float] = []
    hits: list[float] = []
    synthetic_top_k_counts: list[int] = []
    by_category: dict[int, list[float]] = defaultdict(list)
    result_rows: list[dict[str, Any]] = []
    for question, query_candidates, latency in zip(
        questions, candidates, latencies, strict=True
    ):
        ranked = sorted(query_candidates, key=lambda row: row["score"], reverse=True)[:top_k]
        retrieved_evidence = {
            by_source_id[row["id"]]["evidence_id"]
            for row in ranked
            if row["id"] in by_source_id
            and by_source_id[row["id"]]["sample_id"] == question["sample_id"]
        }
        gold = set(question["evidence"])
        found = gold & retrieved_evidence
        recall = len(found) / len(gold) if gold else 0.0
        recalls.append(recall)
        hits.append(1.0 if found else 0.0)
        by_category[int(question["category"])].append(recall)
        synthetic_count = sum(row["id"].startswith("synthetic:") for row in ranked)
        synthetic_top_k_counts.append(synthetic_count)
        result_rows.append(
            {
                "question_id": question["question_id"],
                "category": question["category"],
                "recall_at_k": round(recall, 6),
                "latency_seconds": round(latency, 6),
                "synthetic_results_in_top_k": synthetic_count,
                "retrieved": ranked,
            }
        )

    return {
        "question_count": len(questions),
        "top_k": top_k,
        "macro_recall_at_k": round(statistics.fmean(recalls), 6),
        "any_evidence_hit_rate_at_k": round(statistics.fmean(hits), 6),
        "macro_recall_by_category": {
            str(category): round(statistics.fmean(values), 6)
            for category, values in sorted(by_category.items())
        },
        "mean_latency_seconds": round(statistics.fmean(latencies), 6),
        "p50_latency_seconds": round(_percentile(latencies, 0.50), 6),
        "p95_latency_seconds": round(_percentile(latencies, 0.95), 6),
        "maximum_latency_seconds": round(max(latencies), 6),
        "mean_synthetic_results_in_top_k": round(
            statistics.fmean(synthetic_top_k_counts), 4
        ),
        "results": result_rows,
    }


def main() -> int:
    args = parse_args()
    from backend.app.core.benchmark_gpu import require_cuda

    cuda_runtime = require_cuda()
    from pylate import indexes, models

    data = json.loads(args.locomo.read_text(encoding="utf-8"))
    documents, all_questions = _flatten_locomo(data)
    questions = _select_questions(
        all_questions,
        args.questions,
        category_scope="standard",
        selection="seeded",
        seed=args.seed,
    )
    questions = [question for question in questions if question["evidence"]]

    descriptors = [
        _index_descriptor(args.primary_report, args.primary_index_root, "primary")
    ]
    descriptors.extend(
        _index_descriptor(path, args.shard_index_root, "distractor")
        for path in sorted(args.shard_report_dir.glob("shard-*.json"))
        if json.loads(path.read_text(encoding="utf-8")).get("checkpoints")
    )

    sampler = ResourceSampler()
    sampler.start()
    try:
        model_started = time.perf_counter()
        model = models.ColBERT(
            model_name_or_path=str(args.model.resolve()), device=args.model_device
        )
        model_load_seconds = time.perf_counter() - model_started
        encode_started = time.perf_counter()
        query_embeddings = model.encode(
            [question["question"] for question in questions],
            batch_size=args.encode_batch_size,
            is_query=True,
            show_progress_bar=False,
        )
        query_encoding_seconds = time.perf_counter() - encode_started

        all_candidates: list[list[dict[str, Any]]] = [[] for _ in questions]
        global_latencies = [0.0 for _ in questions]
        primary_candidates: list[list[dict[str, Any]]] | None = None
        primary_latencies: list[float] | None = None
        index_results: list[dict[str, Any]] = []
        for descriptor in descriptors:
            configuration = descriptor["configuration"]
            open_started = time.perf_counter()
            index = indexes.PLAID(
                index_folder=str(descriptor["index_root"]),
                index_name=descriptor["index_name"],
                override=False,
                use_fast=True,
                nbits=int(configuration["nbits"]),
                n_ivf_probe=int(configuration["n_ivf_probe"]),
                n_full_scores=int(configuration["n_full_scores"]),
                device="cpu",
                low_memory=True,
                show_progress=False,
                use_triton=False,
            )
            open_seconds = time.perf_counter() - open_started
            document_count = len(
                index._index._load_documents_ids_to_plaid_ids()  # noqa: SLF001
            )
            index_latencies: list[float] = []
            index_candidates: list[list[dict[str, Any]]] = []
            for position, query_embedding in enumerate(query_embeddings):
                started = time.perf_counter()
                ranked = index([query_embedding], k=args.top_k)[0]
                latency = time.perf_counter() - started
                index_latencies.append(latency)
                global_latencies[position] += latency
                rows = [
                    {
                        "id": str(hit["id"]),
                        "score": round(float(hit["score"]), 6),
                        "shard": descriptor["index_name"],
                    }
                    for hit in ranked
                ]
                index_candidates.append(rows)
                all_candidates[position].extend(rows)

            if descriptor["role"] == "primary":
                primary_candidates = index_candidates
                primary_latencies = index_latencies
            index_path = descriptor["index_root"] / descriptor["index_name"]
            index_results.append(
                {
                    "role": descriptor["role"],
                    "index_name": descriptor["index_name"],
                    "document_count": document_count,
                    "disk_bytes": _directory_bytes(index_path),
                    "open_seconds": round(open_seconds, 6),
                    "mean_search_seconds": round(
                        statistics.fmean(index_latencies), 6
                    ),
                    "p95_search_seconds": round(
                        _percentile(index_latencies, 0.95), 6
                    ),
                }
            )
            print(
                json.dumps(
                    {
                        "event": "shard_queried",
                        "index": descriptor["index_name"],
                        "documents": document_count,
                        "p95_seconds": index_results[-1]["p95_search_seconds"],
                    }
                ),
                flush=True,
            )
            del index
            gc.collect()

        if primary_candidates is None or primary_latencies is None:
            raise RuntimeError("Primary index was not evaluated.")
        report = {
            "schema_version": 1,
            "cuda_runtime": cuda_runtime,
            "system": "Vault compressed ColBERT sharded scale experiment",
            "item_count": sum(row["document_count"] for row in index_results),
            "shard_count": len(index_results),
            "total_disk_bytes": sum(row["disk_bytes"] for row in index_results),
            "model": str(args.model.resolve()),
            "model_device": args.model_device,
            "model_load_seconds": round(model_load_seconds, 6),
            "query_encoding_seconds": round(query_encoding_seconds, 6),
            "index_results": index_results,
            "scoped_primary": _metrics(
                questions=questions,
                candidates=primary_candidates,
                latencies=primary_latencies,
                documents=documents,
                top_k=args.top_k,
            ),
            "global_sequential": _metrics(
                questions=questions,
                candidates=all_candidates,
                latencies=global_latencies,
                documents=documents,
                top_k=args.top_k,
            ),
            "resource_peaks": {
                "process_rss_bytes": sampler.peak_process_rss_bytes,
                "minimum_system_available_bytes": sampler.minimum_system_available_bytes,
            },
        }
        _write_json(args.output, report)
        print(
            json.dumps(
                {
                    "items": report["item_count"],
                    "shards": report["shard_count"],
                    "disk_gib": round(report["total_disk_bytes"] / 2**30, 4),
                    "scoped_recall_at_10": report["scoped_primary"][
                        "macro_recall_at_k"
                    ],
                    "scoped_p95_seconds": report["scoped_primary"][
                        "p95_latency_seconds"
                    ],
                    "global_recall_at_10": report["global_sequential"][
                        "macro_recall_at_k"
                    ],
                    "global_p95_seconds": report["global_sequential"][
                        "p95_latency_seconds"
                    ],
                },
                indent=2,
            )
        )
    finally:
        sampler.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
