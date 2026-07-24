from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rerank saved LongMemEval session candidates with a local cross-encoder. "
            "The policy is fixed, answer-blind, GPU-only, and makes no API calls."
        )
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--retrieval", type=Path, required=True)
    parser.add_argument("--cross-encoder", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--chunk-chars", type=int, default=1_200)
    parser.add_argument("--chunk-overlap", type=int, default=200)
    parser.add_argument("--batch-size", type=int, default=64)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _chunks(text: str, size: int, overlap: int) -> list[str]:
    compact = " ".join(str(text or "").split())
    if not compact:
        return [""]
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("chunk size must be positive and overlap smaller than size")
    output: list[str] = []
    start = 0
    while start < len(compact):
        end = min(len(compact), start + size)
        output.append(compact[start:end])
        if end == len(compact):
            break
        start = end - overlap
    return output


def _session_text(date: object, turns: list[dict]) -> str:
    lines = [f"Date: {date}"]
    for turn in turns:
        role = str(turn.get("role") or "unknown").strip().lower()
        content = " ".join(str(turn.get("content") or "").split())
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _recall(row: dict, ids: list[str]) -> float:
    gold = {str(item) for item in row.get("answer_session_ids") or []}
    if not gold:
        return 1.0
    return len(gold & set(ids)) / len(gold)


def rerank(
    model: Any,
    *,
    dataset: list[dict],
    retrieval: dict,
    top_k: int,
    chunk_chars: int,
    chunk_overlap: int,
    batch_size: int,
) -> dict:
    references = {str(row["question_id"]): row for row in dataset}
    results: list[dict] = []
    elapsed: list[float] = []
    for position, source in enumerate(retrieval["results"], start=1):
        question_id = str(source["question_id"])
        reference = references[question_id]
        session_map: dict[str, list[tuple[str, list[dict]]]] = {}
        for session_id, date, turns in zip(
            reference["haystack_session_ids"],
            reference["haystack_dates"],
            reference["haystack_sessions"],
            strict=True,
        ):
            session_map.setdefault(str(session_id), []).append((str(date), turns))

        pairs: list[list[str]] = []
        owners: list[str] = []
        original_ids = [str(item) for item in source["retrieved_session_ids"]]
        started = time.perf_counter()
        for session_id in original_ids:
            envelopes = session_map.get(session_id) or []
            text = "\n".join(
                _session_text(date, turns) for date, turns in envelopes
            )
            for chunk in _chunks(text, chunk_chars, chunk_overlap):
                pairs.append([str(source["question"]), chunk])
                owners.append(session_id)
        predictions = model.predict(
            pairs,
            batch_size=max(1, batch_size),
            show_progress_bar=False,
        )
        session_scores: dict[str, float] = {}
        for session_id, score in zip(owners, predictions, strict=True):
            session_scores[session_id] = max(
                session_scores.get(session_id, -math.inf), float(score)
            )
        cross_ranked = sorted(
            original_ids,
            key=lambda item: (
                session_scores.get(item, -math.inf),
                -original_ids.index(item),
            ),
            reverse=True,
        )
        cross_rank = {session_id: rank for rank, session_id in enumerate(cross_ranked, 1)}
        original_rank = {
            session_id: rank for rank, session_id in enumerate(original_ids, 1)
        }
        # Equal-weight reciprocal-rank fusion is fixed before evaluation. It keeps the
        # strong production retriever as a co-equal signal instead of trusting a
        # passage model trained on unrelated web-search data.
        fused = sorted(
            original_ids,
            key=lambda item: (
                1 / (60 + original_rank[item]) + 1 / (60 + cross_rank[item]),
                -original_rank[item],
            ),
            reverse=True,
        )
        selected_ids = fused[: max(1, top_k)]
        elapsed.append(time.perf_counter() - started)
        results.append(
            {
                **source,
                "retrieved_session_ids": selected_ids,
                "rank": selected_ids,
                "found_session_ids": sorted(
                    set(selected_ids)
                    & {str(item) for item in source.get("answer_session_ids") or []}
                ),
                "recall_at_k": _recall(source, selected_ids),
                "any_evidence_at_k": bool(
                    set(selected_ids)
                    & {str(item) for item in source.get("answer_session_ids") or []}
                ),
                "session_reranker": {
                    "original_session_ids": original_ids,
                    "cross_encoder_order": cross_ranked,
                    "fused_order": fused,
                    "cross_encoder_scores": session_scores,
                    "elapsed_seconds": round(elapsed[-1], 4),
                },
            }
        )
        if position % 25 == 0 or position == len(retrieval["results"]):
            print(f"reranked {position}/{len(retrieval['results'])}", flush=True)

    recalls = [float(row["recall_at_k"]) for row in results]
    complete = sum(value == 1.0 for value in recalls)
    return {
        **{key: value for key, value in retrieval.items() if key not in {"results", "protocol", "summary"}},
        "protocol": {
            **(retrieval.get("protocol") or {}),
            "session_reranker": "cross-encoder-max-chunk-equal-rrf-v1",
            "top_k": top_k,
            "chunk_chars": chunk_chars,
            "chunk_overlap": chunk_overlap,
            "rrf_constant": 60,
            "retriever_weight": 1.0,
            "cross_encoder_weight": 1.0,
            "answer_or_gold_used_for_ranking": False,
            "reader_or_judge_api_calls": 0,
            "gpu_required": True,
        },
        "summary": {
            "question_count": len(results),
            "macro_recall_at_k": round(statistics.fmean(recalls), 6),
            "complete_recall_count": complete,
            "mean_reranker_seconds": round(statistics.fmean(elapsed), 4),
            "p95_reranker_seconds": round(
                sorted(elapsed)[max(0, math.ceil(len(elapsed) * 0.95) - 1)], 4
            ),
        },
        "results": results,
    }


def main() -> int:
    args = parse_args()
    if not args.cross_encoder.is_dir():
        raise RuntimeError("Cross-encoder must be an existing local directory")
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required; CPU reranking is forbidden")
    from sentence_transformers import CrossEncoder

    model = CrossEncoder(
        str(args.cross_encoder),
        device="cuda",
        local_files_only=True,
    )
    device = str(getattr(model, "device", ""))
    if not device.startswith("cuda"):
        raise RuntimeError(f"Cross-encoder did not load on CUDA: {device!r}")
    report = rerank(
        model,
        dataset=json.loads(args.dataset.read_text(encoding="utf-8")),
        retrieval=json.loads(args.retrieval.read_text(encoding="utf-8")),
        top_k=max(1, args.top_k),
        chunk_chars=args.chunk_chars,
        chunk_overlap=args.chunk_overlap,
        batch_size=max(1, args.batch_size),
    )
    report["protocol"]["cross_encoder"] = str(args.cross_encoder.resolve())
    report["protocol"]["cross_encoder_sha256"] = _sha256(
        args.cross_encoder / "model.safetensors"
    )
    report["protocol"]["device"] = device
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(report["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
