from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import shutil
import statistics
import sys
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate Vault retrieval on the official LOCOMO corpus."
    )
    parser.add_argument("--locomo", type=Path, required=True)
    parser.add_argument("--questions", type=int, default=300)
    parser.add_argument(
        "--selection", choices=("seeded", "first", "all"), default="seeded"
    )
    parser.add_argument(
        "--category-scope",
        choices=("standard", "adversarial", "all"),
        default="standard",
        help=(
            "standard evaluates categories 1-4; adversarial evaluates category 5 "
            "as a separate abstention task"
        ),
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument(
        "--model",
        required=True,
        help="Local SentenceTransformer model path or a model already present in the cache",
    )
    parser.add_argument(
        "--model-cache",
        type=Path,
        default=Path.home() / ".cache" / "huggingface" / "hub",
    )
    parser.add_argument(
        "--work-dir", type=Path, default=Path(".tmp/vault-odin-memory-benchmark/locomo")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".tmp/vault-odin-memory-benchmark/locomo-results.json"),
    )
    parser.add_argument("--keep-database", action="store_true")
    return parser.parse_args()


def _configure_environment(args: argparse.Namespace) -> None:
    data_dir = args.work_dir.resolve()
    if data_dir.exists() and not args.keep_database:
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["CML_DATA_DIR"] = str(data_dir)
    os.environ["CML_DATABASE_PATH"] = str(data_dir / "vault-memory.sqlite3")
    os.environ["CML_EMBEDDING_PROVIDER"] = "sentence-transformers"
    os.environ["CML_EMBEDDING_MODEL"] = args.model
    os.environ["CML_EMBEDDING_CACHE_DIR"] = str(args.model_cache.resolve())


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def _exclusive_index_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    if path.stat().st_size == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError(f"Another LOCOMO indexing process holds {path}") from exc
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError(f"Another LOCOMO indexing process holds {path}") from exc
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _flatten_locomo(
    data: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    documents: list[dict[str, str]] = []
    questions: list[dict[str, Any]] = []
    for conversation in data:
        sample_id = str(conversation["sample_id"])
        conversation_data = conversation["conversation"]
        for key, turns in conversation_data.items():
            if not key.startswith("session_") or key.endswith("_date_time") or not isinstance(turns, list):
                continue
            date = str(conversation_data.get(f"{key}_date_time") or "")
            for turn in turns:
                dia_id = str(turn["dia_id"])
                speaker = str(turn.get("speaker") or "")
                content = str(turn.get("text") or "")
                image_caption = str(turn.get("blip_caption") or "").strip()
                if image_caption:
                    content = f"{content}\nShared image: {image_caption}"
                documents.append(
                    {
                        "source_id": f"locomo:{sample_id}:{dia_id}",
                        "sample_id": sample_id,
                        "cluster_id": f"locomo:{sample_id}",
                        "evidence_id": dia_id,
                        "title": f"{sample_id} {dia_id}",
                        "text": f"Date: {date}\n{speaker}: {content}",
                    }
                )
        for index, qa in enumerate(conversation["qa"]):
            questions.append(
                {
                    "question_id": f"{sample_id}:q{index:03d}",
                    "sample_id": sample_id,
                    "question": str(qa["question"]),
                    "answer": (
                        str(qa["answer"]) if qa.get("answer") is not None else None
                    ),
                    "adversarial_answer": (
                        str(qa["adversarial_answer"])
                        if qa.get("adversarial_answer") is not None
                        else None
                    ),
                    "category": int(qa.get("category") or 0),
                    "evidence": [
                        evidence_id
                        for value in qa.get("evidence") or []
                        for evidence_id in re.split(r"\s*;\s*", str(value))
                        if evidence_id
                    ],
                }
            )
    return documents, questions


def _select_questions(
    questions: list[dict[str, Any]],
    count: int,
    *,
    category_scope: str,
    selection: str,
    seed: int,
) -> list[dict[str, Any]]:
    if category_scope == "standard":
        eligible = [question for question in questions if question["category"] in {1, 2, 3, 4}]
    elif category_scope == "adversarial":
        eligible = [question for question in questions if question["category"] == 5]
    elif category_scope == "all":
        eligible = questions
    else:
        raise ValueError(f"Unsupported category scope: {category_scope}")
    if selection == "all":
        return eligible
    selected_count = min(len(eligible), max(1, count))
    if selection == "first":
        return eligible[:selected_count]
    return random.Random(seed).sample(eligible, selected_count)


def _index_documents(
    documents: list[dict[str, str]], *, model_name: str, model_cache: Path
) -> dict[str, Any]:
    from sentence_transformers import SentenceTransformer

    from backend.app.core.database import connect, init_db, utc_now
    from backend.app.core.derived_state import chunk_tuple_values, query_epoch_snapshot_conn
    from backend.app.core.embeddings import content_hash, encode_embedding
    from backend.app.core.vector_maintenance import activate_embedding_index

    init_db()
    now = utc_now()
    vault_id = "vault-locomo-benchmark"
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (vault_id, "LOCOMO Benchmark", os.environ["CML_DATA_DIR"], now, now),
        )
        for sample_id in sorted({document["sample_id"] for document in documents}):
            conn.execute(
                """
                INSERT INTO clusters (id, vault_id, name, description, created_at, updated_at)
                VALUES (?, ?, ?, '', ?, ?)
                """,
                (f"locomo:{sample_id}", vault_id, sample_id, now, now),
            )

    import numpy as np

    cache_identity = {
        "model": model_name,
        "content_hashes": [content_hash(document["text"]) for document in documents],
    }
    cache_signature = hashlib.sha256(
        json.dumps(cache_identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    cache_root = Path(os.environ["CML_DATA_DIR"]).parent / ".cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    vector_cache = cache_root / f"locomo-vectors-{cache_signature[:16]}.npy"
    if vector_cache.exists():
        vectors = np.load(vector_cache, mmap_mode="r")
        embedding_seconds = 0.0
        embedding_cache_hit = True
    else:
        model = SentenceTransformer(
            model_name, cache_folder=str(model_cache.resolve()), local_files_only=True
        )
        started = time.perf_counter()
        vectors = model.encode(
            [document["text"] for document in documents],
            batch_size=64,
            normalize_embeddings=True,
            show_progress_bar=True,
        )
        embedding_seconds = time.perf_counter() - started
        np.save(vector_cache, vectors)
        embedding_cache_hit = False
    activate_embedding_index(model_name)

    with connect() as conn:
        snapshot = query_epoch_snapshot_conn(
            conn, vault_id, embedding_model_id=model_name, index_version="v1"
        )
        tuple_values = chunk_tuple_values(snapshot)
        for document, vector in zip(documents, vectors, strict=True):
            source_id = document["source_id"]
            conn.execute(
                """
                INSERT INTO sources (
                    id, vault_id, cluster_id, title, source_type, state, raw_text, extracted_text,
                    summary, tags, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'external_transcript', 'indexed', ?, ?, '', ?, ?, ?)
                """,
                (
                    source_id,
                    vault_id,
                    document["cluster_id"],
                    document["title"],
                    document["text"],
                    document["text"],
                    json.dumps(
                        ["locomo", document["sample_id"], document["evidence_id"]],
                        separators=(",", ":"),
                    ),
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO source_chunks (
                    id, source_id, vault_id, cluster_id, chunk_index, text, embedding,
                    embedding_model_id, content_profile, chunk_strategy, chunk_meta_json,
                    content_hash, index_version, normalization_version, extraction_version,
                    derived_state_epoch, indexed_at, created_at
                ) VALUES (?, ?, ?, ?, 0, ?, ?, ?, 'conversation', 'benchmark-turn', '{}',
                          ?, 'v1', ?, ?, ?, ?, ?)
                """,
                (
                    f"chunk:{source_id}",
                    source_id,
                    vault_id,
                    document["cluster_id"],
                    document["text"],
                    encode_embedding([float(value) for value in vector.tolist()]),
                    model_name,
                    content_hash(document["text"]),
                    tuple_values["normalization_version"],
                    tuple_values["extraction_version"],
                    tuple_values["derived_state_epoch"],
                    now,
                    now,
                ),
            )
    return {
        "vault_id": vault_id,
        "document_count": len(documents),
        "embedding_seconds": round(embedding_seconds, 3),
        "embedding_cache_hit": embedding_cache_hit,
        "embedding_cache_signature": cache_signature,
    }


def _evaluate(
    questions: list[dict[str, Any]], *, vault_id: str, top_k: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from backend.app.core.retrieval_scoring import scoring_ledger

    results: list[dict[str, Any]] = []
    latencies: list[float] = []
    for position, item in enumerate(questions, start=1):
        started = time.perf_counter()
        ledger = scoring_ledger(
            vault_id,
            item["question"],
            cluster_id=f"locomo:{item['sample_id']}",
            limit=top_k,
        )
        latency = time.perf_counter() - started
        latencies.append(latency)
        retrieved = []
        for hit in ledger["results"]:
            parts = str(hit["source_id"]).split(":", 2)
            retrieved.append(
                {
                    "source_id": hit["source_id"],
                    "sample_id": parts[1] if len(parts) == 3 else "",
                    "evidence_id": parts[2] if len(parts) == 3 else "",
                    "score": hit["combined_score"],
                    "semantic_score": hit["semantic_score"],
                    "bm25_score": hit["bm25_score"],
                }
            )
        gold = set(item["evidence"])
        matching_conversation = {
            hit["evidence_id"] for hit in retrieved if hit["sample_id"] == item["sample_id"]
        }
        found = gold & matching_conversation
        recall = len(found) / len(gold) if gold else None
        results.append(
            {
                **item,
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
    summary = {
        "question_count": len(results),
        "evidence_question_count": len(evidence_rows),
        "questions_without_evidence": len(results) - len(evidence_rows),
        "macro_recall_at_k": round(
            statistics.fmean(float(row["recall_at_k"]) for row in evidence_rows), 6
        )
        if evidence_rows
        else 0.0,
        "any_evidence_hit_rate_at_k": round(
            statistics.fmean(1.0 if row["any_evidence_at_k"] else 0.0 for row in evidence_rows),
            6,
        )
        if evidence_rows
        else 0.0,
        "category_counts": dict(sorted(Counter(row["category"] for row in results).items())),
        "macro_recall_by_category": {
            str(category): round(statistics.fmean(values), 6)
            for category, values in sorted(by_category.items())
        },
        "mean_query_latency_seconds": round(statistics.fmean(latencies), 4),
        "p95_query_latency_seconds": round(
            sorted(latencies)[max(0, math.ceil(len(latencies) * 0.95) - 1)], 4
        ),
    }
    return results, summary


def _run(args: argparse.Namespace) -> int:
    _configure_environment(args)
    data = json.loads(args.locomo.read_text(encoding="utf-8"))
    documents, all_questions = _flatten_locomo(data)
    selected_questions = _select_questions(
        all_questions,
        args.questions,
        category_scope=args.category_scope,
        selection=args.selection,
        seed=args.seed,
    )
    index = _index_documents(
        documents, model_name=args.model, model_cache=args.model_cache
    )
    results, summary = _evaluate(
        selected_questions, vault_id=index["vault_id"], top_k=max(1, args.top_k)
    )
    report = {
        "schema_version": 2,
        "system": "Vault+Odin (Vault context retrieval; Odin code graph not applicable)",
        "dataset": "LOCOMO official locomo10.json",
        "protocol": {
            "selection": (
                f"all {len(selected_questions)} eligible questions in official file order"
                if args.selection == "all"
                else (
                    f"first {len(selected_questions)} eligible questions in official file order"
                    if args.selection == "first"
                    else f"random sample of {len(selected_questions)} eligible questions using Python seed {args.seed}"
                )
            ),
            "selection_mode": args.selection,
            "category_scope": args.category_scope,
            "category_policy": (
                "categories 1-4 only; category 5 is an adversarial abstention task"
                if args.category_scope == "standard"
                else "explicit non-headline category scope"
            ),
            "seed": args.seed if args.selection == "seeded" else None,
            "dataset_sha256": _file_sha256(args.locomo),
            "question_ids": [question["question_id"] for question in selected_questions],
            "selection_manifest_available_from_graphify": False,
            "top_k": args.top_k,
            "granularity": "dialog turn with released image caption when present",
            "retrieval_scope": "the question's conversation, matching the official RAG protocol",
            "retriever": "Vault hybrid scorer (70% semantic, 30% BM25)",
            "embedding_model": args.model,
            "qa_reader": None,
            "qa_judge": None,
        },
        "index": index,
        "summary": summary,
        "graphify_published_reference": {
            "sample_size": 300,
            "recall_at_10": 0.497,
            "qa_accuracy": 0.453,
            "embedding_model": "BAAI/bge-m3",
            "reader_and_judge": "Kimi K2.6",
            "comparison_status": "directional_only_until_sample_ids_and_matching_models_are_available",
        },
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({**summary, "output": str(args.output)}, indent=2))
    return 0


def main() -> int:
    args = parse_args()
    lock_path = args.work_dir.resolve().parent / "locomo-index.lock"
    with _exclusive_index_lock(lock_path):
        return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
