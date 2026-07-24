from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from scripts.backend.prepare_atomic_extractor_training_data import (
    DEFAULT_PROTECTED,
    _session_hash,
    _walk_objects,
)


PROTOCOL = "atomic-extraction-one-time-holdout-control-v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seal a non-overlapping extraction holdout or claim its one allowed run."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    seal = subparsers.add_parser("seal")
    seal.add_argument("--input", type=Path, required=True)
    seal.add_argument("--output", type=Path, required=True)
    seal.add_argument("--minimum-fixtures", type=int, default=30)
    seal.add_argument(
        "--training-corpus",
        type=Path,
        required=True,
        help="Original independent corpus; evaluation content must not overlap it.",
    )
    seal.add_argument("--protected-manifest", type=Path, action="append", default=[])

    claim = subparsers.add_parser("claim")
    claim.add_argument("--sealed-holdout", type=Path, required=True)
    claim.add_argument("--promotion-report", type=Path, required=True)
    claim.add_argument("--candidate-fingerprint", required=True)
    claim.add_argument("--result-dir", type=Path, required=True)
    claim.add_argument("--registry", type=Path, required=True)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _protected_content(paths: list[Path]) -> tuple[set[str], set[str]]:
    ids: set[str] = set()
    hashes: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in _walk_objects(payload):
            if item.get("id"):
                ids.add(str(item["id"]).casefold())
            if isinstance(item.get("session"), dict):
                hashes.add(_session_hash(item["session"]))
    return ids, hashes


def seal(args: argparse.Namespace) -> int:
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    evaluation_role = payload.get("evaluation_role")
    if evaluation_role not in {"validation", "holdout"}:
        raise ValueError("evaluation_bundle_requires_validation_or_holdout_role")
    fixtures = payload.get("fixtures") or []
    if len(fixtures) < args.minimum_fixtures:
        raise ValueError("holdout_bundle_below_minimum_fixture_count")
    protected = [*DEFAULT_PROTECTED, args.training_corpus, *args.protected_manifest]
    protected_ids, protected_hashes = _protected_content(protected)
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    for fixture in fixtures:
        fixture_id = str(fixture.get("id") or "").casefold()
        if not fixture_id or fixture_id in seen_ids:
            raise ValueError("holdout_fixture_ids_must_be_unique_and_nonempty")
        digest = _session_hash(fixture.get("session") or {})
        if digest in seen_hashes:
            raise ValueError("holdout_session_content_must_be_unique")
        if fixture_id in protected_ids or digest in protected_hashes:
            raise ValueError("holdout_overlaps_protected_evaluation_content")
        seen_ids.add(fixture_id)
        seen_hashes.add(digest)
    payload["holdout_control_protocol"] = PROTOCOL
    payload["details_policy"] = (
        "redacted-during-scoring"
        if evaluation_role == "holdout"
        else "development-team-visible"
    )
    payload["one_time_use"] = evaluation_role == "holdout"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    args.output.write_text(content, encoding="utf-8")
    seal_manifest = {
        "protocol": PROTOCOL,
        "sealed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fixture_count": len(fixtures),
        "evaluation_role": evaluation_role,
        "sealed_file": str(args.output),
        "sealed_file_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "protected_inputs": [
            {"path": str(path), "sha256": _sha256(path)}
            for path in protected
            if path.exists()
        ],
        "status": "sealed_unused",
    }
    seal_path = args.output.with_suffix(args.output.suffix + ".seal.json")
    seal_path.write_text(
        json.dumps(seal_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(seal_manifest, indent=2))
    return 0


def claim(args: argparse.Namespace) -> int:
    promotion = json.loads(args.promotion_report.read_text(encoding="utf-8"))
    if not promotion.get("holdout_authorized"):
        raise ValueError("checkpoint_promotion_did_not_authorize_holdout")
    seal_path = args.sealed_holdout.with_suffix(
        args.sealed_holdout.suffix + ".seal.json"
    )
    seal_manifest = json.loads(seal_path.read_text(encoding="utf-8"))
    if seal_manifest.get("evaluation_role") != "holdout":
        raise ValueError("only_holdout_bundles_use_one_time_claims")
    holdout_hash = _sha256(args.sealed_holdout)
    if seal_manifest.get("sealed_file_sha256") != holdout_hash:
        raise ValueError("sealed_holdout_hash_mismatch")
    if args.result_dir.exists():
        raise ValueError("holdout_result_directory_must_not_preexist")
    registry = (
        json.loads(args.registry.read_text(encoding="utf-8"))
        if args.registry.exists()
        else {"protocol": PROTOCOL, "claims": []}
    )
    key = f"{holdout_hash}:{args.candidate_fingerprint}"
    if any(row.get("key") == key for row in registry.get("claims") or []):
        raise ValueError("holdout_already_claimed_for_candidate")
    claim_row = {
        "key": key,
        "holdout_sha256": holdout_hash,
        "candidate_fingerprint": args.candidate_fingerprint,
        "promotion_report_sha256": _sha256(args.promotion_report),
        "result_dir": str(args.result_dir),
        "claimed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "process_id": os.getpid(),
        "status": "claimed_one_time",
    }
    registry.setdefault("claims", []).append(claim_row)
    args.registry.parent.mkdir(parents=True, exist_ok=True)
    args.registry.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.result_dir.mkdir(parents=True, exist_ok=False)
    (args.result_dir / "holdout-authorization.json").write_text(
        json.dumps(claim_row, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(claim_row, indent=2))
    return 0


def main() -> int:
    args = parse_args()
    try:
        return seal(args) if args.command == "seal" else claim(args)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
