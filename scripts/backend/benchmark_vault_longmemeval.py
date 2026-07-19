from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
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


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def _exclusive_index_lock(path: Path):
    """Use an OS-backed lock so a crashed process cannot leave a stale lock active."""

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
                raise RuntimeError(
                    f"Another LongMemEval indexing process holds {path}"
                ) from exc
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError(
                    f"Another LongMemEval indexing process holds {path}"
                ) from exc
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate Vault session retrieval on LongMemEval-S."
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--questions", type=int, default=50)
    parser.add_argument(
        "--selection", choices=("seeded", "first", "all"), default="seeded"
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--model", required=True)
    parser.add_argument("--embedding-batch-size", type=int, default=64)
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path(".tmp/vault-odin-memory-benchmark/longmemeval"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".tmp/vault-odin-memory-benchmark/longmemeval-results.json"),
    )
    return parser.parse_args()


def _configure(args: argparse.Namespace) -> None:
    data_dir = args.work_dir.resolve()
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["CML_DATA_DIR"] = str(data_dir)
    os.environ["CML_DATABASE_PATH"] = str(data_dir / "vault-memory.sqlite3")
    os.environ["CML_EMBEDDING_PROVIDER"] = "sentence-transformers"
    os.environ["CML_EMBEDDING_MODEL"] = args.model
    os.environ["CML_EMBEDDING_CACHE_DIR"] = args.model


def _session_text(date: Any, turns: list[dict[str, Any]]) -> str:
    lines = [f"Date: {date}"]
    for turn in turns:
        lines.append(f"{turn.get('role', '')}: {turn.get('content', '')}")
    return "\n".join(lines)


def _prepare(
    data: list[dict[str, Any]], count: int, *, selection: str = "seeded", seed: int = 42
) -> tuple[list[dict], list[dict]]:
    if selection == "all":
        questions = data
    else:
        selected_count = min(len(data), max(1, count))
    if selection == "first":
        questions = data[:selected_count]
    elif selection == "seeded":
        questions = random.Random(seed).sample(data, selected_count)
    documents: list[dict] = []
    normalized_questions: list[dict] = []
    for item in questions:
        question_id = str(item["question_id"])
        cluster_id = f"lme:{question_id}"
        session_ids = item["haystack_session_ids"]
        dates = item["haystack_dates"]
        sessions = item["haystack_sessions"]
        for session_position, (session_id, date, turns) in enumerate(
            zip(session_ids, dates, sessions, strict=True)
        ):
            documents.append(
                {
                    "source_id": f"lme:{question_id}:{session_position:03d}:{session_id}",
                    "cluster_id": cluster_id,
                    "question_id": question_id,
                    "session_id": str(session_id),
                    "text": _session_text(date, turns),
                }
            )
        normalized_questions.append(
            {
                "question_id": question_id,
                "cluster_id": cluster_id,
                "question_type": str(item.get("question_type") or ""),
                "question": str(item["question"]),
                "answer": str(item.get("answer") or ""),
                "answer_session_ids": [str(value) for value in item.get("answer_session_ids") or []],
                "abstention": question_id.endswith("_abs"),
            }
        )
    return documents, normalized_questions


def _index(
    documents: list[dict],
    questions: list[dict],
    model_path: str,
    *,
    embedding_batch_size: int,
) -> dict:
    from sentence_transformers import SentenceTransformer

    from backend.app.core.database import connect, init_db, utc_now
    from backend.app.core.derived_state import chunk_tuple_values, query_epoch_snapshot_conn
    from backend.app.core.embeddings import chunk_text_for_source, content_hash, encode_embedding
    from backend.app.core.vector_maintenance import activate_embedding_index

    init_db()
    vault_id = "vault-longmemeval-benchmark"
    now = utc_now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (vault_id, "LongMemEval Benchmark", os.environ["CML_DATA_DIR"], now, now),
        )
        for question in questions:
            conn.execute(
                """
                INSERT INTO clusters (id, vault_id, name, description, created_at, updated_at)
                VALUES (?, ?, ?, '', ?, ?)
                """,
                (question["cluster_id"], vault_id, question["question_id"], now, now),
            )

    model = SentenceTransformer(model_path, local_files_only=True)
    chunk_records: list[dict] = []
    for document in documents:
        chunks = chunk_text_for_source(
            {"source_type": "external_transcript", "title": document["session_id"]},
            document["text"],
            tokenizer=model.tokenizer,
            max_seq_length=int(model.max_seq_length),
        )
        for chunk_index, chunk in enumerate(chunks):
            chunk_records.append(
                {
                    **document,
                    "chunk_index": chunk_index,
                    "chunk_text": chunk["text"],
                    "content_profile": chunk["content_profile"],
                    "chunk_strategy": chunk["chunk_strategy"],
                    "chunk_meta_json": chunk["chunk_meta_json"],
                }
            )

    import numpy as np

    cache_root = Path(os.environ["CML_DATA_DIR"]).parent / ".cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    expected_cache_identity = {
        "model": model_path,
        "chunk_count": len(chunk_records),
        "content_hashes": [content_hash(record["chunk_text"]) for record in chunk_records],
    }
    cache_signature = hashlib.sha256(
        json.dumps(expected_cache_identity, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    vector_cache = cache_root / f"longmemeval-vectors-{cache_signature[:16]}.npy"
    cache_manifest = cache_root / f"longmemeval-vectors-{cache_signature[:16]}.json"
    if cache_manifest.exists():
        saved_manifest = json.loads(cache_manifest.read_text(encoding="utf-8"))
    else:
        saved_manifest = {}

    def save_cache_manifest(completed_count: int, dimension: int) -> None:
        payload = {
            "schema_version": 2,
            "signature": cache_signature,
            "model": model_path,
            "chunk_count": len(chunk_records),
            "dimension": dimension,
            "completed_count": completed_count,
        }
        temporary = cache_manifest.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(cache_manifest)

    cache_complete = (
        vector_cache.exists()
        and saved_manifest.get("signature") == cache_signature
        and int(saved_manifest.get("completed_count") or 0) == len(chunk_records)
    )
    if cache_complete:
        vectors = np.load(vector_cache, mmap_mode="r")
        embedding_seconds = 0.0
        embedding_cache_hit = True
    else:
        dimension = int(model.get_sentence_embedding_dimension())
        resume_at = 0
        if (
            vector_cache.exists()
            and saved_manifest.get("signature") == cache_signature
            and int(saved_manifest.get("dimension") or 0) == dimension
        ):
            vectors = np.lib.format.open_memmap(vector_cache, mode="r+")
            resume_at = min(
                len(chunk_records), int(saved_manifest.get("completed_count") or 0)
            )
        else:
            vectors = np.lib.format.open_memmap(
                vector_cache,
                mode="w+",
                dtype="float32",
                shape=(len(chunk_records), dimension),
            )
            save_cache_manifest(0, dimension)
        started = time.perf_counter()
        checkpoint_batch_size = max(512, embedding_batch_size * 16)
        for start in range(resume_at, len(chunk_records), checkpoint_batch_size):
            end = min(len(chunk_records), start + checkpoint_batch_size)
            vectors[start:end] = model.encode(
                [record["chunk_text"] for record in chunk_records[start:end]],
                batch_size=embedding_batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            vectors.flush()
            save_cache_manifest(end, dimension)
            print(f"embedded {end}/{len(chunk_records)} chunks", flush=True)
        embedding_seconds = time.perf_counter() - started
        embedding_cache_hit = False
    activate_embedding_index(model_path)

    with connect() as conn:
        snapshot = query_epoch_snapshot_conn(
            conn, vault_id, embedding_model_id=model_path, index_version="v1"
        )
        tuple_values = chunk_tuple_values(snapshot)
        for document in documents:
            source_id = document["source_id"]
            conn.execute(
                """
                INSERT INTO sources (
                    id, vault_id, cluster_id, title, source_type, state, raw_text,
                    extracted_text, summary, tags, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'external_transcript', 'indexed', ?, ?, '', ?, ?, ?)
                """,
                (
                    source_id,
                    vault_id,
                    document["cluster_id"],
                    document["session_id"],
                    document["text"],
                    document["text"],
                    json.dumps(["longmemeval", document["session_id"]], separators=(",", ":")),
                    now,
                    now,
                ),
            )
        for record_position, (record, vector) in enumerate(
            zip(chunk_records, vectors, strict=True), start=1
        ):
            source_id = record["source_id"]
            conn.execute(
                """
                INSERT INTO source_chunks (
                    id, source_id, vault_id, cluster_id, chunk_index, text, embedding,
                    embedding_model_id, content_profile, chunk_strategy, chunk_meta_json,
                    content_hash, index_version, normalization_version, extraction_version,
                    derived_state_epoch, indexed_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, 'v1', ?, ?, ?, ?, ?)
                """,
                (
                    f"chunk:{source_id}:{record['chunk_index']}",
                    source_id,
                    vault_id,
                    record["cluster_id"],
                    record["chunk_index"],
                    record["chunk_text"],
                    encode_embedding([float(value) for value in vector.tolist()]),
                    model_path,
                    record["content_profile"],
                    record["chunk_strategy"],
                    record["chunk_meta_json"],
                    content_hash(record["chunk_text"]),
                    tuple_values["normalization_version"],
                    tuple_values["extraction_version"],
                    tuple_values["derived_state_epoch"],
                    now,
                    now,
                ),
            )
            if record_position % 5_000 == 0:
                conn.commit()
                print(
                    f"persisted {record_position}/{len(chunk_records)} chunks", flush=True
                )
    return {
        "vault_id": vault_id,
        "session_count": len(documents),
        "chunk_count": len(chunk_records),
        "embedding_seconds": round(embedding_seconds, 3),
        "embedding_cache_hit": embedding_cache_hit,
        "embedding_cache_signature": cache_signature,
        "embedding_cache_path": str(vector_cache),
        "embedding_batch_size": embedding_batch_size,
    }


def _evaluate(questions: list[dict], vault_id: str, top_k: int) -> tuple[list[dict], dict]:
    from backend.app.core.retrieval_scoring import scoring_ledger

    rows: list[dict] = []
    latencies: list[float] = []
    for position, question in enumerate(questions, start=1):
        started = time.perf_counter()
        ledger = scoring_ledger(
            vault_id, question["question"], cluster_id=question["cluster_id"], limit=100
        )
        latency = time.perf_counter() - started
        latencies.append(latency)
        retrieved_ids = []
        for hit in ledger["results"]:
            session_id = str(hit["source_title"])
            if session_id not in retrieved_ids:
                retrieved_ids.append(session_id)
            if len(retrieved_ids) >= top_k:
                break
        gold = set(question["answer_session_ids"])
        found = gold & set(retrieved_ids)
        recall = len(found) / len(gold) if gold and not question["abstention"] else None
        rows.append(
            {
                **question,
                "rank": position,
                "retrieved_session_ids": retrieved_ids,
                "found_session_ids": sorted(found),
                "recall_at_k": recall,
                "any_evidence_at_k": bool(found) if recall is not None else None,
                "latency_seconds": round(latency, 4),
            }
        )
        if position % 10 == 0:
            print(f"evaluated {position}/{len(questions)}", flush=True)

    scorable = [row for row in rows if row["recall_at_k"] is not None]
    by_type: dict[str, list[float]] = defaultdict(list)
    for row in scorable:
        by_type[row["question_type"]].append(float(row["recall_at_k"]))
    summary = {
        "question_count": len(rows),
        "retrieval_question_count": len(scorable),
        "abstention_or_missing_gold_count": len(rows) - len(scorable),
        "macro_recall_at_k": round(statistics.fmean(row["recall_at_k"] for row in scorable), 6),
        "any_evidence_hit_rate_at_k": round(
            statistics.fmean(1.0 if row["any_evidence_at_k"] else 0.0 for row in scorable), 6
        ),
        "question_type_counts": dict(sorted(Counter(row["question_type"] for row in rows).items())),
        "macro_recall_by_type": {
            key: round(statistics.fmean(values), 6) for key, values in sorted(by_type.items())
        },
        "mean_query_latency_seconds": round(statistics.fmean(latencies), 4),
        "p95_query_latency_seconds": round(
            sorted(latencies)[max(0, math.ceil(len(latencies) * 0.95) - 1)], 4
        ),
    }
    return rows, summary


def _run(args: argparse.Namespace) -> int:
    _configure(args)
    data = json.loads(args.dataset.read_text(encoding="utf-8"))
    documents, questions = _prepare(
        data, args.questions, selection=args.selection, seed=args.seed
    )
    index = _index(
        documents,
        questions,
        args.model,
        embedding_batch_size=max(1, args.embedding_batch_size),
    )
    results, summary = _evaluate(questions, index["vault_id"], args.top_k)
    report = {
        "schema_version": 2,
        "system": "Vault+Odin (Vault context retrieval; Odin code graph not applicable)",
        "dataset": "LongMemEval-S cleaned",
        "protocol": {
            "selection": (
                f"all {len(questions)} records in official file order"
                if args.selection == "all"
                else (
                    f"first {len(questions)} records in official file order"
                    if args.selection == "first"
                    else f"random sample of {len(questions)} records using Python seed {args.seed}"
                )
            ),
            "selection_mode": args.selection,
            "seed": args.seed if args.selection == "seeded" else None,
            "dataset_sha256": _file_sha256(args.dataset),
            "question_ids": [question["question_id"] for question in questions],
            "selection_manifest_available_from_graphify": False,
            "top_k": args.top_k,
            "granularity": "session",
            "retriever": "Vault hybrid scorer (70% semantic, 30% BM25)",
            "embedding_model": args.model,
            "qa_reader": None,
            "qa_judge": None,
        },
        "index": index,
        "summary": summary,
        "graphify_published_reference": {
            "sample_size": 50,
            "recall_at_10": 0.844,
            "qa_accuracy": 0.76,
            "embedding_model": "BAAI/bge-m3",
            "reader_and_judge": "Kimi K2.6",
            "comparison_status": "directional_only_until_sample_ids_and_matching_models_are_available",
        },
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({**summary, "index": index, "output": str(args.output)}, indent=2))
    return 0


def main() -> int:
    args = parse_args()
    lock_path = args.work_dir.resolve().parent / "longmemeval-index.lock"
    with _exclusive_index_lock(lock_path):
        return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
