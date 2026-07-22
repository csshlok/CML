from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.atomic_memory_v2 import (  # noqa: E402
    AtomicMemoryV2Response,
    atomic_memory_v2_json_schema,
    atomic_memory_v2_prompt,
    normalize_atomic_memory_v2,
    semantic_signatures,
)


DEFAULT_FIXTURES = REPO_ROOT / "backend/tests/fixtures/atomic_memory_v2_extraction.json"
DEFAULT_GATES = REPO_ROOT / "backend/tests/fixtures/atomic_memory_v2_gates.json"
RUNNER_PROTOCOL = "atomic-memory-v2-extractor-matrix-v1"


@dataclass(frozen=True)
class CandidateSpec:
    label: str
    model: str
    base_url: str


def parse_candidate(value: str) -> CandidateSpec:
    parts = value.split("|", 2)
    if len(parts) != 3 or not all(part.strip() for part in parts):
        raise argparse.ArgumentTypeError(
            "candidate must be LABEL|MODEL|LOOPBACK_BASE_URL"
        )
    label, model, base_url = (part.strip() for part in parts)
    hostname = (urlparse(base_url).hostname or "").casefold()
    if hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise argparse.ArgumentTypeError("candidate endpoint must be loopback-only")
    return CandidateSpec(label=label, model=model, base_url=base_url.rstrip("/"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the frozen Atomic Memory v2 extraction suite on local GPU models."
    )
    parser.add_argument(
        "--candidate",
        action="append",
        type=parse_candidate,
        required=True,
        help="Repeat LABEL|MODEL|LOOPBACK_BASE_URL for every candidate.",
    )
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--gates", type=Path, default=DEFAULT_GATES)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".tmp/atomic-memory-v2-extractor-matrix"),
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--max-tokens", type=int, default=2_048)
    parser.add_argument("--fixture-id", action="append", default=[])
    parser.add_argument("--refresh", action="store_true")
    return parser.parse_args()


def load_fixture_bundle(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    fixtures = payload.get("fixtures")
    if not isinstance(fixtures, list) or len(fixtures) < 30:
        raise ValueError("atomic_v2_fixture_bundle_requires_at_least_30_fixtures")
    identifiers = [str(item.get("id") or "") for item in fixtures]
    if any(not identifier for identifier in identifiers) or len(set(identifiers)) != len(identifiers):
        raise ValueError("atomic_v2_fixture_ids_must_be_unique")
    for fixture in fixtures:
        session = fixture.get("session") or {}
        if not session.get("session_id") or not isinstance(session.get("turns"), list):
            raise ValueError(f"invalid fixture session: {fixture.get('id')}")
        if any(
            str(turn.get("role") or "") not in {"user", "assistant", "tool"}
            for turn in session["turns"]
        ):
            raise ValueError(f"invalid fixture source role: {fixture.get('id')}")
        if not isinstance(fixture.get("required"), list) or not isinstance(fixture.get("forbidden"), list):
            raise ValueError(f"invalid fixture signatures: {fixture.get('id')}")
    return payload


def load_gate_manifest(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    thresholds = payload.get("thresholds")
    if not payload.get("gate_version") or not isinstance(thresholds, dict):
        raise ValueError("invalid_atomic_v2_gate_manifest")
    return payload


def cuda_preflight() -> dict:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required; CPU extraction fallback is disabled")
    device = torch.device("cuda:0")
    free_bytes, total_bytes = torch.cuda.mem_get_info(device)
    left = torch.randn((256, 256), device=device)
    right = torch.randn((256, 256), device=device)
    torch.cuda.synchronize(device)
    started = time.perf_counter()
    value = left @ right
    torch.cuda.synchronize(device)
    return {
        "cuda_ready": True,
        "device": torch.cuda.get_device_name(device),
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "free_mib": free_bytes // 1024**2,
        "total_mib": total_bytes // 1024**2,
        "smoke_seconds": round(time.perf_counter() - started, 6),
        "smoke_value": float(value[0, 0]),
        "cpu_fallback_allowed": False,
    }


class NvidiaMemorySampler:
    def __init__(self, interval_seconds: float = 0.2) -> None:
        self.interval_seconds = interval_seconds
        self.samples: list[int] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "NvidiaMemorySampler":
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    @property
    def peak_mib(self) -> int:
        return max(self.samples, default=0)

    def _sample_loop(self) -> None:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        while not self._stop.is_set():
            try:
                result = subprocess.run(
                    [
                        "nvidia-smi",
                        "--id=0",
                        "--query-gpu=memory.used",
                        "--format=csv,noheader,nounits",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=2,
                    creationflags=creationflags,
                )
                values = [
                    int(line.strip())
                    for line in result.stdout.splitlines()
                    if line.strip().isdigit()
                ]
                if values:
                    self.samples.append(values[0])
            except (OSError, subprocess.SubprocessError, ValueError):
                pass
            self._stop.wait(self.interval_seconds)


def _post_chat(
    candidate: CandidateSpec,
    prompt: str,
    *,
    timeout: float,
    max_tokens: int,
) -> dict:
    payload = {
        "model": candidate.model,
        "messages": [
            {
                "role": "system",
                "content": "Compile cited conversational memory into strict JSON. Do not think aloud.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "stream": False,
        "max_tokens": max_tokens,
        "response_format": {
            "type": "json_object",
            "schema": atomic_memory_v2_json_schema(),
        },
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = Request(
        f"{candidate.base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _parse_json_object(text: str) -> dict:
    candidate = str(text or "").strip()
    if candidate.startswith("```"):
        candidate = candidate.removeprefix("```json").removeprefix("```")
        candidate = candidate.removesuffix("```").strip()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        if start < 0:
            raise
        value, _ = json.JSONDecoder().raw_decode(candidate[start:])
    if not isinstance(value, dict):
        raise ValueError("response_root_not_object")
    return value


def evaluate_fixture_response(
    fixture: dict,
    *,
    response_text: str,
    finish_reason: str | None,
    wall_seconds: float,
    peak_gpu_memory_mib: int,
) -> dict:
    required = set(map(str, fixture["required"]))
    forbidden = set(map(str, fixture["forbidden"]))
    session = fixture["session"]
    source_chars = sum(len(str(turn.get("content") or "")) for turn in session["turns"])
    source_tokens_estimate = max(1, math.ceil(source_chars / 4))
    base = {
        "fixture_id": fixture["id"],
        "critical": bool(fixture.get("critical")),
        "wall_seconds": round(wall_seconds, 6),
        "source_tokens_estimate": source_tokens_estimate,
        "seconds_per_1000_source_tokens": round(
            wall_seconds * 1000 / source_tokens_estimate, 6
        ),
        "peak_gpu_memory_mib": int(peak_gpu_memory_mib),
        "finish_reason": finish_reason,
        "truncated": finish_reason == "length",
        "schema_compliant": False,
        "candidate_item_count": 0,
        "accepted_item_count": 0,
        "citation_invalid_count": 0,
        "required_count": len(required),
        "required_hit_count": 0,
        "missing_required": sorted(required),
        "forbidden_hits": [],
        "false_completed_action_hits": [],
        "complete_pass": False,
        "error": None,
    }
    try:
        response = AtomicMemoryV2Response.model_validate(_parse_json_object(response_text))
        base["schema_compliant"] = True
        matches = [item for item in response.sessions if item.session_id == session["session_id"]]
        if len(response.sessions) != 1 or len(matches) != 1:
            raise ValueError("response_requires_exactly_one_matching_session")
        candidate = matches[0]
        candidate_count = (
            len(candidate.entities)
            + len(candidate.events)
            + len(candidate.relations)
            + len(candidate.table_cells)
        )
        normalized = normalize_atomic_memory_v2(
            session,
            candidate,
            processed_turn_indices=range(len(session["turns"])),
            extraction_complete=finish_reason != "length",
            output_truncated=finish_reason == "length",
        )
        signatures = semantic_signatures(normalized)
        hits = required & signatures
        forbidden_hits = forbidden & signatures
        citation_invalid = sum(
            count
            for reason, count in normalized.invalid_by_reason.items()
            if reason.startswith("citation_") or reason == "entity_surface_not_in_citation"
        )
        rejected = sum(normalized.invalid_by_reason.values())
        base.update(
            {
                "candidate_item_count": candidate_count,
                "accepted_item_count": max(0, candidate_count - rejected),
                "citation_invalid_count": citation_invalid,
                "required_hit_count": len(hits),
                "missing_required": sorted(required - hits),
                "forbidden_hits": sorted(forbidden_hits),
                "false_completed_action_hits": sorted(
                    item for item in forbidden_hits if "|completed" in item
                ),
                "invalid_by_reason": normalized.invalid_by_reason,
                "semantic_signatures": sorted(signatures),
            }
        )
        base["complete_pass"] = bool(
            not base["truncated"]
            and not base["missing_required"]
            and not base["forbidden_hits"]
            and not normalized.invalid_by_reason
        )
    except (ValueError, TypeError) as exc:
        base["error"] = f"{type(exc).__name__}:{str(exc)[:300]}"
    return base


def aggregate_candidate_results(results: list[dict]) -> dict:
    count = len(results)
    schema_count = sum(bool(row["schema_compliant"]) for row in results)
    candidate_items = sum(int(row["candidate_item_count"]) for row in results)
    accepted_items = sum(int(row["accepted_item_count"]) for row in results)
    citation_invalid = sum(int(row["citation_invalid_count"]) for row in results)
    required = sum(int(row["required_count"]) for row in results)
    required_hits = sum(int(row["required_hit_count"]) for row in results)
    critical = [row for row in results if row["critical"]]
    normalized_latencies = sorted(
        float(row["seconds_per_1000_source_tokens"]) for row in results
    )
    p95_index = max(0, math.ceil(len(normalized_latencies) * 0.95) - 1)
    return {
        "fixture_count": count,
        "response_schema_compliance_rate": schema_count / count if count else 0.0,
        "accepted_citation_validity_rate": (
            max(0, candidate_items - citation_invalid) / candidate_items
            if candidate_items
            else 0.0
        ),
        "required_signature_recall": required_hits / required if required else 0.0,
        "critical_fixture_complete_pass_rate": (
            sum(bool(row["complete_pass"]) for row in critical) / len(critical)
            if critical
            else 0.0
        ),
        "forbidden_signature_violation_count": sum(
            len(row["forbidden_hits"]) for row in results
        ),
        "false_completed_action_violation_count": sum(
            len(row["false_completed_action_hits"]) for row in results
        ),
        "failed_or_truncated_fixture_count": sum(
            bool(row["error"] or row["truncated"]) for row in results
        ),
        "p95_seconds_per_1000_source_tokens": (
            normalized_latencies[p95_index] if normalized_latencies else 0.0
        ),
        "mean_wall_seconds": statistics.fmean(
            float(row["wall_seconds"]) for row in results
        ) if results else 0.0,
        "peak_gpu_memory_mib": max(
            (int(row["peak_gpu_memory_mib"]) for row in results), default=0
        ),
        "candidate_item_count": candidate_items,
        "accepted_item_count": accepted_items,
    }


def evaluate_gates(metrics: dict, gate_manifest: dict) -> dict:
    thresholds = gate_manifest["thresholds"]
    checks: dict[str, bool] = {}
    for name, threshold in thresholds.items():
        if name.endswith("_min"):
            metric = name.removesuffix("_min")
            checks[name] = float(metrics.get(metric, 0.0)) >= float(threshold)
        elif name.endswith("_max"):
            metric = name.removesuffix("_max")
            checks[name] = float(metrics.get(metric, float("inf"))) <= float(threshold)
        else:
            raise ValueError(f"gate threshold must end in _min or _max: {name}")
    return {
        "gate_version": gate_manifest["gate_version"],
        "passed": all(checks.values()),
        "checks": checks,
        "failed_checks": sorted(name for name, passed in checks.items() if not passed),
    }


def _artifact_path(
    output_dir: Path,
    candidate: CandidateSpec,
    fixture: dict,
    prompt: str,
    *,
    max_tokens: int,
) -> Path:
    digest = hashlib.sha256(
        json.dumps(
            {
                "candidate": candidate.__dict__,
                "fixture": fixture,
                "prompt": prompt,
                "schema": atomic_memory_v2_json_schema(),
                "runner_protocol": RUNNER_PROTOCOL,
                "max_tokens": max_tokens,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return output_dir / "responses" / normalize_label(candidate.label) / f"{digest}.json"


def normalize_label(value: str) -> str:
    safe = "".join(character if character.isalnum() else "-" for character in value.lower())
    return safe.strip("-") or "candidate"


def run_candidate(
    candidate: CandidateSpec,
    fixtures: list[dict],
    *,
    output_dir: Path,
    timeout: float,
    max_tokens: int,
    refresh: bool,
) -> list[dict]:
    results: list[dict] = []
    for position, fixture in enumerate(fixtures, start=1):
        prompt = atomic_memory_v2_prompt(fixture["session"])
        artifact = _artifact_path(
            output_dir,
            candidate,
            fixture,
            prompt,
            max_tokens=max_tokens,
        )
        if artifact.exists() and not refresh:
            response_record = json.loads(artifact.read_text(encoding="utf-8"))
        else:
            started = time.perf_counter()
            try:
                with NvidiaMemorySampler() as sampler:
                    response = _post_chat(
                        candidate,
                        prompt,
                        timeout=timeout,
                        max_tokens=max_tokens,
                    )
                wall_seconds = time.perf_counter() - started
                choice = response["choices"][0]
                response_record = {
                    "response_text": str(choice["message"]["content"]),
                    "finish_reason": choice.get("finish_reason"),
                    "wall_seconds": wall_seconds,
                    "peak_gpu_memory_mib": sampler.peak_mib,
                    "usage": response.get("usage") or {},
                }
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_text(
                    json.dumps(response_record, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            except (OSError, ValueError, KeyError, IndexError) as exc:
                response_record = {
                    "response_text": "",
                    "finish_reason": "request_error",
                    "wall_seconds": time.perf_counter() - started,
                    "peak_gpu_memory_mib": 0,
                    "request_error": f"{type(exc).__name__}:{str(exc)[:300]}",
                }
        evaluated = evaluate_fixture_response(fixture, **{
            key: response_record[key]
            for key in (
                "response_text",
                "finish_reason",
                "wall_seconds",
                "peak_gpu_memory_mib",
            )
        })
        if response_record.get("request_error"):
            evaluated["error"] = response_record["request_error"]
        results.append(evaluated)
        print(
            f"{candidate.label} {position}/{len(fixtures)} {fixture['id']} "
            f"pass={evaluated['complete_pass']} seconds={evaluated['wall_seconds']:.2f}",
            flush=True,
        )
    return results


def main() -> int:
    args = parse_args()
    hardware = cuda_preflight()
    fixture_bundle = load_fixture_bundle(args.fixtures)
    gate_manifest = load_gate_manifest(args.gates)
    selected = set(args.fixture_id)
    fixtures = [
        fixture
        for fixture in fixture_bundle["fixtures"]
        if not selected or fixture["id"] in selected
    ]
    if selected - {fixture["id"] for fixture in fixtures}:
        raise ValueError("one or more requested fixture IDs do not exist")
    reports = []
    for candidate in args.candidate:
        results = run_candidate(
            candidate,
            fixtures,
            output_dir=args.output_dir,
            timeout=args.timeout,
            max_tokens=args.max_tokens,
            refresh=args.refresh,
        )
        metrics = aggregate_candidate_results(results)
        reports.append(
            {
                "candidate": candidate.__dict__,
                "metrics": metrics,
                "gate": evaluate_gates(metrics, gate_manifest),
                "fixtures": results,
            }
        )
    report = {
        "protocol": RUNNER_PROTOCOL,
        "fixture_version": fixture_bundle["fixture_version"],
        "gate_version": gate_manifest["gate_version"],
        "hardware": hardware,
        "fixture_count": len(fixtures),
        "reports": reports,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "matrix-report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**report, "reports": [{"candidate": row["candidate"], "metrics": row["metrics"], "gate": row["gate"]} for row in reports]}, indent=2))
    print(f"wrote {output}")
    return 0 if all(row["gate"]["passed"] for row in reports) else 2


if __name__ == "__main__":
    raise SystemExit(main())
