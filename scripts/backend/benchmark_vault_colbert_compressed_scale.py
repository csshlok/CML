from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.backend.benchmark_vault_memory import (  # noqa: E402
    _file_sha256,
    _flatten_locomo,
    _select_questions,
)


NAMES = (
    "Amina",
    "Arjun",
    "Beatrice",
    "Caleb",
    "Chen",
    "Diego",
    "Elena",
    "Fatima",
    "Gabriel",
    "Hana",
    "Ibrahim",
    "Jun",
    "Keira",
    "Lena",
    "Mateo",
    "Nadia",
    "Omar",
    "Priya",
    "Quinn",
    "Ravi",
    "Sofia",
    "Tariq",
    "Uma",
    "Victor",
    "Willow",
    "Xavier",
    "Yara",
    "Zane",
)
CITIES = (
    "Adelaide",
    "Amsterdam",
    "Athens",
    "Bangalore",
    "Barcelona",
    "Berlin",
    "Boston",
    "Brisbane",
    "Cairo",
    "Cape Town",
    "Chicago",
    "Copenhagen",
    "Dublin",
    "Edinburgh",
    "Helsinki",
    "Istanbul",
    "Jakarta",
    "Kyoto",
    "Lisbon",
    "London",
    "Madrid",
    "Melbourne",
    "Montreal",
    "Mumbai",
    "Nairobi",
    "Oslo",
    "Paris",
    "Porto",
    "Prague",
    "Reykjavik",
    "Rome",
    "Seoul",
    "Singapore",
    "Stockholm",
    "Sydney",
    "Taipei",
    "Tallinn",
    "Tokyo",
    "Toronto",
    "Valencia",
    "Vienna",
    "Warsaw",
    "Wellington",
    "Zurich",
)
PROJECTS = (
    "accessibility",
    "archive",
    "billing",
    "catalogue",
    "community",
    "compliance",
    "customer research",
    "data migration",
    "design system",
    "education",
    "energy audit",
    "field study",
    "fundraising",
    "garden",
    "health programme",
    "inventory",
    "knowledge base",
    "launch",
    "library",
    "logistics",
    "maintenance",
    "market research",
    "membership",
    "mobile application",
    "museum",
    "onboarding",
    "operations",
    "partnership",
    "policy review",
    "product research",
    "quality programme",
    "renovation",
    "roadmap",
    "safety review",
    "scholarship",
    "security audit",
    "support programme",
    "training",
    "travel plan",
    "volunteer programme",
)
ACTIONS = (
    "approve",
    "archive",
    "audit",
    "cancel",
    "compare",
    "deliver",
    "document",
    "expand",
    "inspect",
    "launch",
    "measure",
    "merge",
    "migrate",
    "pause",
    "publish",
    "redesign",
    "repair",
    "replace",
    "review",
    "schedule",
    "simplify",
    "test",
    "translate",
    "update",
)
ASSETS = (
    "annual report",
    "application form",
    "budget forecast",
    "client portal",
    "contract",
    "data export",
    "delivery route",
    "design proposal",
    "equipment list",
    "event calendar",
    "feedback survey",
    "floor plan",
    "funding request",
    "incident log",
    "indexing pipeline",
    "insurance policy",
    "meeting agenda",
    "migration checklist",
    "operating manual",
    "performance report",
    "project brief",
    "release checklist",
    "research notes",
    "risk register",
    "service agreement",
    "support handbook",
    "training guide",
    "travel itinerary",
    "vendor proposal",
    "website content",
)
STATUSES = (
    "approved",
    "awaiting review",
    "blocked",
    "cancelled",
    "completed",
    "drafted",
    "in progress",
    "on hold",
    "scheduled",
    "under discussion",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Measure a compressed, persistent ColBERT index at realistic Vault scales."
        )
    )
    parser.add_argument("--locomo", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--model-device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--index-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--targets", type=int, nargs="+", default=[100_000, 1_000_000])
    parser.add_argument("--batch-size", type=int, default=5_000)
    parser.add_argument("--encode-batch-size", type=int, default=128)
    parser.add_argument("--questions", type=int, default=100)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--nbits", type=int, choices=(1, 2, 4, 8), default=2)
    parser.add_argument("--n-ivf-probe", type=int, default=8)
    parser.add_argument("--n-full-scores", type=int, default=1_024)
    parser.add_argument("--update-kmeans-niters", type=int, default=4)
    parser.add_argument("--centroid-expansion-buffer", type=int, default=100)
    parser.add_argument("--num-threads", type=int, default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--synthetic-only", action="store_true")
    parser.add_argument("--synthetic-offset", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def _mix64(value: int) -> int:
    value = (value + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    return value ^ (value >> 31)


def _choice(values: tuple[str, ...], value: int, shift: int) -> str:
    return values[_mix64(value + shift) % len(values)]


def _synthetic_document(position: int) -> str:
    first = _choice(NAMES, position, 11)
    second = _choice(NAMES, position, 29)
    city = _choice(CITIES, position, 47)
    project = _choice(PROJECTS, position, 71)
    action = _choice(ACTIONS, position, 101)
    asset = _choice(ASSETS, position, 131)
    status = _choice(STATUSES, position, 173)
    month = 1 + (_mix64(position + 191) % 12)
    day = 1 + (_mix64(position + 211) % 28)
    year = 2018 + (_mix64(position + 229) % 9)
    reference = f"VX-{_mix64(position + 251) & 0xFFFFFF:06X}"
    return (
        f"Archive record {reference}. On {year:04d}-{month:02d}-{day:02d}, {first} and "
        f"{second} met in {city} about the {project}. They agreed to {action} the "
        f"{asset}. {first} remained the owner, the status was {status}, and the team "
        "planned a written follow-up after the next monthly review."
    )


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[max(0, math.ceil(len(ordered) * percentile) - 1)]


def _directory_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _merge_resource_peaks(
    report: dict[str, Any], sampler: ResourceSampler
) -> dict[str, int | None]:
    previous = report.get("resource_peaks", {})
    previous_rss = int(previous.get("process_rss_bytes") or 0)
    previous_available = previous.get("minimum_system_available_bytes")
    current_available = sampler.minimum_system_available_bytes
    available_values = [
        int(value)
        for value in (previous_available, current_available)
        if value is not None
    ]
    return {
        "process_rss_bytes": max(previous_rss, sampler.peak_process_rss_bytes),
        "minimum_system_available_bytes": min(available_values)
        if available_values
        else None,
    }


@dataclass
class ResourceSampler:
    interval_seconds: float = 0.25
    peak_process_rss_bytes: int = 0
    minimum_system_available_bytes: int | None = None
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    def start(self) -> None:
        import psutil

        process = psutil.Process(os.getpid())

        def sample() -> None:
            while not self._stop.wait(self.interval_seconds):
                rss = process.memory_info().rss
                available = psutil.virtual_memory().available
                self.peak_process_rss_bytes = max(self.peak_process_rss_bytes, rss)
                if self.minimum_system_available_bytes is None:
                    self.minimum_system_available_bytes = available
                else:
                    self.minimum_system_available_bytes = min(
                        self.minimum_system_available_bytes, available
                    )

        self._thread = threading.Thread(target=sample, name="resource-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)


def _configuration_signature(args: argparse.Namespace) -> str:
    configuration = {
        "locomo_sha256": _file_sha256(args.locomo),
        "model": str(args.model.resolve()),
        "model_device": args.model_device,
        "nbits": args.nbits,
        "seed": args.seed,
        "generator": "vault-like-v1",
    }
    if args.synthetic_only or args.synthetic_offset:
        configuration["synthetic_only"] = args.synthetic_only
        configuration["synthetic_offset"] = args.synthetic_offset
    return hashlib.sha256(
        json.dumps(configuration, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _document_batch(
    start: int,
    stop: int,
    documents: list[dict[str, str]],
    *,
    synthetic_only: bool,
    synthetic_offset: int,
) -> tuple[list[str], list[str]]:
    identifiers: list[str] = []
    texts: list[str] = []
    for position in range(start, stop):
        if not synthetic_only and position < len(documents):
            document = documents[position]
            identifiers.append(document["source_id"])
            texts.append(document["text"])
        else:
            synthetic_position = (
                synthetic_offset + position
                if synthetic_only
                else synthetic_offset + position - len(documents)
            )
            identifiers.append(f"synthetic:{synthetic_position:09d}")
            texts.append(_synthetic_document(synthetic_position))
    return identifiers, texts


def _existing_document_count(index: Any) -> int:
    mapping = index._index._load_documents_ids_to_plaid_ids()  # noqa: SLF001
    return len(mapping)


def _add_documents(
    *,
    index: Any,
    identifiers: list[str],
    embeddings: list[Any],
    update_kmeans_niters: int,
    centroid_expansion_buffer: int,
) -> None:
    backend = index._index  # noqa: SLF001
    if not backend.is_indexed or (
        update_kmeans_niters == backend.kmeans_niters
        and centroid_expansion_buffer == 100
    ):
        index.add_documents(
            documents_ids=identifiers,
            documents_embeddings=embeddings,
        )
        return

    from pylate.indexes.utils import convert_embeddings_to_torch

    torch_embeddings = convert_embeddings_to_torch(embeddings)
    documents_to_plaid = backend._load_documents_ids_to_plaid_ids()  # noqa: SLF001
    plaid_to_documents = backend._load_plaid_ids_to_documents_ids()  # noqa: SLF001
    current_max_id = max(plaid_to_documents) if plaid_to_documents else -1
    backend.fast_plaid.update(
        documents_embeddings=torch_embeddings,
        kmeans_niters=update_kmeans_niters,
        max_points_per_centroid=backend.max_points_per_centroid,
        n_samples_kmeans=backend.n_samples_kmeans,
        seed=backend.seed,
        buffer_size=centroid_expansion_buffer,
        use_triton_kmeans=backend.use_triton,
    )
    plaid_ids = list(
        range(current_max_id + 1, current_max_id + 1 + len(torch_embeddings))
    )
    documents_to_plaid.update(zip(identifiers, plaid_ids, strict=True))
    plaid_to_documents.update(zip(plaid_ids, identifiers, strict=True))
    backend._save_mappings(documents_to_plaid, plaid_to_documents)  # noqa: SLF001


def _evaluate(
    *,
    model: Any,
    index: Any,
    questions: list[dict[str, Any]],
    documents: list[dict[str, str]],
    top_k: int,
    encode_batch_size: int,
) -> dict[str, Any]:
    by_source_id = {document["source_id"]: document for document in documents}
    query_texts = [question["question"] for question in questions]
    encode_started = time.perf_counter()
    query_embeddings = model.encode(
        query_texts,
        batch_size=max(1, encode_batch_size),
        is_query=True,
        show_progress_bar=False,
    )
    query_encoding_seconds = time.perf_counter() - encode_started

    latencies: list[float] = []
    recalls: list[float] = []
    hits: list[float] = []
    result_rows: list[dict[str, Any]] = []
    for question, query_embedding in zip(questions, query_embeddings, strict=True):
        started = time.perf_counter()
        ranked = index([query_embedding], k=top_k)[0]
        latency = time.perf_counter() - started
        latencies.append(latency)
        retrieved_ids = [str(hit["id"]) for hit in ranked]
        retrieved_evidence = {
            by_source_id[source_id]["evidence_id"]
            for source_id in retrieved_ids
            if source_id in by_source_id
            and by_source_id[source_id]["sample_id"] == question["sample_id"]
        }
        gold = set(question["evidence"])
        found = gold & retrieved_evidence
        recall = len(found) / len(gold) if gold else 0.0
        recalls.append(recall)
        hits.append(1.0 if found else 0.0)
        result_rows.append(
            {
                "question_id": question["question_id"],
                "category": question["category"],
                "gold_evidence_count": len(gold),
                "found_evidence_count": len(found),
                "recall_at_k": round(recall, 6),
                "latency_seconds": round(latency, 6),
                "retrieved_ids": retrieved_ids,
            }
        )

    return {
        "question_count": len(questions),
        "top_k": top_k,
        "global_scope": True,
        "query_encoding_seconds": round(query_encoding_seconds, 4),
        "macro_recall_at_k": round(statistics.fmean(recalls), 6),
        "any_evidence_hit_rate_at_k": round(statistics.fmean(hits), 6),
        "mean_search_latency_seconds": round(statistics.fmean(latencies), 6),
        "p50_search_latency_seconds": round(_percentile(latencies, 0.50), 6),
        "p95_search_latency_seconds": round(_percentile(latencies, 0.95), 6),
        "maximum_search_latency_seconds": round(max(latencies), 6),
        "results": result_rows,
    }


def _batched_ranges(start: int, stop: int, batch_size: int) -> Iterable[tuple[int, int]]:
    cursor = start
    while cursor < stop:
        next_cursor = min(stop, cursor + batch_size)
        yield cursor, next_cursor
        cursor = next_cursor


def main() -> int:
    args = parse_args()
    targets = sorted(set(args.targets))
    if not targets or targets[0] <= 0:
        raise ValueError("Targets must contain positive item counts.")
    if args.batch_size <= 0 or args.encode_batch_size <= 0:
        raise ValueError("Batch sizes must be positive.")

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
    signature = _configuration_signature(args)
    index_name = f"compressed-{args.nbits}bit-{signature[:12]}"
    index_path = args.index_root / index_name

    if args.output.exists():
        report = json.loads(args.output.read_text(encoding="utf-8"))
        if report.get("configuration_signature") != signature:
            raise RuntimeError("Existing report configuration does not match this run.")
    else:
        report = {
            "schema_version": 1,
            "system": "Vault compressed ColBERT scale experiment",
            "configuration_signature": signature,
            "configuration": {
                "dataset": "LoCoMo seed plus deterministic vault-like distractors",
                "locomo": str(args.locomo.resolve()),
                "locomo_sha256": _file_sha256(args.locomo),
                "real_document_count": 0 if args.synthetic_only else len(documents),
                "synthetic_only": args.synthetic_only,
                "synthetic_offset": args.synthetic_offset,
                "model": str(args.model.resolve()),
                "model_device": args.model_device,
                "index_backend": "PyLate FastPLAID",
                "nbits": args.nbits,
                "batch_size": args.batch_size,
                "encode_batch_size": args.encode_batch_size,
                "n_ivf_probe": args.n_ivf_probe,
                "n_full_scores": args.n_full_scores,
                "top_k": args.top_k,
                "question_count": len(questions),
                "seed": args.seed,
                "targets": targets,
                "scope": "global index across real records and synthetic distractors",
            },
            "batches": [],
            "checkpoints": {},
            "runs": [],
        }

    report.setdefault("runs", []).append(
        {
            "started_at_unix": time.time(),
            "resume": bool(args.resume),
            "batch_size": args.batch_size,
            "targets": targets,
            "update_kmeans_niters": args.update_kmeans_niters,
            "centroid_expansion_buffer": args.centroid_expansion_buffer,
        }
    )

    override = not args.resume
    if index_path.exists() and not args.resume:
        raise RuntimeError(
            f"Index already exists at {index_path}. Use --resume or choose another root."
        )

    sampler = ResourceSampler()
    sampler.start()
    try:
        model_started = time.perf_counter()
        model = models.ColBERT(
            model_name_or_path=str(args.model.resolve()), device=args.model_device
        )
        report["model_load_seconds"] = round(time.perf_counter() - model_started, 4)

        index_started = time.perf_counter()
        index = indexes.PLAID(
            index_folder=str(args.index_root.resolve()),
            index_name=index_name,
            override=override,
            use_fast=True,
            nbits=args.nbits,
            n_ivf_probe=args.n_ivf_probe,
            n_full_scores=args.n_full_scores,
            num_threads=args.num_threads,
            device="cpu",
            low_memory=True,
            show_progress=False,
            use_triton=False,
        )
        report["index_open_seconds"] = round(time.perf_counter() - index_started, 4)
        indexed_count = _existing_document_count(index) if args.resume else 0
        report["resumed_from_items"] = indexed_count

        for target in targets:
            if indexed_count < target:
                for start, stop in _batched_ranges(indexed_count, target, args.batch_size):
                    identifiers, texts = _document_batch(
                        start,
                        stop,
                        documents,
                        synthetic_only=args.synthetic_only,
                        synthetic_offset=args.synthetic_offset,
                    )
                    encode_started = time.perf_counter()
                    embeddings = model.encode(
                        texts,
                        batch_size=args.encode_batch_size,
                        is_query=False,
                        show_progress_bar=False,
                    )
                    encode_seconds = time.perf_counter() - encode_started
                    token_vectors = sum(int(embedding.shape[0]) for embedding in embeddings)
                    raw_embedding_bytes = sum(int(embedding.nbytes) for embedding in embeddings)

                    add_started = time.perf_counter()
                    _add_documents(
                        index=index,
                        identifiers=identifiers,
                        embeddings=embeddings,
                        update_kmeans_niters=args.update_kmeans_niters,
                        centroid_expansion_buffer=args.centroid_expansion_buffer,
                    )
                    add_seconds = time.perf_counter() - add_started
                    indexed_count = stop
                    batch_result = {
                        "start": start,
                        "stop": stop,
                        "items": stop - start,
                        "token_vectors": token_vectors,
                        "raw_embedding_bytes": raw_embedding_bytes,
                        "encode_seconds": round(encode_seconds, 4),
                        "index_seconds": round(add_seconds, 4),
                        "update_kmeans_niters": args.update_kmeans_niters,
                        "centroid_expansion_buffer": args.centroid_expansion_buffer,
                        "index_bytes_after_batch": _directory_bytes(index_path),
                    }
                    report["batches"].append(batch_result)
                    report["indexed_items"] = indexed_count
                    report["resource_peaks"] = _merge_resource_peaks(report, sampler)
                    _write_json(args.output, report)
                    print(
                        json.dumps(
                            {
                                "event": "batch_complete",
                                "items": indexed_count,
                                "target": target,
                                "encode_seconds": round(encode_seconds, 2),
                                "index_seconds": round(add_seconds, 2),
                                "index_gib": round(_directory_bytes(index_path) / 2**30, 4),
                                "peak_rss_gib": round(sampler.peak_process_rss_bytes / 2**30, 3),
                            }
                        ),
                        flush=True,
                    )
                    del embeddings, texts, identifiers

            checkpoint_key = str(target)
            if checkpoint_key not in report["checkpoints"]:
                evaluation = (
                    None
                    if args.synthetic_only
                    else _evaluate(
                        model=model,
                        index=index,
                        questions=questions,
                        documents=documents,
                        top_k=args.top_k,
                        encode_batch_size=args.encode_batch_size,
                    )
                )
                total_token_vectors = sum(
                    batch["token_vectors"]
                    for batch in report["batches"]
                    if batch["stop"] <= target
                )
                total_raw_bytes = sum(
                    batch["raw_embedding_bytes"]
                    for batch in report["batches"]
                    if batch["stop"] <= target
                )
                compressed_bytes = _directory_bytes(index_path)
                report["checkpoints"][checkpoint_key] = {
                    "items": target,
                    "token_vectors": total_token_vectors,
                    "mean_token_vectors_per_item": round(total_token_vectors / target, 4),
                    "raw_embedding_bytes": total_raw_bytes,
                    "compressed_index_bytes": compressed_bytes,
                    "compressed_to_raw_ratio": round(
                        compressed_bytes / max(total_raw_bytes, 1), 6
                    ),
                    "compressed_bytes_per_item": round(compressed_bytes / target, 4),
                    "dense_384_float32_bytes": target * 384 * 4,
                    "compressed_to_dense_384_ratio": round(
                        compressed_bytes / max(target * 384 * 4, 1), 6
                    ),
                    "evaluation": evaluation,
                }
                _write_json(args.output, report)
                print(
                    json.dumps(
                        {
                            "event": "checkpoint_complete",
                            "items": target,
                            "index_gib": round(compressed_bytes / 2**30, 4),
                            "recall_at_10": evaluation["macro_recall_at_k"]
                            if evaluation
                            else None,
                            "p95_search_seconds": evaluation[
                                "p95_search_latency_seconds"
                            ]
                            if evaluation
                            else None,
                        }
                    ),
                    flush=True,
                )
    finally:
        sampler.stop()
        report["resource_peaks"] = _merge_resource_peaks(report, sampler)
        report["runs"][-1]["completed_at_unix"] = time.time()
        report["completed_at_unix"] = time.time()
        _write_json(args.output, report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
