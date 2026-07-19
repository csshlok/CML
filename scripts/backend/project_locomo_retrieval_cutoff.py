from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def project(report: dict[str, Any], cutoff: int) -> dict[str, Any]:
    selected_cutoff = max(1, cutoff)
    projected_results = []
    for row in report.get("results") or []:
        retrieved = list(row.get("retrieved") or [])[:selected_cutoff]
        gold = {str(value) for value in row.get("evidence") or []}
        found = gold & {str(hit.get("evidence_id") or "") for hit in retrieved}
        projected_results.append(
            {
                **row,
                "retrieved": retrieved,
                "found_evidence": sorted(found),
                "recall_at_k": len(found) / len(gold) if gold else None,
                "any_evidence_at_k": bool(found) if gold else None,
            }
        )
    protocol = {**(report.get("protocol") or {}), "top_k": selected_cutoff}
    protocol["projection"] = {
        "source_top_k": int((report.get("protocol") or {}).get("top_k") or 0),
        "projected_top_k": selected_cutoff,
        "ranking_unchanged": True,
    }
    return {**report, "protocol": protocol, "results": projected_results}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Project a saved LoCoMo retrieval trace to a smaller cutoff."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cutoff", type=int, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = project(json.loads(args.input.read_text(encoding="utf-8")), args.cutoff)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "question_count": len(payload["results"]),
                "top_k": payload["protocol"]["top_k"],
                "output": str(args.output),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
