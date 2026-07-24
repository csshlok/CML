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

from scripts.backend.atomic_io import atomic_write_text

DATASET_REVISION = "63f6b052ff83508b08e242db42263ee708815c26"
VAULT_ID = "vault-open-rag-bench"
SOURCE_PREFIX = "orb"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Vault's production hybrid retrieval against Open RAG Bench."
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path(".tmp/open-rag-bench/source/pdf/arxiv"),
    )
    parser.add_argument("--dataset-revision", default=DATASET_REVISION)
    parser.add_argument("--questions", type=int, default=25)
    parser.add_argument(
        "--selection", choices=("seeded", "first", "all"), default="seeded"
    )
    parser.add_argument("--seed", type=int, default=20260724)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--embedding-batch-size", type=int, default=64)
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path(".tmp/open-rag-bench/vault-index"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".tmp/open-rag-bench/results.json"),
    )
    parser.add_argument(
        "--rebuild-index",
        action="store_true",
        help="Discard and rebuild an existing benchmark-only index.",
    )
    return parser.parse_args()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    content = "".join(
        json.dumps(row, ensure_ascii=False) + "\n" for row in rows
    )
    atomic_write_text(path, content)


def _write_progress(
    output: Path,
    *,
    total: int,
    completed: int,
    detail: str,
) -> None:
    path = output.with_name(output.stem + ".progress.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "stage": "retrieval",
        "total": total,
        "completed": completed,
        "remaining": max(0, total - completed),
        "percent": round((completed / total) * 100, 2) if total else 100.0,
        "detail": detail,
        "updated_at_epoch": time.time(),
    }
    try:
        atomic_write_text(path, json.dumps(payload, indent=2))
    except OSError as exc:
        print(
            f"warning: could not publish retrieval progress at {path}: {exc}",
            file=sys.stderr,
            flush=True,
        )


def _corpus_manifest(corpus_dir: Path) -> dict[str, Any]:
    files = sorted(corpus_dir.glob("*.json"), key=lambda path: path.name)
    digest = hashlib.sha256()
    total_bytes = 0
    for path in files:
        file_hash = _file_sha256(path)
        size = path.stat().st_size
        total_bytes += size
        digest.update(f"{path.name}\0{size}\0{file_hash}\n".encode("utf-8"))
    return {
        "file_count": len(files),
        "total_bytes": total_bytes,
        "sha256": digest.hexdigest(),
    }


@contextmanager
def _exclusive_lock(path: Path):
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
                raise RuntimeError(f"Another Open RAG Bench run holds {path}") from exc
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError(f"Another Open RAG Bench run holds {path}") from exc
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


def _require_gpu() -> str:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError(
            "Open RAG Bench is GPU-only by policy, but torch.cuda.is_available() is false."
        )
    return str(torch.cuda.get_device_name(torch.cuda.current_device()))


def _source_id(doc_id: str, section_id: int) -> str:
    return f"{SOURCE_PREFIX}:{doc_id}:section:{int(section_id)}"


def _parse_source_id(source_id: str) -> tuple[str, int]:
    prefix, doc_id, marker, section_id = source_id.split(":", 3)
    if prefix != SOURCE_PREFIX or marker != "section":
        raise ValueError(f"invalid Open RAG Bench source id: {source_id}")
    return doc_id, int(section_id)


def _section_text(section: dict[str, Any]) -> str:
    """Build answer-blind text. Images are deliberately never serialized."""

    parts = [str(section.get("text") or "").strip()]
    tables = section.get("tables") or {}
    if not isinstance(tables, dict):
        raise ValueError("section tables must be a mapping")
    for table_id, table_text in sorted(tables.items()):
        rendered = str(table_text or "").strip()
        if rendered:
            parts.append(f"#### Table {table_id}\n\n{rendered}")
    return "\n\n".join(part for part in parts if part)


def _load_corpus(corpus_dir: Path) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for path in sorted(corpus_dir.glob("*.json"), key=lambda item: item.name):
        paper = json.loads(path.read_text(encoding="utf-8"))
        doc_id = str(paper["id"])
        if path.stem != doc_id:
            raise ValueError(f"corpus id mismatch in {path}")
        for section in paper["sections"]:
            section_id = int(section["section_id"])
            text = _section_text(section)
            if not text:
                continue
            documents.append(
                {
                    "source_id": _source_id(doc_id, section_id),
                    "doc_id": doc_id,
                    "section_id": section_id,
                    "title": f"{doc_id} §{section_id}",
                    "text": text,
                    "has_tables": bool(section.get("tables")),
                    "has_images": bool(section.get("images")),
                }
            )
    return documents


def _select_questions(
    queries: dict[str, dict[str, Any]],
    *,
    selection: str,
    count: int,
    seed: int,
) -> list[dict[str, Any]]:
    ordered_ids = sorted(queries)
    if selection == "all":
        selected_ids = ordered_ids
    elif selection == "first":
        selected_ids = ordered_ids[: min(len(ordered_ids), max(1, count))]
    else:
        selected_ids = random.Random(seed).sample(
            ordered_ids, min(len(ordered_ids), max(1, count))
        )
    return [
        {
            "question_id": question_id,
            "question": str(queries[question_id]["query"]),
            "question_type": str(queries[question_id]["type"]),
            "source_modality": str(queries[question_id]["source"]),
        }
        for question_id in selected_ids
    ]


def _dataset_identity(dataset_root: Path, revision: str) -> dict[str, Any]:
    return {
        "revision": revision,
        "queries_sha256": _file_sha256(dataset_root / "queries.json"),
        "qrels_sha256": _file_sha256(dataset_root / "qrels.json"),
        "corpus": _corpus_manifest(dataset_root / "corpus"),
    }


def _configure(work_dir: Path, model_path: Path) -> None:
    resolved_work_dir = work_dir.resolve()
    resolved_model = model_path.resolve()
    os.environ["CML_DATA_DIR"] = str(resolved_work_dir)
    os.environ["CML_DATABASE_PATH"] = str(resolved_work_dir / "vault.sqlite3")
    os.environ["CML_EMBEDDING_PROVIDER"] = "sentence-transformers"
    os.environ["CML_EMBEDDING_MODEL"] = str(resolved_model)
    os.environ["CML_EMBEDDING_CACHE_DIR"] = str(resolved_model)

    from backend.app.core.config import get_settings
    get_settings.cache_clear()


def _index_signature(
    dataset_identity: dict[str, Any], model_path: Path
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "dataset": dataset_identity,
        "embedding_model": str(model_path.resolve()),
        "adapter": {
            "granularity": "dataset_section_as_vault_document_source",
            "content": "section_text_plus_markdown_tables",
            "images": "excluded",
            "source_type": "document",
            "chunker": "production_chunk_text_for_source",
        },
    }


def _build_or_reuse_index(
    *,
    documents: list[dict[str, Any]],
    work_dir: Path,
    model_path: Path,
    embedding_batch_size: int,
    expected_signature: dict[str, Any],
    rebuild: bool,
) -> dict[str, Any]:
    manifest_path = work_dir / "index-manifest.json"
    if rebuild and work_dir.exists():
        resolved = work_dir.resolve()
        expected_parent = (REPO_ROOT / ".tmp").resolve()
        if expected_parent not in resolved.parents:
            raise RuntimeError(
                f"Refusing to remove benchmark work directory outside .tmp: {resolved}"
            )
        shutil.rmtree(resolved)
    work_dir.mkdir(parents=True, exist_ok=True)
    _configure(work_dir, model_path)

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("signature") != expected_signature:
            raise RuntimeError(
                "Existing Open RAG Bench index does not match this dataset/model/adapter. "
                "Pass --rebuild-index to replace it."
            )
        return {**manifest["index"], "reused": True}
    if (work_dir / "vault.sqlite3").exists():
        raise RuntimeError(
            "An incomplete benchmark index exists without a manifest. "
            "Pass --rebuild-index to recover."
        )

    from sentence_transformers import SentenceTransformer

    from backend.app.core.database import connect, init_db, utc_now
    from backend.app.core.derived_state import (
        chunk_tuple_values,
        query_epoch_snapshot_conn,
    )
    from backend.app.core.embeddings import (
        chunk_text_for_source,
        content_hash,
        encode_embedding,
    )
    from backend.app.core.vector_maintenance import activate_embedding_index

    started = time.perf_counter()
    init_db()
    now = utc_now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (VAULT_ID, "Open RAG Bench", str(work_dir.resolve()), now, now),
        )

    model = SentenceTransformer(
        str(model_path.resolve()), local_files_only=True, device="cuda"
    )
    if not str(model.device).startswith("cuda"):
        raise RuntimeError(f"embedding model unexpectedly loaded on {model.device}")

    chunk_records: list[dict[str, Any]] = []
    for position, document in enumerate(documents, start=1):
        chunks = chunk_text_for_source(
            {
                "source_type": "document",
                "title": document["title"],
                "original_path": f"{document['doc_id']}.pdf",
            },
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
        if position % 2_000 == 0:
            print(f"chunked {position}/{len(documents)} sections", flush=True)

    import numpy as np

    vector_path = work_dir / "vectors.npy"
    dimension_getter = (
        model.get_embedding_dimension
        if hasattr(model, "get_embedding_dimension")
        else model.get_sentence_embedding_dimension
    )
    dimension = int(dimension_getter())
    vectors = np.lib.format.open_memmap(
        vector_path,
        mode="w+",
        dtype="float32",
        shape=(len(chunk_records), dimension),
    )
    embedding_started = time.perf_counter()
    checkpoint_size = max(512, embedding_batch_size * 16)
    for start in range(0, len(chunk_records), checkpoint_size):
        end = min(len(chunk_records), start + checkpoint_size)
        vectors[start:end] = model.encode(
            [record["chunk_text"] for record in chunk_records[start:end]],
            batch_size=max(1, embedding_batch_size),
            normalize_embeddings=True,
            show_progress_bar=False,
            device="cuda",
        )
        vectors.flush()
        print(f"embedded {end}/{len(chunk_records)} chunks", flush=True)
    embedding_seconds = time.perf_counter() - embedding_started

    activate_embedding_index(str(model_path.resolve()))
    with connect() as conn:
        snapshot = query_epoch_snapshot_conn(
            conn,
            VAULT_ID,
            embedding_model_id=str(model_path.resolve()),
            index_version="v1",
        )
        tuple_values = chunk_tuple_values(snapshot)
        for document in documents:
            conn.execute(
                """
                INSERT INTO sources (
                    id, vault_id, title, source_type, state, original_path,
                    raw_text, extracted_text, summary, tags, created_at, updated_at
                ) VALUES (?, ?, ?, 'document', 'indexed', ?, ?, ?, '', ?, ?, ?)
                """,
                (
                    document["source_id"],
                    VAULT_ID,
                    document["title"],
                    f"{document['doc_id']}.pdf",
                    document["text"],
                    document["text"],
                    json.dumps(
                        [
                            "open-rag-bench",
                            document["doc_id"],
                            f"section:{document['section_id']}",
                        ],
                        separators=(",", ":"),
                    ),
                    now,
                    now,
                ),
            )
        for position, (record, vector) in enumerate(
            zip(chunk_records, vectors, strict=True), start=1
        ):
            conn.execute(
                """
                INSERT INTO source_chunks (
                    id, source_id, vault_id, cluster_id, chunk_index, text, embedding,
                    embedding_model_id, content_profile, chunk_strategy, chunk_meta_json,
                    content_hash, index_version, normalization_version, extraction_version,
                    derived_state_epoch, indexed_at, created_at
                ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, 'v1', ?, ?, ?, ?, ?)
                """,
                (
                    f"chunk:{record['source_id']}:{record['chunk_index']}",
                    record["source_id"],
                    VAULT_ID,
                    record["chunk_index"],
                    record["chunk_text"],
                    encode_embedding([float(value) for value in vector.tolist()]),
                    str(model_path.resolve()),
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
            if position % 5_000 == 0:
                conn.commit()
                print(f"persisted {position}/{len(chunk_records)} chunks", flush=True)

    index = {
        "vault_id": VAULT_ID,
        "document_count": len(documents),
        "paper_count": len({item["doc_id"] for item in documents}),
        "chunk_count": len(chunk_records),
        "embedding_dimension": dimension,
        "embedding_device": str(model.device),
        "gpu_name": _require_gpu(),
        "embedding_seconds": round(embedding_seconds, 3),
        "total_index_seconds": round(time.perf_counter() - started, 3),
        "reused": False,
    }
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"signature": expected_signature, "index": index}, indent=2),
        encoding="utf-8",
    )
    temporary.replace(manifest_path)
    return index


def _rank_metrics(rank: int | None, cutoff: int) -> dict[str, float]:
    hit = float(rank is not None and rank <= cutoff)
    return {
        f"hit_at_{cutoff}": hit,
        f"mrr_at_{cutoff}": (1.0 / rank) if hit and rank else 0.0,
        f"ndcg_at_{cutoff}": (1.0 / math.log2(rank + 1)) if hit and rank else 0.0,
    }


def _first_rank(values: list[Any], gold: Any) -> int | None:
    try:
        return values.index(gold) + 1
    except ValueError:
        return None


def _deduplicated_rankings(
    raw_source_ids: list[str], top_k: int
) -> tuple[list[str], list[str]]:
    all_source_ids: list[str] = []
    for source_id in raw_source_ids:
        if source_id not in all_source_ids:
            all_source_ids.append(source_id)

    source_ids = all_source_ids[:top_k]
    doc_ids: list[str] = []
    for source_id in all_source_ids:
        doc_id, _ = _parse_source_id(source_id)
        if doc_id not in doc_ids:
            doc_ids.append(doc_id)
        if len(doc_ids) >= top_k:
            break
    return source_ids, doc_ids


def _metric_summary(rows: list[dict[str, Any]], prefix: str) -> dict[str, float]:
    metric_names = sorted(
        {
            key
            for row in rows
            for key in row
            if key.startswith(f"{prefix}_")
            and any(token in key for token in ("hit_at_", "mrr_at_", "ndcg_at_"))
        }
    )
    return {
        name.removeprefix(f"{prefix}_"): round(
            statistics.fmean(float(row[name]) for row in rows), 6
        )
        for name in metric_names
    }


def _evaluate(
    questions: list[dict[str, Any]],
    qrels: dict[str, dict[str, Any]],
    *,
    top_k: int,
    checkpoint_path: Path,
    output_path: Path,
    run_fingerprint: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from backend.app.core import embeddings
    from backend.app.core.retrieval_scoring import scoring_ledger

    production_model = embeddings._get_sentence_transformer(  # noqa: SLF001
        str(Path(os.environ["CML_EMBEDDING_MODEL"]).resolve()),
        Path(os.environ["CML_EMBEDDING_CACHE_DIR"]).resolve(),
    )
    if not str(production_model.device).startswith("cuda"):
        raise RuntimeError(
            f"production query embedder unexpectedly loaded on {production_model.device}"
        )

    question_ids = [str(question["question_id"]) for question in questions]
    existing = {
        str(row["question_id"]): row
        for row in _load_jsonl(checkpoint_path)
        if row.get("run_fingerprint") == run_fingerprint
        and str(row.get("question_id")) in question_ids
    }
    _write_progress(
        output_path,
        total=len(questions),
        completed=len(existing),
        detail="resuming retrieval checkpoint",
    )
    result_limit = max(100, top_k)
    for position, question in enumerate(questions, start=1):
        question_id = str(question["question_id"])
        if question_id in existing:
            continue
        started = time.perf_counter()
        ledger = scoring_ledger(
            VAULT_ID, question["question"], cluster_id=None, limit=result_limit
        )
        latency = time.perf_counter() - started

        raw_source_ids = [str(hit["source_id"]) for hit in ledger["results"]]
        source_ids, doc_ids = _deduplicated_rankings(raw_source_ids, top_k)
        first_hit_by_source: dict[str, dict[str, Any]] = {}
        for hit in ledger["results"]:
            source_id = str(hit["source_id"])
            first_hit_by_source.setdefault(source_id, hit)
        retrieved_evidence = []
        for source_id in source_ids:
            hit = first_hit_by_source[source_id]
            doc_id, section_id = _parse_source_id(source_id)
            retrieved_evidence.append(
                {
                    "source_id": source_id,
                    "doc_id": doc_id,
                    "section_id": section_id,
                    "chunk_id": str(hit["chunk_id"]),
                    "chunk_index": int(hit["chunk_index"]),
                    "semantic_score": float(hit["semantic_score"]),
                    "bm25_score": float(hit["bm25_score"]),
                    "combined_score": float(hit["combined_score"]),
                    "text": str(hit["snippet"]),
                }
            )

        qrel = qrels[question["question_id"]]
        gold_doc_id = str(qrel["doc_id"])
        gold_section_id = int(qrel["section_id"])
        gold_source_id = _source_id(gold_doc_id, gold_section_id)
        raw_section_rank = _first_rank(raw_source_ids, gold_source_id)
        section_rank = _first_rank(source_ids, gold_source_id)
        document_rank = _first_rank(doc_ids, gold_doc_id)
        row = {
            **question,
            "run_fingerprint": run_fingerprint,
            "gold_doc_id": gold_doc_id,
            "gold_section_id": gold_section_id,
            "gold_source_id": gold_source_id,
            "raw_chunk_section_rank": raw_section_rank,
            "section_rank": section_rank,
            "document_rank": document_rank,
            "retrieved_source_ids": source_ids,
            "retrieved_doc_ids": doc_ids,
            "retrieved_evidence": retrieved_evidence,
            "chunks_considered": int(ledger["chunks_considered"]),
            "latency_seconds": round(latency, 4),
        }
        for cutoff in sorted({1, 5, 10, top_k}):
            for name, value in _rank_metrics(section_rank, cutoff).items():
                row[f"section_{name}"] = value
            for name, value in _rank_metrics(document_rank, cutoff).items():
                row[f"document_{name}"] = value
            for name, value in _rank_metrics(raw_section_rank, cutoff).items():
                row[f"raw_chunk_section_{name}"] = value
        existing[question_id] = row
        _append_jsonl(checkpoint_path, row)
        _write_progress(
            output_path,
            total=len(questions),
            completed=len(existing),
            detail=f"{position}/{len(questions)} {question_id}",
        )
        print(
            f"evaluated {position}/{len(questions)} "
            f"(section_rank={section_rank}, document_rank={document_rank}, "
            f"latency={latency:.2f}s)",
            flush=True,
        )

    rows = [existing[question_id] for question_id in question_ids]
    _write_jsonl(checkpoint_path, rows)
    latencies = [float(row["latency_seconds"]) for row in rows]
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_modality: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_type[row["question_type"]].append(row)
        by_modality[row["source_modality"]].append(row)
    summary = {
        "question_count": len(rows),
        "section": _metric_summary(rows, "section"),
        "document": _metric_summary(rows, "document"),
        "raw_chunk_section": _metric_summary(rows, "raw_chunk_section"),
        "by_question_type": {
            key: {"count": len(group), "section": _metric_summary(group, "section")}
            for key, group in sorted(by_type.items())
        },
        "by_source_modality": {
            key: {
                "count": len(group),
                "section": _metric_summary(group, "section"),
            }
            for key, group in sorted(by_modality.items())
        },
        "mean_query_latency_seconds": round(statistics.fmean(latencies), 4),
        "p95_query_latency_seconds": round(
            sorted(latencies)[max(0, math.ceil(len(latencies) * 0.95) - 1)], 4
        ),
    }
    return rows, summary


def _run(args: argparse.Namespace) -> int:
    dataset_root = args.dataset_root.resolve()
    model_path = args.model.resolve()
    required = [
        dataset_root / "queries.json",
        dataset_root / "qrels.json",
        dataset_root / "corpus",
        model_path,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing required paths: {missing}")
    gpu_name = _require_gpu()

    queries = json.loads((dataset_root / "queries.json").read_text(encoding="utf-8"))
    questions = _select_questions(
        queries,
        selection=args.selection,
        count=args.questions,
        seed=args.seed,
    )
    dataset_identity = _dataset_identity(dataset_root, args.dataset_revision)
    expected_signature = _index_signature(dataset_identity, model_path)
    if int(dataset_identity["corpus"]["file_count"]) != 1_000:
        raise ValueError("expected exactly 1,000 Open RAG Bench corpus files")
    reusable_manifest = args.work_dir.resolve() / "index-manifest.json"
    documents = (
        []
        if reusable_manifest.exists() and not args.rebuild_index
        else _load_corpus(dataset_root / "corpus")
    )

    index = _build_or_reuse_index(
        documents=documents,
        work_dir=args.work_dir.resolve(),
        model_path=model_path,
        embedding_batch_size=max(1, args.embedding_batch_size),
        expected_signature=expected_signature,
        rebuild=args.rebuild_index,
    )

    # Gold labels enter only after corpus indexing is complete.
    qrels = json.loads((dataset_root / "qrels.json").read_text(encoding="utf-8"))
    from backend.app.core.database import connect

    with connect() as conn:
        indexed_source_rows = conn.execute(
            "SELECT id FROM sources WHERE vault_id = ? AND deleted_at IS NULL",
            (VAULT_ID,),
        ).fetchall()
    indexed_paper_ids = {
        _parse_source_id(str(row["id"]))[0] for row in indexed_source_rows
    }
    empty_paper_ids = sorted(
        path.stem
        for path in (dataset_root / "corpus").glob("*.json")
        if path.stem not in indexed_paper_ids
    )
    missing_qrels = [
        item["question_id"] for item in questions if item["question_id"] not in qrels
    ]
    if missing_qrels:
        raise ValueError(f"selected questions missing qrels: {missing_qrels}")
    gold_empty_papers = sorted(
        {
            str(qrel["doc_id"])
            for qrel in qrels.values()
            if str(qrel["doc_id"]) in empty_paper_ids
        }
    )
    if gold_empty_papers:
        raise ValueError(
            f"corpus papers with no indexable sections are gold targets: {gold_empty_papers}"
        )
    retrieval_run_fingerprint = _fingerprint(
        {
            "schema_version": 1,
            "dataset_identity": dataset_identity,
            "index_signature": expected_signature,
            "question_ids": [item["question_id"] for item in questions],
            "top_k": max(1, min(10, args.top_k)),
            "retriever": "production scoring_ledger (70% semantic, 30% BM25)",
            "evidence_contract": "first_chunk_per_deduplicated_source_v1",
        }
    )
    checkpoint_path = args.output.with_name(
        args.output.stem + ".retrieval.jsonl"
    )
    results, summary = _evaluate(
        questions,
        qrels,
        top_k=max(1, min(10, args.top_k)),
        checkpoint_path=checkpoint_path,
        output_path=args.output,
        run_fingerprint=retrieval_run_fingerprint,
    )

    report = {
        "schema_version": 1,
        "system": "Vault production hybrid retrieval",
        "dataset": "vectara/open_ragbench",
        "dataset_identity": dataset_identity,
        "run_fingerprint": retrieval_run_fingerprint,
        "protocol": {
            "selection_mode": args.selection,
            "selection": (
                f"all {len(questions)} query IDs in sorted order"
                if args.selection == "all"
                else (
                    f"first {len(questions)} sorted query IDs"
                    if args.selection == "first"
                    else f"{len(questions)} query IDs sampled from sorted IDs with seed {args.seed}"
                )
            ),
            "seed": args.seed if args.selection == "seeded" else None,
            "question_ids": [item["question_id"] for item in questions],
            "full_corpus_search": True,
            "corpus_scope": (
                "all indexable sections from the 1,000-paper corpus in one Vault; "
                "no gold-based cluster filtering"
            ),
            "empty_non_gold_paper_ids": empty_paper_ids,
            "granularity": "Open RAG Bench section represented as one Vault document source",
            "content": "section text plus Markdown tables; base64 images excluded",
            "retriever": "production scoring_ledger (70% semantic, 30% BM25)",
            "source_weight": 1.0,
            "embedding_model": str(model_path),
            "embedding_device_policy": "CUDA required; no CPU fallback",
            "gpu_name": gpu_name,
            "top_k": max(1, min(10, args.top_k)),
            "ranking": "first hit per Vault source; paper list also deduplicated",
            "answers_loaded": False,
            "qrels_used_for": "metrics only, after indexing",
            "qa_reader": None,
            "qa_judge": None,
        },
        "limitations": [
            "This is a retrieval-only benchmark; it does not measure answer generation.",
            "Image bytes are not indexed because Vault's production retriever is text-only.",
            "Text-image and text-table-image strata are therefore diagnostic lower bounds.",
            "Section-as-source tests structured corpus ingestion, not Vault's raw-PDF parser.",
            (
                f"{len(empty_paper_ids)} corpus papers contain no sections and cannot be "
                "indexed; none is a gold target."
            ),
        ],
        "index": index,
        "summary": summary,
        "results": results,
        "checkpoint": str(checkpoint_path),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"summary": summary, "index": index, "output": str(args.output)}, indent=2))
    return 0


def main() -> int:
    args = parse_args()
    lock_path = args.work_dir.resolve().parent / "open-rag-bench-index.lock"
    with _exclusive_lock(lock_path):
        return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
