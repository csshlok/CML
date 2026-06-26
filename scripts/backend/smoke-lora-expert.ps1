param(
  [string]$ReportPath = ".tmp/lora-expert-smoke-report.json",
  [switch]$AllowTestTrainer,
  [string[]]$SourcePaths = @("docs/PROJECT_CONTEXT.md", "docs/OVERALL_CONTEXT.md"),
  [string]$BaseModelPath = $env:CML_LORA_BASE_MODEL_PATH,
  [int]$ExpectedSourceCount = 0,
  [int]$MaxRealSources = 12,
  [int]$BenchmarkCaseLimit = 8,
  [switch]$AllowBenchmarkFailure,
  [int]$RuntimeMaxNewTokens = 48,
  [int]$BenchmarkMaxNewTokens = 0,
  [string]$WorkDir = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}

if (-not $AllowTestTrainer -and -not $env:CML_LORA_TRAINER_COMMAND) {
  throw "CML_LORA_TRAINER_COMMAND is required for real LoRA smoke. Use -AllowTestTrainer only for CI scaffold validation."
}
if (-not $AllowTestTrainer -and -not $BaseModelPath -and -not $env:CML_LLM_MODEL) {
  throw "A real local Transformers base model is required. Pass -BaseModelPath or set CML_LORA_BASE_MODEL_PATH/CML_LLM_MODEL."
}

$reportFullPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $ReportPath))
$reportDir = Split-Path -Parent $reportFullPath
if ($reportDir) {
  New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
}

$resolvedSources = @()
foreach ($sourcePath in $SourcePaths) {
  $candidate = Join-Path $repoRoot $sourcePath
  if (Test-Path $candidate) {
    $resolvedSources += [System.IO.Path]::GetFullPath($candidate)
  } elseif (Test-Path $sourcePath) {
    $resolvedSources += [System.IO.Path]::GetFullPath($sourcePath)
  } elseif (-not $AllowTestTrainer) {
    throw "Real LoRA source path not found: $sourcePath"
  }
}

$env:CML_ALLOW_LORA_TEST_TRAINER = if ($AllowTestTrainer) { "1" } else { "0" }
$env:CML_ALLOW_HASH_EMBEDDINGS = "1"
$env:CML_EMBEDDING_PROVIDER = "hash"
$env:REPORT_PATH = $reportFullPath
$env:CML_LORA_SMOKE_SOURCE_PATHS_JSON = ConvertTo-Json @($resolvedSources) -Compress
$env:CML_LORA_SMOKE_BASE_MODEL_PATH = $BaseModelPath
$env:CML_LORA_SMOKE_ALLOW_BENCHMARK_FAILURE = if ($AllowBenchmarkFailure) { "1" } else { "0" }
$env:CML_LORA_SMOKE_MAX_REAL_SOURCES = [string]$MaxRealSources
$env:CML_LORA_SMOKE_EXPECTED_SOURCE_COUNT = [string]$ExpectedSourceCount
$env:CML_LORA_SMOKE_BENCHMARK_CASE_LIMIT = [string]$BenchmarkCaseLimit
$env:CML_LORA_BENCHMARK_CASE_LIMIT = [string]$BenchmarkCaseLimit
$env:CML_LORA_SMOKE_RUNTIME_MAX_NEW_TOKENS = [string]$RuntimeMaxNewTokens
$env:CML_LORA_SMOKE_BENCHMARK_MAX_NEW_TOKENS = [string]$BenchmarkMaxNewTokens
if (-not $AllowTestTrainer) {
  if (-not $WorkDir) {
    $WorkDir = ".tmp/lora-real-smoke-work"
  }
  if ([System.IO.Path]::IsPathRooted($WorkDir)) {
    $workFullPath = [System.IO.Path]::GetFullPath($WorkDir)
  } else {
    $workFullPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $WorkDir))
  }
  $env:CML_LORA_SMOKE_WORK_DIR = $workFullPath
} else {
  $env:CML_LORA_SMOKE_WORK_DIR = ""
}

$pythonScript = @'
import json
import importlib.util
import os
import re
import shutil
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from backend.app.core.config import get_settings

repo_report = Path(os.environ.get("REPORT_PATH", ".tmp/lora-expert-smoke-report.json"))
persisted_work_dir = os.environ.get("CML_LORA_SMOKE_WORK_DIR") or ""
if persisted_work_dir:
    work_path = Path(persisted_work_dir)
    if work_path.exists():
        shutil.rmtree(work_path)
    work_path.mkdir(parents=True, exist_ok=True)
    work = None
    work_name = str(work_path)
else:
    work = tempfile.TemporaryDirectory()
    work_name = work.name
os.environ["CML_DATA_DIR"] = work_name
os.environ["CML_DATABASE_PATH"] = str(Path(work_name) / "smoke.sqlite3")
if os.environ.get("CML_ALLOW_LORA_TEST_TRAINER") == "1":
    model_root = Path(work_name) / "models"
    model_dir = model_root / "smoke-base-model"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "config.json").write_text('{"model_type":"llama"}', encoding="utf-8")
    (model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
    os.environ["CML_LORA_MODEL_DIRS"] = str(model_root)
    os.environ["CML_LLM_MODEL"] = "smoke-base-model"
else:
    base_model_path = os.environ.get("CML_LORA_SMOKE_BASE_MODEL_PATH") or ""
    if base_model_path:
        resolved_base_model = str(Path(base_model_path).resolve())
        os.environ["CML_LLM_MODEL"] = resolved_base_model
        os.environ["CML_LORA_MODEL_DIRS"] = str(Path(resolved_base_model).parent)
get_settings.cache_clear()

from backend.app.api.routes.clusters import get_expert_status, list_expert_artifacts, queue_expert_retrain
from backend.app.api.routes.sources import create_source
from backend.app.core.background_jobs import job_queue_status, run_due_jobs_once
from backend.app.core.database import connect, init_db, utc_now
from backend.app.core.expert_evaluation import (
    build_expert_evaluation_plan,
    default_expert_benchmark_token_budgets,
    run_live_expert_benchmark,
)
from backend.app.core.expert_runtime import run_adapter_runtime_smoke
from backend.app.core.hardware import hardware_status as actual_hardware_status
from backend.app.core.lora_training import trainer_dependency_status
from backend.app.core.model_registry import model_compatibility_report
from backend.app.core.training_dataset import build_cluster_dataset
from backend.app.schemas import SourceCreate

allow_test_trainer = os.environ.get("CML_ALLOW_LORA_TEST_TRAINER") == "1"
allow_benchmark_failure = os.environ.get("CML_LORA_SMOKE_ALLOW_BENCHMARK_FAILURE") == "1"
max_real_sources = int(os.environ.get("CML_LORA_SMOKE_MAX_REAL_SOURCES") or "12")
expected_source_count = int(os.environ.get("CML_LORA_SMOKE_EXPECTED_SOURCE_COUNT") or "0")
benchmark_case_limit = int(os.environ.get("CML_LORA_SMOKE_BENCHMARK_CASE_LIMIT") or "6")
runtime_max_new_tokens = int(os.environ.get("CML_LORA_SMOKE_RUNTIME_MAX_NEW_TOKENS") or "16")
benchmark_max_new_tokens = int(os.environ.get("CML_LORA_SMOKE_BENCHMARK_MAX_NEW_TOKENS") or "0")
source_paths = json.loads(os.environ.get("CML_LORA_SMOKE_SOURCE_PATHS_JSON") or "[]")
base_model_path = os.environ.get("CML_LORA_SMOKE_BASE_MODEL_PATH") or ""


def _real_source_records(paths: list[Path], *, limit: int) -> list[dict]:
    candidates: list[Path] = []
    for path in paths:
        if path.is_dir():
            for child in path.rglob("*"):
                if _should_use_source_file(child):
                    candidates.append(child)
        elif _should_use_source_file(path):
            candidates.append(path)
    records: list[dict] = []
    for path in candidates:
        text = _read_source_text(path)
        if not text.strip():
            continue
        for section in _split_real_text(path, text):
            records.append(section)
            if len(records) >= limit:
                return records
    return records


def _should_use_source_file(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    ignored = {".git", ".venv", "node_modules", "data", ".tmp", "apps/desktop/release"}
    normalized_parts = {part.lower() for part in path.parts}
    if any(part in normalized_parts for part in ignored):
        return False
    if path.name.lower() == "manifest.json":
        return False
    return path.suffix.lower() in {".md", ".txt", ".py", ".ps1", ".js", ".ts", ".tsx", ".json", ".pdf"}


def _read_source_text(path: Path) -> str:
    if path.suffix.lower() != ".pdf":
        return path.read_text(encoding="utf-8", errors="replace")
    if importlib.util.find_spec("pypdf") is None:
        return ""
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception:
        return ""


def _split_real_text(path: Path, text: str) -> list[dict]:
    sections: list[tuple[str, str]] = []
    title = path.name
    buffer: list[str] = []
    for line in text.splitlines():
        if re.match(r"^#{1,3}\s+\S", line) and buffer:
            sections.append((title, "\n".join(buffer).strip()))
            title = line.lstrip("#").strip() or path.name
            buffer = []
        else:
            if re.match(r"^#{1,3}\s+\S", line):
                title = line.lstrip("#").strip() or path.name
            buffer.append(line)
    if buffer:
        sections.append((title, "\n".join(buffer).strip()))
    rows: list[dict] = []
    for section_title, section_text in sections:
        if len(section_text.strip()) < 400:
            continue
        for chunk_index, chunk in enumerate(_chunk_text(section_text, size=12000)):
            clean = " ".join(chunk.split())
            rows.append(
                {
                    "title": f"{path.name} - {section_title}" + (f" part {chunk_index + 1}" if chunk_index else ""),
                    "path": str(path),
                    "text": chunk,
                    "summary": clean[:700],
                }
            )
    if rows:
        return rows
    clean = " ".join(text.split())
    return [{"title": path.name, "path": str(path), "text": text, "summary": clean[:700]}] if clean else []


def _chunk_text(text: str, *, size: int) -> list[str]:
    chunks = []
    remaining = text
    while len(remaining) > size:
        split_at = remaining.rfind("\n", 0, size)
        if split_at < size // 2:
            split_at = size
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip()
    if remaining.strip():
        chunks.append(remaining)
    return chunks


init_db()
now = utc_now()
with connect() as conn:
    conn.execute(
        "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("vault-smoke", "LoRA real smoke vault", work_name, now, now),
    )
    conn.execute(
        """
        INSERT INTO clusters (id, vault_id, name, description, color, expert_status, created_at, updated_at)
        VALUES ('cluster-smoke', 'vault-smoke', 'LoRA Real Smoke', 'Real local corpus LoRA smoke cluster', 'sage', 'retrieval_ready', ?, ?)
        """,
        (now, now),
    )

source_records = []
if allow_test_trainer:
    for index in range(3):
        source_records.append(
            {
                "title": f"LoRA smoke source {index + 1}",
                "text": (f"lora smoke adapter evidence source {index + 1} strict evaluation retrieval baseline " * 240),
                "summary": f"LoRA smoke source {index + 1} contains strict adapter training and evaluation evidence.",
                "path": "",
            }
        )
else:
    source_records = _real_source_records([Path(item) for item in source_paths], limit=max_real_sources)
    if not source_records:
        raise SystemExit("No real source records were found for LoRA smoke.")
    if expected_source_count > 0 and len(source_records) != expected_source_count:
        raise SystemExit(
            f"Expected {expected_source_count} source records for LoRA smoke, "
            f"but only collected {len(source_records)}. Refusing to start training."
        )

for item in source_records:
    create_source(
        SourceCreate(
            vault_id="vault-smoke",
            cluster_id="cluster-smoke",
            title=item["title"],
            source_type="note",
            raw_text=item["text"],
            summary=item["summary"],
        )
    )

actual_hardware = actual_hardware_status()
hardware_override = dict(actual_hardware)
if allow_test_trainer:
    hardware_override = {"training_supported": True, "hardware_tier": "smoke", "detail": "smoke hardware override"}
elif actual_hardware.get("training_supported") is not True and actual_hardware.get("avx2") is not False:
    hardware_override["training_supported"] = True
    hardware_override["detail"] = (
        str(actual_hardware.get("detail") or "")
        + " Guarded real smoke override used because AVX2 could not be verified by this environment."
    ).strip()

preferred_model = None
model_compatibility = None
if allow_test_trainer:
    preferred_model = {
        "id": "smoke-base-model",
        "name": "Smoke base model",
        "family": "smoke",
        "local_path": str(Path(os.environ["CML_LORA_MODEL_DIRS"]) / "smoke-base-model"),
        "compatibility": {"accepted": True, "expert_role_accepted": True},
        "source_kind": "smoke",
    }
elif base_model_path:
    model_compatibility = model_compatibility_report(base_model_path)
    hardware_probe = dict(model_compatibility.get("hardware") or {})
    compatibility_reasons = [str(item) for item in (model_compatibility.get("reasons") or []) if str(item).strip()]
    hardware_unknown_only = (
        bool(compatibility_reasons)
        and all("hardware tier does not satisfy the minimum contract" in reason.lower() for reason in compatibility_reasons)
        and hardware_probe.get("training_supported") is True
        and hardware_probe.get("avx2") is not False
        and str(hardware_probe.get("hardware_tier") or "").strip().lower() == "unknown"
    )
    if not model_compatibility.get("accepted") and not hardware_unknown_only:
        raise SystemExit("Base model was rejected by CML compatibility checks: " + model_compatibility.get("detail", ""))
    preferred_model = {
        "id": Path(base_model_path).name,
        "name": Path(base_model_path).name,
        "family": model_compatibility.get("family") or "",
        "local_path": str(Path(base_model_path).resolve()),
        "compatibility": model_compatibility,
        "source_kind": "smoke_explicit_path",
    }

patches = [
    patch("backend.app.core.expert_lifecycle.hardware_status", return_value=hardware_override),
    patch("backend.app.core.hardware.hardware_status", return_value=hardware_override),
]
if preferred_model is not None:
    patches.append(patch("backend.app.core.background_jobs.preferred_expert_base_model", return_value=preferred_model))

with ExitStack() as stack:
    for item in patches:
        stack.enter_context(item)
    expert_job = queue_expert_retrain("cluster-smoke")
    processed_passes = []
    for _ in range(80):
        processed = run_due_jobs_once(limit=5)
        processed_passes.append(processed)
        if processed == 0:
            break

dataset = build_cluster_dataset("cluster-smoke")
plan = build_expert_evaluation_plan(dataset, max_cases=max(1, benchmark_case_limit))
artifacts = list_expert_artifacts("cluster-smoke")
status = get_expert_status("cluster-smoke")
runtime_smoke = None
benchmark_report = None
live_runtime_batch = None
if artifacts:
    active = next((item for item in artifacts if item.get("active")), artifacts[0])
    runtime_smoke = run_adapter_runtime_smoke(
        adapter_path=active["local_path"],
        base_model=str(active["base_model"]),
        prompt="Using the local CML project context, name the public V1 release stance in one short sentence.",
        max_new_tokens=runtime_max_new_tokens,
    )
    if runtime_smoke.get("ok"):
        benchmark_run = run_live_expert_benchmark(
            dataset,
            adapter_path=active["local_path"],
            base_model=str(active["base_model"]),
            max_new_tokens=(benchmark_max_new_tokens if benchmark_max_new_tokens > 0 else None),
            max_new_tokens_by_category=(None if benchmark_max_new_tokens > 0 else default_expert_benchmark_token_budgets()),
            mode="ci_scaffold_non_release_benchmark" if allow_test_trainer else "live_adapter_benchmark",
            evaluation_plan=plan,
        )
        live_runtime_batch = benchmark_run.get("runtime")
        benchmark_report = benchmark_run.get("benchmark_report")
    else:
        benchmark_report = {"status": "runtime_failed", "passes": False, "live_adapter_backed": True}
else:
    benchmark_report = {"status": "no_adapter_artifact", "passes": False, "live_adapter_backed": False}

report = {
    "mode": "ci_scaffold_non_release" if allow_test_trainer else "real_local_lora_smoke",
    "used_synthetic_sources": bool(allow_test_trainer),
    "work_dir": work_name,
    "real_source_paths": [str(item) for item in source_paths],
    "source_records": [
        {"title": item["title"], "path": item.get("path") or "", "chars": len(item["text"])}
        for item in source_records
    ],
    "base_model_path": str(Path(base_model_path).resolve()) if base_model_path else "",
    "model_compatibility": model_compatibility,
    "trainer_dependency_status": trainer_dependency_status(),
    "actual_hardware_status": actual_hardware,
    "hardware_status_used": hardware_override,
    "processed_job_passes": processed_passes,
    "processed_jobs_total": sum(processed_passes),
    "job_queue_status": job_queue_status(),
    "expert_job": expert_job,
    "artifact_count": len(artifacts),
    "artifacts": artifacts,
    "expert_status": status,
    "dataset": {
        "source_count": dataset.get("source_count"),
        "unique_content_hash_count": dataset.get("unique_content_hash_count"),
        "estimated_token_count": dataset.get("estimated_token_count"),
        "dataset_hash": dataset.get("dataset_hash"),
    },
    "evaluation_plan": {"case_count": plan["case_count"], "categories": plan["categories"]},
    "runtime_limits": {
        "runtime_max_new_tokens": runtime_max_new_tokens,
        "benchmark_max_new_tokens": benchmark_max_new_tokens,
    },
    "runtime_smoke": runtime_smoke,
    "live_runtime_batch": live_runtime_batch,
    "benchmark_report": benchmark_report,
}
repo_report.write_text(json.dumps(report, indent=2), encoding="utf-8")

if not artifacts or not status["searchable"]:
    raise SystemExit(1)
if not runtime_smoke or not runtime_smoke.get("ok"):
    raise SystemExit(1)
if not allow_test_trainer:
    if not benchmark_report or not benchmark_report.get("passes"):
        if allow_benchmark_failure:
            raise SystemExit(0)
        raise SystemExit(2)
'@

$pythonScript | & $python -
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

Write-Host "LoRA expert smoke report written to $reportFullPath"
