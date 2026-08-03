from __future__ import annotations

# DEAD EXPERIMENT (2026-08-03): selection helper retained with the failed Qwen
# fact-extraction A/B for audit only. Its executable entry point is disabled.

import argparse
import hashlib
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.backend.benchmark_reader_evidence_local import select_references  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freeze a disjoint LongMemEval fact-extraction A/B sample."
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--per-stratum", type=int, default=2)
    parser.add_argument("--seed", default="vault-fact-extraction-ab-2026-08-02")
    parser.add_argument("--exclude-report", type=Path, action="append", default=[])
    args = parser.parse_args()

    payload = args.dataset.read_bytes()
    dataset = json.loads(payload)
    excluded: set[str] = set()
    for path in args.exclude_report:
        if not path.exists():
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        excluded.update(str(value) for value in report.get("question_ids") or [])
        excluded.update(str(row.get("question_id")) for row in report.get("rows") or [])
    selected = select_references(
        dataset,
        per_stratum=args.per_stratum,
        seed=args.seed,
        excluded_ids=excluded,
    )
    clean = [
        {key: value for key, value in row.items() if key != "evaluation_stratum"}
        for row in selected
    ]
    manifest = {
        "schema_version": 1,
        "protocol": "vault-local-mem0-style-fact-ab-selection-v1",
        "source_dataset_sha256": hashlib.sha256(payload).hexdigest(),
        "seed": args.seed,
        "per_stratum": args.per_stratum,
        "excluded_question_count": len(excluded),
        "items": [
            {"question_id": row["question_id"], "stratum": row["evaluation_stratum"]}
            for row in selected
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "manifest": str(args.manifest),
                "question_count": len(clean),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(
        "DEAD EXPERIMENT: the associated Qwen fact-extraction A/B was retired"
    )
    # raise SystemExit(main())  # Intentionally disabled; audit code only.
