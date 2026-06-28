param(
  [Parameter(Mandatory = $true)]
  [string]$AdapterPath,
  [Parameter(Mandatory = $true)]
  [string]$BaseModel,
  [string]$WrongAdapterPath = "",
  [string]$WrongAdapterBaseModel = "",
  [string[]]$SourcePaths = @("docs/PROJECT_CONTEXT.md", "docs/OVERALL_CONTEXT.md"),
  [string]$ReportPath = ".tmp/lora-adapter-quality-benchmark.json",
  [int]$MaxRealSources = 12,
  [int]$BenchmarkCaseLimit = 8,
  [int]$BenchmarkMaxNewTokens = 0
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}

$adapterCandidate = if ([System.IO.Path]::IsPathRooted($AdapterPath)) { $AdapterPath } else { Join-Path $repoRoot $AdapterPath }
$baseModelCandidate = if ([System.IO.Path]::IsPathRooted($BaseModel)) { $BaseModel } else { Join-Path $repoRoot $BaseModel }
$reportCandidate = if ([System.IO.Path]::IsPathRooted($ReportPath)) { $ReportPath } else { Join-Path $repoRoot $ReportPath }
$adapterFullPath = [System.IO.Path]::GetFullPath($adapterCandidate)
$baseModelFullPath = [System.IO.Path]::GetFullPath($baseModelCandidate)
$wrongAdapterFullPath = if ($WrongAdapterPath) {
  $wrongAdapterCandidate = if ([System.IO.Path]::IsPathRooted($WrongAdapterPath)) { $WrongAdapterPath } else { Join-Path $repoRoot $WrongAdapterPath }
  [System.IO.Path]::GetFullPath($wrongAdapterCandidate)
} else { "" }
$wrongAdapterBaseModelFullPath = if ($WrongAdapterBaseModel) {
  $wrongBaseCandidate = if ([System.IO.Path]::IsPathRooted($WrongAdapterBaseModel)) { $WrongAdapterBaseModel } else { Join-Path $repoRoot $WrongAdapterBaseModel }
  [System.IO.Path]::GetFullPath($wrongBaseCandidate)
} else { "" }
if ($wrongAdapterFullPath -and $wrongAdapterFullPath -eq $adapterFullPath) {
  throw "WrongAdapterPath must be different from AdapterPath."
}
$reportFullPath = [System.IO.Path]::GetFullPath($reportCandidate)
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
  } else {
    throw "LoRA benchmark source path not found: $sourcePath"
  }
}

$env:CML_LORA_BENCH_ADAPTER_PATH = $adapterFullPath
$env:CML_LORA_BENCH_BASE_MODEL = $baseModelFullPath
$env:CML_LORA_BENCH_WRONG_ADAPTER_PATH = $wrongAdapterFullPath
$env:CML_LORA_BENCH_WRONG_ADAPTER_BASE_MODEL = $wrongAdapterBaseModelFullPath
$env:CML_LORA_BENCH_SOURCE_PATHS_JSON = ConvertTo-Json @($resolvedSources) -Compress
$env:CML_LORA_BENCH_REPORT_PATH = $reportFullPath
$env:CML_LORA_BENCH_MAX_REAL_SOURCES = [string]$MaxRealSources
$env:CML_LORA_BENCH_CASE_LIMIT = [string]$BenchmarkCaseLimit
$env:CML_LORA_BENCH_MAX_NEW_TOKENS = [string]$BenchmarkMaxNewTokens

$pythonScript = @'
import json
import importlib.util
import os
import re
from pathlib import Path

from backend.app.core.embeddings import content_hash
from backend.app.core.expert_evaluation import (
    build_heldout_bundle_evaluation_dataset,
    build_expert_evaluation_plan,
    default_expert_benchmark_token_budgets,
    run_live_expert_benchmark,
)
from backend.app.core.expert_runtime import runtime_adapter_load_plan
from backend.app.core.hardware import hardware_status


def real_source_records(paths: list[Path], *, limit: int) -> list[dict]:
    candidates: list[Path] = []
    for path in paths:
        if path.is_dir():
            for child in path.rglob("*"):
                if should_use_source_file(child):
                    candidates.append(child)
        elif should_use_source_file(path):
            candidates.append(path)
    records: list[dict] = []
    for path in candidates:
        text = read_source_text(path)
        if not text.strip():
            continue
        for section in split_real_text(path, text):
            records.append(section)
            if len(records) >= limit:
                return records
    return records


def should_use_source_file(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    ignored = {".git", ".venv", "node_modules", "data", ".tmp", "apps/desktop/release"}
    normalized_parts = {part.lower() for part in path.parts}
    if any(part in normalized_parts for part in ignored):
        return False
    if path.name.lower() == "manifest.json":
        return False
    return path.suffix.lower() in {".md", ".txt", ".py", ".ps1", ".js", ".ts", ".tsx", ".json", ".pdf"}


def read_source_text(path: Path) -> str:
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


def split_real_text(path: Path, text: str) -> list[dict]:
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
        clean = " ".join(section_text.split())
        rows.append(
            {
                "title": f"{path.name} - {section_title}",
                "path": str(path),
                "text": section_text,
                "summary": clean[:700],
            }
        )
    return rows


def adapter_training_dataset(adapter_path: Path) -> dict:
    manifest_path = adapter_path / "dataset" / "dataset-manifest.json"
    training_config_path = adapter_path / "training-config.json"
    manifest: dict = {}
    training_config: dict = {}
    if manifest_path.exists():
        try:
            parsed_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            parsed_manifest = {}
        if isinstance(parsed_manifest, dict):
            manifest = parsed_manifest
    if training_config_path.exists():
        try:
            parsed_config = json.loads(training_config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            parsed_config = {}
        if isinstance(parsed_config, dict):
            training_config = parsed_config
    dataset_hash = str(manifest.get("dataset_hash") or training_config.get("dataset_hash") or "")
    return {
        "manifest_path": str(manifest_path) if manifest_path.exists() else "",
        "training_config_path": str(training_config_path) if training_config_path.exists() else "",
        "dataset_hash": dataset_hash,
        "source_count": int(manifest.get("source_count") or 0),
        "train_count": int(manifest.get("train_count") or 0),
        "validation_count": int(manifest.get("validation_count") or 0),
    }


adapter_path = Path(os.environ["CML_LORA_BENCH_ADAPTER_PATH"])
base_model = os.environ["CML_LORA_BENCH_BASE_MODEL"]
wrong_adapter_path = os.environ.get("CML_LORA_BENCH_WRONG_ADAPTER_PATH") or ""
wrong_adapter_base_model = os.environ.get("CML_LORA_BENCH_WRONG_ADAPTER_BASE_MODEL") or ""
source_paths = [Path(item) for item in json.loads(os.environ["CML_LORA_BENCH_SOURCE_PATHS_JSON"])]
report_path = Path(os.environ["CML_LORA_BENCH_REPORT_PATH"])
max_real_sources = int(os.environ.get("CML_LORA_BENCH_MAX_REAL_SOURCES") or "12")
case_limit = int(os.environ.get("CML_LORA_BENCH_CASE_LIMIT") or "6")
max_new_tokens = int(os.environ.get("CML_LORA_BENCH_MAX_NEW_TOKENS") or "0")

adapter_dataset = adapter_training_dataset(adapter_path)
adapter_dataset_hash = adapter_dataset.get("dataset_hash") or ""
heldout_dataset = build_heldout_bundle_evaluation_dataset(
    adapter_path / "dataset",
    cluster_id="cluster-smoke",
    max_cases=max(1, case_limit),
)
if heldout_dataset is not None:
    dataset = heldout_dataset
    source_records = [
        {
            "title": str(item.get("title") or "Untitled"),
            "path": str((adapter_path / "dataset" / "validation-sources.jsonl")),
            "chars": len(str(item.get("text") or "")),
        }
        for item in list(dataset.get("documents") or [])[:max_real_sources]
    ]
else:
    source_records = real_source_records(source_paths, limit=max_real_sources)
    if not source_records:
        raise SystemExit("No real source records were found for LoRA adapter benchmark.")
    documents = [
        {
            "source_id": f"source-{index + 1}",
            "title": item["title"],
            "summary": item["summary"],
            "text": item["text"],
            "content_hash": content_hash(item["text"]),
        }
        for index, item in enumerate(source_records)
    ]
    dataset = {
        "cluster_id": "cluster-smoke",
        "dataset_hash": content_hash("\n".join(f"{doc['source_id']}:{doc['content_hash']}" for doc in documents)),
        "documents": documents,
    }
plan = build_expert_evaluation_plan(dataset, max_cases=max(1, case_limit))
if plan.get("dataset_hash"):
    dataset["dataset_hash"] = str(plan["dataset_hash"])
dataset_matches_adapter = bool(adapter_dataset_hash and adapter_dataset_hash == dataset["dataset_hash"])
load_plan = runtime_adapter_load_plan(adapter_path=adapter_path, base_model=base_model)
if not load_plan.get("available"):
    report_path.write_text(
        json.dumps(
            {
                "status": "runtime_unavailable",
                "passes": False,
                "adapter_load_plan": load_plan,
                "hardware_status": hardware_status(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    raise SystemExit("Adapter runtime load plan is not available.")

benchmark_run = run_live_expert_benchmark(
    dataset,
    adapter_path=str(adapter_path),
    base_model=base_model,
    wrong_adapter_path=(wrong_adapter_path or None),
    wrong_adapter_base_model=(wrong_adapter_base_model or None),
    max_new_tokens=(max_new_tokens if max_new_tokens > 0 else None),
    max_new_tokens_by_category=(None if max_new_tokens > 0 else default_expert_benchmark_token_budgets()),
    evaluation_plan=plan,
)
runtime = benchmark_run.get("runtime") or {}
if not runtime.get("ok"):
    report_path.write_text(
        json.dumps(
            {
                "status": "runtime_failed",
                "passes": False,
                "adapter_load_plan": load_plan,
                "runtime": runtime,
                "hardware_status": hardware_status(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    raise SystemExit(runtime.get("error") or "Adapter runtime benchmark failed.")

adapter_case_scores = list(benchmark_run.get("adapter_case_scores") or [])
baseline_case_scores = list(benchmark_run.get("retrieval_case_scores") or [])
retrieval_small_case_scores = list(benchmark_run.get("retrieval_small_case_scores") or [])
wrong_adapter_case_scores = list(benchmark_run.get("wrong_adapter_case_scores") or [])
mode_case_outputs = dict((benchmark_run.get("benchmark_report") or {}).get("mode_case_outputs") or {})
bundle_case_outputs = dict((benchmark_run.get("benchmark_report") or {}).get("bundle_case_outputs") or mode_case_outputs)
benchmark = dict(benchmark_run.get("benchmark_report") or {})
bundle_summary = dict(benchmark.get("bundle_benchmark_summary") or {})
bundle_release_gate = dict(benchmark.get("bundle_release_gate") or benchmark.get("gate_report") or {})
bundle_category_scores = dict(benchmark.get("bundle_category_scores") or {})
behavior_summary = dict(benchmark.get("behavior_specialization_summary") or {})
behavior_gate = dict(benchmark.get("behavior_specialization_gate") or {})
reported_status = benchmark["status"]
reported_passes = bool(benchmark["passes"])
if adapter_dataset_hash and not dataset_matches_adapter:
    reported_status = "dataset_mismatch"
    reported_passes = False
report = {
    "status": reported_status,
    "passes": reported_passes,
    "adapter_path": str(adapter_path),
    "base_model": base_model,
    "source_records": [
        {"title": item["title"], "path": item["path"], "chars": len(item["text"])}
        for item in source_records
    ],
    "dataset": {
        "source_count": len(documents),
        "dataset_hash": dataset["dataset_hash"],
    },
    "adapter_training_dataset": adapter_dataset,
    "dataset_matches_adapter_training": dataset_matches_adapter,
    "evaluation_plan": {"case_count": plan["case_count"], "categories": plan["categories"]},
    "adapter_load_plan": load_plan,
    "runtime": runtime,
    "adapter_case_scores": adapter_case_scores,
    "retrieval_case_scores": baseline_case_scores,
    "retrieval_small_case_scores": retrieval_small_case_scores,
    "wrong_adapter_case_scores": wrong_adapter_case_scores,
    "bundle_case_outputs": bundle_case_outputs,
    "mode_case_outputs": mode_case_outputs,
    "benchmark_report": benchmark,
    "bundle_benchmark_summary": bundle_summary,
    "bundle_release_gate": bundle_release_gate,
    "bundle_category_scores": bundle_category_scores,
    "behavior_specialization_summary": behavior_summary,
    "behavior_specialization_gate": behavior_gate,
    "quality_gate_report": bundle_release_gate,
    "adapter_training_dataset_hash": adapter_dataset_hash,
    "benchmark_dataset_hash": dataset["dataset_hash"],
    "model_runtime_load_plan": load_plan,
    "hardware_status": hardware_status(),
}
report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(
    json.dumps(
        {
            "report_path": str(report_path),
            "status": report["status"],
            "passes": report["passes"],
            "dataset_matches_adapter_training": dataset_matches_adapter,
            "bundle_benchmark_summary": bundle_summary,
            "bundle_release_gate": bundle_release_gate,
            "behavior_specialization_summary": behavior_summary,
            "behavior_specialization_gate": behavior_gate,
        },
        indent=2,
    )
)
if not report["passes"]:
    raise SystemExit(2)
'@

$pythonScript | & $python -
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}
