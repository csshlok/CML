from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.typed_evidence import SCHEMA_HASH, extract_evidence, plan_query
from scripts.backend.evaluate_vault_longmemeval_api import _chat, _provider, _usage


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Precompute and cache source-centric typed evidence before answer evaluation."
    )
    parser.add_argument("--retrieval", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".tmp/vault-odin-memory-benchmark/typed-evidence-cache"),
    )
    parser.add_argument("--provider", choices=("kimi", "openai"), default="kimi")
    parser.add_argument("--model", default="kimi-k2.6")
    parser.add_argument("--max-tokens", type=int, default=8_192)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument(
        "--deterministic-only",
        action="store_true",
        help="Cache authoritative deterministic sentence evidence without semantic API calls.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    retrieval = json.loads(args.retrieval.read_text(encoding="utf-8"))
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    references = {str(row["question_id"]): row for row in dataset}
    provider = _provider(args.provider, args.model)
    selected = [
        row
        for row in retrieval["results"]
        if plan_query(references[str(row["question_id"])]).intent != "unsupported"
    ]
    rows: list[dict] = []
    total_started = time.perf_counter()
    for position, row in enumerate(selected, start=1):
        question_id = str(row["question_id"])
        reference = references[question_id]

        def extractor(prompt: str) -> tuple[str, dict]:
            response = _chat(
                provider,
                prompt,
                max_tokens=args.max_tokens,
                timeout=args.timeout,
                retries=args.retries,
            )
            return response["choices"][0]["message"]["content"].strip(), _usage(response)

        _, diagnostics = extract_evidence(
            reference,
            row["retrieved_session_ids"],
            model=provider.model,
            cache_dir=args.cache_dir,
            extractor=None if args.deterministic_only else extractor,
        )
        result = {
            "question_id": question_id,
            "intent": plan_query(reference).intent,
            **diagnostics.model_dump(mode="json"),
        }
        rows.append(result)
        checkpoint = {
            "schema_hash": SCHEMA_HASH,
            "provider": provider.name,
            "model": provider.model,
            "completed_question_count": len(rows),
            "results": rows,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
        print(
            f"extraction {position}/{len(selected)} {question_id} "
            f"cache={diagnostics.cache_hit_count}/{diagnostics.requested_session_count} "
            f"valid={diagnostics.valid_claim_count} invalid={diagnostics.invalid_claim_count}",
            flush=True,
        )

    usages = [row["usage"] for row in rows]
    prompt_tokens = sum(int(usage.get("prompt_tokens") or 0) for usage in usages)
    completion_tokens = sum(int(usage.get("completion_tokens") or 0) for usage in usages)
    requested = sum(int(row["requested_session_count"]) for row in rows)
    hits = sum(int(row["cache_hit_count"]) for row in rows)
    valid = sum(int(row["valid_claim_count"]) for row in rows)
    invalid = sum(int(row["invalid_claim_count"]) for row in rows)
    report = {
        "schema_hash": SCHEMA_HASH,
        "provider": provider.name,
        "model": provider.model,
        "deterministic_only": args.deterministic_only,
        "question_count": len(rows),
        "requested_session_count": requested,
        "cache_hit_count": hits,
        "cache_hit_rate": round(hits / requested, 4) if requested else None,
        "valid_claim_count": valid,
        "invalid_claim_count": invalid,
        "claim_acceptance_rate": round(valid / (valid + invalid), 4)
        if valid + invalid
        else None,
        "extraction_failure_count": sum(bool(row["extraction_failed"]) for row in rows),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "mean_question_wall_seconds": round(
            statistics.fmean(float(row["wall_seconds"]) for row in rows), 4
        )
        if rows
        else None,
        "total_wall_seconds": round(time.perf_counter() - total_started, 4),
        "results": rows,
    }
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
