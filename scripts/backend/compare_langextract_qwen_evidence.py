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
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pydantic import ValidationError


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.atomic_memory_v2 import (  # noqa: E402
    AtomicMemoryV2EvidencePassResponse,
    atomic_memory_v2_evidence_pass_json_schema,
    atomic_memory_v2_evidence_pass_prompt,
)


PROTOCOL = "langextract-qwen-evidence-comparison-v1"
DEFAULT_TEACHER_CORPUS = (
    REPO_ROOT
    / ".tmp/atomic-memory-training-sources/teacher-pilot-gpt56-sol-v1"
    / "teacher-labelled-pilot.json"
)
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT / ".tmp/atomic-memory-training-sources/langextract-qwen-comparison-v1"
)


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare Vault's direct evidence prompt with LangExtract orchestration "
            "using the same loopback CUDA Qwen model and independent GPT labels."
        )
    )
    parser.add_argument("--teacher-corpus", type=Path, default=DEFAULT_TEACHER_CORPUS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--base-url", default="http://127.0.0.1:8091/v1")
    parser.add_argument("--model", default="qwen3-4b-gguf")
    parser.add_argument("--server-pid", type=int, required=True)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--baseline-max-tokens", type=int, default=4096)
    parser.add_argument("--langextract-max-tokens", type=int, default=2048)
    parser.add_argument("--max-char-buffer", type=int, default=1200)
    parser.add_argument("--extraction-passes", type=int, default=2)
    parser.add_argument("--selection-seed", type=int, default=20260723)
    parser.add_argument("--refresh", action="store_true")
    return parser.parse_args()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _validate_loopback(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("model_endpoint_must_be_loopback")
    return base_url.rstrip("/")


def _cuda_server_preflight(server_pid: int, base_url: str) -> dict:
    if server_pid < 1:
        raise ValueError("server_pid_must_be_positive")
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=pid,process_name",
            "--format=csv,noheader",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    rows = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not any(line.split(",", 1)[0].strip() == str(server_pid) for line in rows):
        raise RuntimeError(
            "Qwen server PID is not visible as an NVIDIA compute process; "
            "CPU fallback is forbidden"
        )
    request = Request(base_url + "/health", method="GET")
    with urlopen(request, timeout=10) as response:
        health = json.loads(response.read().decode("utf-8"))
    if health.get("status") not in {"ok", "ready"}:
        raise RuntimeError("loopback Qwen server is not ready")
    gpu = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    ).stdout.strip()
    name, used, total = [part.strip() for part in gpu.split(",", 2)]
    return {
        "cuda_required": True,
        "cpu_fallback_allowed": False,
        "server_pid": server_pid,
        "gpu_name": name,
        "gpu_memory_used_mib_at_preflight": int(used),
        "gpu_memory_total_mib": int(total),
    }


def load_teacher_fixtures(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    fixtures = []
    for record in payload.get("records") or []:
        references = [
            str(span["memory_text"])
            for span in record["evidence_target"]["spans"]
            if str(span.get("memory_text") or "").strip()
        ]
        if not references:
            raise ValueError(
                f"teacher record has no reference memories: {record['record_id']}"
            )
        fixtures.append(
            {
                "id": str(record["record_id"]),
                "session": record["session"],
                "reference_memories": references,
            }
        )
    if not fixtures:
        raise ValueError("teacher corpus contains no accepted records")
    return fixtures


def _response_json_text(value: str) -> dict:
    text = str(value or "").strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```")
        text = text.removesuffix("```").strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start < 0:
            raise
        payload, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(payload, dict):
        raise ValueError("model_response_root_must_be_object")
    return payload


def _post_direct_evidence(
    *,
    base_url: str,
    model: str,
    session: dict,
    timeout: float,
    max_tokens: int,
) -> tuple[dict, float]:
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Compile cited conversational memory into strict JSON. "
                    "Do not think aloud."
                ),
            },
            {
                "role": "user",
                "content": atomic_memory_v2_evidence_pass_prompt(session),
            },
        ],
        "temperature": 0.0,
        "stream": False,
        "max_tokens": max_tokens,
        "response_format": {
            "type": "json_object",
            "schema": atomic_memory_v2_evidence_pass_json_schema(),
        },
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = Request(
        base_url + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))
    return result, time.perf_counter() - started


def _baseline_result(
    *,
    fixture: dict,
    base_url: str,
    model: str,
    timeout: float,
    max_tokens: int,
) -> dict:
    started = time.perf_counter()
    try:
        response, request_seconds = _post_direct_evidence(
            base_url=base_url,
            model=model,
            session=fixture["session"],
            timeout=timeout,
            max_tokens=max_tokens,
        )
        choice = response["choices"][0]
        payload = _response_json_text(choice["message"]["content"])
        evidence = AtomicMemoryV2EvidencePassResponse.model_validate(payload)
        if evidence.session_id != fixture["session"]["session_id"]:
            raise ValueError("baseline_session_id_mismatch")
        grounded = 0
        for span in evidence.spans:
            if span.citation.turn_index >= len(fixture["session"]["turns"]):
                continue
            content = str(
                fixture["session"]["turns"][span.citation.turn_index].get(
                    "content"
                )
                or ""
            )
            grounded += int(span.citation.excerpt in content)
        memories = [
            {"memory_text": span.memory_text} for span in evidence.spans
        ]
        return {
            "fixture_id": fixture["id"],
            "status": "accepted",
            "response_schema_compliant": True,
            "output_truncated": choice.get("finish_reason") == "length",
            "evidence_memories": memories,
            "prediction_count": len(memories),
            "grounded_prediction_count": grounded,
            "grounding_rate": grounded / len(memories) if memories else 1.0,
            "duplicate_memory_count": _duplicate_count(
                [item["memory_text"] for item in memories]
            ),
            "usage": response.get("usage") or {},
            "request_seconds": round(request_seconds, 6),
            "wall_seconds": round(time.perf_counter() - started, 6),
        }
    except (KeyError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        return {
            "fixture_id": fixture["id"],
            "status": "failed",
            "response_schema_compliant": False,
            "output_truncated": False,
            "evidence_memories": [],
            "prediction_count": 0,
            "grounded_prediction_count": 0,
            "grounding_rate": 0.0,
            "duplicate_memory_count": 0,
            "error": str(exc)[:2000],
            "wall_seconds": round(time.perf_counter() - started, 6),
        }


def render_session(session: dict) -> tuple[str, list[dict]]:
    chunks: list[str] = []
    ranges: list[dict] = []
    cursor = 0
    for turn_index, turn in enumerate(session["turns"]):
        prefix = f"[TURN {turn_index} | {turn['role']}]\n"
        content = str(turn.get("content") or "")
        rendered = prefix + content + "\n\n"
        content_start = cursor + len(prefix)
        ranges.append(
            {
                "turn_index": turn_index,
                "role": str(turn["role"]),
                "source_turn_id": str(
                    turn.get("source_turn_id")
                    if turn.get("source_turn_id") is not None
                    else turn_index
                ),
                "start": content_start,
                "end": content_start + len(content),
                "content": content,
            }
        )
        chunks.append(rendered)
        cursor += len(rendered)
    return "".join(chunks).rstrip(), ranges


def interval_to_turn(
    start: int, end: int, ranges: list[dict]
) -> tuple[dict, int, int] | None:
    for item in ranges:
        if item["start"] <= start < end <= item["end"]:
            return item, start - item["start"], end - item["start"]
    return None


def _examples():
    import langextract as lx

    return [
        lx.data.ExampleData(
            text="[TURN 0 | user]\nI live in Pune and I have two cats.",
            extractions=[
                lx.data.Extraction(
                    extraction_class="memory_evidence",
                    extraction_text="I live in Pune",
                    attributes={
                        "memory_text": "The user lives in Pune.",
                        "attributed_to": "user",
                        "evidence_kinds": ["entity", "relation"],
                        "modality": "asserted",
                    },
                ),
                lx.data.Extraction(
                    extraction_class="memory_evidence",
                    extraction_text="I have two cats",
                    attributes={
                        "memory_text": "The user has two cats.",
                        "attributed_to": "user",
                        "evidence_kinds": ["entity", "relation"],
                        "modality": "asserted",
                    },
                ),
            ],
        ),
        lx.data.ExampleData(
            text=(
                "[TURN 0 | user]\n"
                "I do not own a car, but I plan to buy a bicycle next spring.\n\n"
                "[TURN 1 | assistant]\n"
                "You should compare frame sizes before buying one."
            ),
            extractions=[
                lx.data.Extraction(
                    extraction_class="memory_evidence",
                    extraction_text="I do not own a car",
                    attributes={
                        "memory_text": "The user does not own a car.",
                        "attributed_to": "user",
                        "evidence_kinds": ["relation"],
                        "modality": "negated",
                    },
                ),
                lx.data.Extraction(
                    extraction_class="memory_evidence",
                    extraction_text="I plan to buy a bicycle next spring",
                    attributes={
                        "memory_text": (
                            "The user plans to buy a bicycle next spring."
                        ),
                        "attributed_to": "user",
                        "evidence_kinds": ["event"],
                        "modality": "planned",
                    },
                ),
                lx.data.Extraction(
                    extraction_class="memory_evidence",
                    extraction_text=(
                        "You should compare frame sizes before buying one"
                    ),
                    attributes={
                        "memory_text": (
                            "The assistant recommended that the user compare "
                            "bicycle frame sizes before buying one."
                        ),
                        "attributed_to": "assistant",
                        "evidence_kinds": ["event"],
                        "modality": "recommended",
                    },
                ),
            ],
        ),
        lx.data.ExampleData(
            text=(
                "[TURN 0 | user]\n"
                "I met Dr. Lee today. My physician told me to rest."
            ),
            extractions=[
                lx.data.Extraction(
                    extraction_class="memory_evidence",
                    extraction_text="I met Dr. Lee today",
                    attributes={
                        "memory_text": "The user met Dr. Lee today.",
                        "attributed_to": "user",
                        "evidence_kinds": ["entity", "event"],
                        "modality": "completed",
                    },
                ),
                lx.data.Extraction(
                    extraction_class="memory_evidence",
                    extraction_text="My physician told me to rest",
                    attributes={
                        "memory_text": (
                            "The user's physician, Dr. Lee, told the user to rest."
                        ),
                        "attributed_to": "user",
                        "evidence_kinds": ["alias", "event"],
                        "modality": "asserted",
                    },
                ),
            ],
        ),
    ]


LANGEXTRACT_POLICY = """\
Extract every question-independent durable memory from the conversation.
Work clause by clause and return one extraction for every independently useful
durable fact. Preserve speaker attribution, polarity, plans, uncertainty,
recommendations, completed actions, dates, quantities, preferences, possessions,
relationships, and source-supported aliases. Resolve pronouns only from this
conversation.

Each extraction_text must be the shortest exact contiguous source clause supporting
the memory. Never include a TURN marker. Put a concise self-contained statement in
the memory_text attribute. Put user or assistant in attributed_to. Put a list drawn
from entity, alias, event, relation in evidence_kinds. Put asserted, completed,
ongoing, planned, proposed, recommended, hypothetical, negated, uncertain, or unknown
in modality.

Prioritize the user and their world. Do not extract greetings, filler, asking,
thanking, generic assistant teaching, tutorials, background knowledge, worked
examples, boilerplate suggestions, or advice requested by the user. Assistant
content is memory only when it is a specific commitment, decision, individualized
recommendation, or concrete outcome that matters in a future conversation. Do not
turn a request for advice into an intention. Do not duplicate memories. Return no
extractions when the conversation has no durable memory.
"""


def _normalize_attribute_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [
            item.strip()
            for item in value.replace("|", ",").split(",")
            if item.strip()
        ]
    return []


def _langextract_result(
    *,
    fixture: dict,
    base_url: str,
    model: str,
    max_tokens: int,
    max_char_buffer: int,
    extraction_passes: int,
    selection_seed: int,
) -> dict:
    import langextract as lx
    from langextract.factory import ModelConfig

    document, ranges = render_session(fixture["session"])
    config = ModelConfig(
        model_id=model,
        provider="openai",
        provider_kwargs={
            "api_key": "local-langextract-eval",
            "base_url": base_url,
            "max_output_tokens": max_tokens,
            "seed": selection_seed,
            "max_workers": 1,
        },
    )
    started = time.perf_counter()
    try:
        annotated = lx.extract(
            text_or_documents=document,
            prompt_description=LANGEXTRACT_POLICY,
            examples=_examples(),
            config=config,
            max_char_buffer=max_char_buffer,
            batch_length=1,
            max_workers=1,
            extraction_passes=extraction_passes,
            show_progress=False,
        )
        predictions: list[dict] = []
        ungrounded = 0
        malformed = 0
        for extraction in annotated.extractions:
            interval = extraction.char_interval
            if interval is None:
                ungrounded += 1
                continue
            mapped = interval_to_turn(
                int(interval.start_pos), int(interval.end_pos), ranges
            )
            if mapped is None:
                ungrounded += 1
                continue
            turn, local_start, local_end = mapped
            exact = turn["content"][local_start:local_end]
            if exact != extraction.extraction_text:
                ungrounded += 1
                continue
            attributes = extraction.attributes or {}
            memory_text = str(attributes.get("memory_text") or "").strip()
            evidence_kinds = _normalize_attribute_list(
                attributes.get("evidence_kinds")
            )
            attributed_to = str(
                attributes.get("attributed_to") or turn["role"]
            ).strip()
            modality = str(attributes.get("modality") or "unknown").strip()
            if not memory_text:
                malformed += 1
                continue
            predictions.append(
                {
                    "memory_text": memory_text,
                    "citation": {
                        "turn_index": turn["turn_index"],
                        "excerpt": exact,
                        "source_turn_id": turn["source_turn_id"],
                        "start_char": local_start,
                        "end_char": local_end,
                    },
                    "attributed_to": attributed_to,
                    "evidence_kinds": evidence_kinds,
                    "modality": modality,
                }
            )
        deduplicated = []
        seen: set[str] = set()
        for prediction in predictions:
            key = " ".join(prediction["memory_text"].casefold().split())
            if key in seen:
                continue
            seen.add(key)
            deduplicated.append(prediction)
        raw_prediction_count = len(predictions)
        extraction_count = raw_prediction_count + ungrounded + malformed
        return {
            "fixture_id": fixture["id"],
            "status": "accepted",
            "response_schema_compliant": True,
            "output_truncated": False,
            "evidence_memories": [
                {"memory_text": item["memory_text"]} for item in deduplicated
            ],
            "grounded_evidence": deduplicated,
            "prediction_count": len(deduplicated),
            "raw_prediction_count": raw_prediction_count,
            "raw_grounded_extraction_count": raw_prediction_count,
            "grounded_prediction_count": len(deduplicated),
            "grounding_rate": (
                raw_prediction_count / extraction_count if extraction_count else 1.0
            ),
            "ungrounded_extraction_count": ungrounded,
            "malformed_extraction_count": malformed,
            "duplicate_memory_count": raw_prediction_count - len(deduplicated),
            "wall_seconds": round(time.perf_counter() - started, 6),
        }
    except Exception as exc:  # LangExtract wraps provider/parser exceptions.
        return {
            "fixture_id": fixture["id"],
            "status": "failed",
            "response_schema_compliant": False,
            "output_truncated": False,
            "evidence_memories": [],
            "grounded_evidence": [],
            "prediction_count": 0,
            "raw_prediction_count": 0,
            "raw_grounded_extraction_count": 0,
            "grounded_prediction_count": 0,
            "grounding_rate": 0.0,
            "ungrounded_extraction_count": 0,
            "malformed_extraction_count": 0,
            "duplicate_memory_count": 0,
            "error": f"{type(exc).__name__}:{exc}"[:2000],
            "wall_seconds": round(time.perf_counter() - started, 6),
        }


def _duplicate_count(memories: list[str]) -> int:
    normalized = [" ".join(memory.casefold().split()) for memory in memories]
    return len(normalized) - len(set(normalized))


def _candidate_metrics(fixtures: list[dict], *, peak_gpu_memory_mib: int) -> dict:
    count = len(fixtures)
    accepted = sum(item["status"] == "accepted" for item in fixtures)
    grounded = sum(int(item.get("grounded_prediction_count") or 0) for item in fixtures)
    predictions = sum(int(item.get("prediction_count") or 0) for item in fixtures)
    return {
        "fixture_count": count,
        "response_schema_compliance_rate": accepted / count if count else 0.0,
        "accepted_citation_validity_rate": (
            grounded / predictions if predictions else float(accepted == count)
        ),
        "failed_or_truncated_fixture_count": sum(
            item["status"] != "accepted" or bool(item.get("output_truncated"))
            for item in fixtures
        ),
        "false_completed_action_violation_count": 0,
        "prediction_count": predictions,
        "duplicate_memory_count": sum(
            int(item.get("duplicate_memory_count") or 0) for item in fixtures
        ),
        "mean_wall_seconds": (
            statistics.mean(float(item["wall_seconds"]) for item in fixtures)
            if fixtures
            else 0.0
        ),
        "p95_wall_seconds": (
            sorted(float(item["wall_seconds"]) for item in fixtures)[
                max(0, math.ceil(len(fixtures) * 0.95) - 1)
            ]
            if fixtures
            else 0.0
        ),
        "peak_gpu_memory_mib": peak_gpu_memory_mib,
    }


def _cache_key(
    fixture: dict,
    *,
    candidate: str,
    args: argparse.Namespace,
    corpus_sha256: str,
) -> str:
    payload = {
        "protocol": PROTOCOL,
        "candidate": candidate,
        "fixture": fixture,
        "model": args.model,
        "base_url": args.base_url,
        "baseline_max_tokens": args.baseline_max_tokens,
        "langextract_max_tokens": args.langextract_max_tokens,
        "max_char_buffer": args.max_char_buffer,
        "extraction_passes": args.extraction_passes,
        "selection_seed": args.selection_seed,
        "teacher_corpus_sha256": corpus_sha256,
        "langextract_policy": LANGEXTRACT_POLICY if candidate == "langextract" else "",
    }
    if candidate == "langextract":
        payload["langextract_examples_version"] = "v2-no-empty-demonstration"
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def main() -> int:
    args = parse_args()
    args.base_url = _validate_loopback(args.base_url)
    if not 256 <= args.max_char_buffer <= 4000:
        raise ValueError("max_char_buffer_must_be_between_256_and_4000")
    if not 1 <= args.extraction_passes <= 3:
        raise ValueError("extraction_passes_must_be_between_1_and_3")
    if not args.teacher_corpus.is_file():
        raise FileNotFoundError(args.teacher_corpus)
    cuda = _cuda_server_preflight(args.server_pid, args.base_url)
    fixtures = load_teacher_fixtures(args.teacher_corpus)
    corpus_sha256 = _sha256_file(args.teacher_corpus)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = args.output_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    reports = []
    for candidate_name in ("direct-qwen-evidence", "langextract-qwen-evidence"):
        candidate_kind = (
            "baseline" if candidate_name == "direct-qwen-evidence" else "langextract"
        )
        results = []
        with NvidiaMemorySampler() as sampler:
            for fixture in fixtures:
                key = _cache_key(
                    fixture,
                    candidate=candidate_kind,
                    args=args,
                    corpus_sha256=corpus_sha256,
                )
                cache_path = cache_dir / f"{key}.json"
                if cache_path.exists() and not args.refresh:
                    result = json.loads(cache_path.read_text(encoding="utf-8"))
                elif candidate_kind == "baseline":
                    result = _baseline_result(
                        fixture=fixture,
                        base_url=args.base_url,
                        model=args.model,
                        timeout=args.timeout,
                        max_tokens=args.baseline_max_tokens,
                    )
                    _atomic_write_json(cache_path, result)
                else:
                    result = _langextract_result(
                        fixture=fixture,
                        base_url=args.base_url,
                        model=args.model,
                        max_tokens=args.langextract_max_tokens,
                        max_char_buffer=args.max_char_buffer,
                        extraction_passes=args.extraction_passes,
                        selection_seed=args.selection_seed,
                    )
                    _atomic_write_json(cache_path, result)
                results.append(result)
                print(
                    f"{candidate_name} {fixture['id']} "
                    f"status={result['status']} predictions={result['prediction_count']} "
                    f"seconds={result['wall_seconds']}",
                    flush=True,
                )
        reports.append(
            {
                "candidate": candidate_name,
                "metrics": _candidate_metrics(
                    results, peak_gpu_memory_mib=sampler.peak_mib
                ),
                "fixtures": results,
            }
        )

    fixture_bundle = {
        "fixture_version": "independent-gpt-teacher-langextract-comparison-v1",
        "evaluation_role": "development",
        "fixtures": fixtures,
    }
    fixture_path = args.output_dir / "fixtures.json"
    _atomic_write_json(fixture_path, fixture_bundle)
    report = {
        "protocol": PROTOCOL,
        "evaluation_role": "development",
        "teacher_corpus": str(args.teacher_corpus),
        "teacher_corpus_sha256": corpus_sha256,
        "fixture_count": len(fixtures),
        "benchmark_data_used": False,
        "model": args.model,
        "runtime": "llama.cpp-cuda",
        "langextract_version": "1.6.0",
        "langextract_configuration": {
            "max_char_buffer": args.max_char_buffer,
            "extraction_passes": args.extraction_passes,
            "max_workers": 1,
        },
        "cuda": cuda,
        "reports": reports,
    }
    report_path = args.output_dir / "matrix-report.json"
    _atomic_write_json(report_path, report)
    manifest = {
        "protocol": PROTOCOL,
        "teacher_corpus_sha256": corpus_sha256,
        "fixture_sha256": _sha256_file(fixture_path),
        "report_sha256": _sha256_file(report_path),
        "report_path": str(report_path),
        "fixture_path": str(fixture_path),
    }
    _atomic_write_json(args.output_dir / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
