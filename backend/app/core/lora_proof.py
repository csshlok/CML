from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.core.expert_runtime import runtime_adapter_load_plan
from backend.app.core.model_registry import model_compatibility_report


def build_lora_smoke_proof(report: dict[str, Any]) -> dict[str, Any]:
    artifacts = list(report.get("artifacts") or [])
    active_artifact = next((item for item in artifacts if item.get("active")), artifacts[0] if artifacts else None)
    runtime_smoke = report.get("runtime_smoke") or {}
    benchmark = report.get("benchmark_report") or {}
    dataset = report.get("dataset") or {}
    base_model = str((active_artifact or {}).get("base_model") or report.get("base_model_path") or "")
    adapter_path = str((active_artifact or {}).get("local_path") or runtime_smoke.get("adapter_path") or "")

    load_plan = runtime_adapter_load_plan(adapter_path=adapter_path, base_model=base_model) if adapter_path else {}
    compatibility = model_compatibility_report(base_model) if base_model else {}
    pairing = _pairing_report(base_model=base_model, adapter_path=adapter_path, load_plan=load_plan, compatibility=compatibility)
    gates = _gate_report(report=report, runtime_smoke=runtime_smoke, benchmark=benchmark, pairing=pairing)
    return {
        "mode": report.get("mode") or "",
        "used_synthetic_sources": bool(report.get("used_synthetic_sources")),
        "real_dataset": {
            "source_record_count": len(report.get("source_records") or []),
            "source_records": report.get("source_records") or [],
            "dataset_hash": dataset.get("dataset_hash") or "",
            "source_count": int(dataset.get("source_count") or 0),
            "unique_content_hash_count": int(dataset.get("unique_content_hash_count") or 0),
            "estimated_token_count": int(dataset.get("estimated_token_count") or 0),
        },
        "hardware": {
            "actual": report.get("actual_hardware_status") or {},
            "used_for_training": report.get("hardware_status_used") or {},
        },
        "dependencies": {
            "trainer": report.get("trainer_dependency_status") or {},
            "runtime": (load_plan.get("runtime_dependencies") or runtime_smoke.get("plan", {}).get("runtime_dependencies") or {}),
        },
        "adapter": {
            "artifact_count": len(artifacts),
            "active_artifact": active_artifact or {},
            "path": adapter_path,
            "load_plan": load_plan,
            "runtime_smoke": runtime_smoke,
        },
        "base_model": {
            "path": base_model,
            "compatibility": compatibility,
        },
        "pairing": pairing,
        "benchmark": {
            "report": benchmark,
            "baseline_score": (benchmark.get("bundle_benchmark_summary") or {}).get("retrieval_only_full_score")
            or (benchmark.get("overall") or {}).get("retrieval_only_score"),
            "retrieval_only_full_score": (benchmark.get("bundle_benchmark_summary") or {}).get("retrieval_only_full_score"),
            "retrieval_only_small_score": (benchmark.get("bundle_benchmark_summary") or {}).get("retrieval_only_small_score"),
            "bundle_with_expert_score": (benchmark.get("bundle_benchmark_summary") or {}).get("bundle_with_expert_score")
            or (benchmark.get("overall") or {}).get("adapter_score"),
            "bundle_without_expert_score": (benchmark.get("bundle_benchmark_summary") or {}).get("bundle_without_expert_score"),
            "quality_delta": (benchmark.get("bundle_release_gate") or {}).get("quality_regression_vs_retrieval_full")
            if (benchmark.get("bundle_release_gate") or {})
            else (benchmark.get("overall") or {}).get("quality_delta"),
            "passes": bool(benchmark.get("passes")),
            "expert_objective_version": str((benchmark.get("metadata") or {}).get("expert_objective_version") or ""),
            "bundle_benchmark_summary": benchmark.get("bundle_benchmark_summary") or {},
            "bundle_release_gate": benchmark.get("bundle_release_gate") or benchmark.get("gate_report") or {},
            "behavior_specialization_summary": benchmark.get("behavior_specialization_summary") or {},
            "behavior_specialization_gate": benchmark.get("behavior_specialization_gate") or {},
            "bundle_readiness": benchmark.get("bundle_readiness") or {},
            "legacy_overall": benchmark.get("overall") or {},
        },
        "gates": gates,
        "public_gate": {
            "passes": bool(gates["public_gate"]["ok"]),
            "blocked_reasons": gates["public_gate"]["blocked_reasons"],
        },
    }


def build_lora_smoke_proof_from_file(report_path: str | Path) -> dict[str, Any]:
    path = Path(report_path)
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError("LoRA smoke report must be a JSON object.")
    proof = build_lora_smoke_proof(report)
    proof["source_report_path"] = str(path)
    return proof


def write_lora_smoke_proof(report_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    proof = build_lora_smoke_proof_from_file(report_path)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(proof, indent=2), encoding="utf-8")
    return proof


def _pairing_report(*, base_model: str, adapter_path: str, load_plan: dict[str, Any], compatibility: dict[str, Any]) -> dict[str, Any]:
    metadata = load_plan.get("adapter_metadata") or {}
    resolved = load_plan.get("resolved_base_model") or {}
    declared_base = str(metadata.get("base_model_name_or_path") or "")
    resolved_base = str(resolved.get("base_model_path") or "")
    normalized_base = _normalized_path(base_model)
    normalized_declared = _normalized_path(declared_base)
    normalized_resolved = _normalized_path(resolved_base)
    declared_matches = bool(
        declared_base
        and (
            normalized_declared == normalized_base
            or normalized_declared == normalized_resolved
            or Path(declared_base).name.lower() == Path(base_model).name.lower()
        )
    )
    return {
        "compatible": bool(load_plan.get("available") and compatibility.get("expert_role_accepted") and declared_matches),
        "adapter_path": adapter_path,
        "base_model": base_model,
        "resolved_base_model_path": resolved_base,
        "adapter_declared_base_model": declared_base,
        "adapter_declared_base_matches": declared_matches,
        "expert_role_accepted": bool(compatibility.get("expert_role_accepted")),
        "peft_type": metadata.get("peft_type") or "",
        "task_type": metadata.get("task_type") or "",
        "peft_version": metadata.get("peft_version") or "",
        "target_modules": metadata.get("target_modules") or [],
        "detail": load_plan.get("detail") or "",
    }


def _gate_report(*, report: dict[str, Any], runtime_smoke: dict[str, Any], benchmark: dict[str, Any], pairing: dict[str, Any]) -> dict[str, Any]:
    real_data_ok = not bool(report.get("used_synthetic_sources")) and bool((report.get("source_records") or []))
    runtime_ok = bool(runtime_smoke.get("ok"))
    benchmark_ok = bool(benchmark.get("passes"))
    pairing_ok = bool(pairing.get("compatible"))
    hardware = report.get("actual_hardware_status") or {}
    hardware_avx2 = hardware.get("avx2")
    hardware_proof_present = bool(hardware) and hardware_avx2 is not None
    hardware_supported = hardware_avx2 is not False
    blocked = []
    for ok, reason in (
        (real_data_ok, "real_dataset_missing"),
        (runtime_ok, "live_runtime_smoke_failed"),
        (benchmark_ok, "expert_bundle_benchmark_failed"),
        (pairing_ok, "adapter_base_pairing_unproven"),
        (hardware_proof_present, "hardware_avx2_proof_missing"),
        (hardware_supported, "hardware_avx2_unsupported"),
    ):
        if not ok:
            blocked.append(reason)
    return {
        "real_dataset": {"ok": real_data_ok},
        "live_runtime_smoke": {"ok": runtime_ok},
        "expert_bundle_benchmark": {"ok": benchmark_ok},
        "adapter_base_pairing": {"ok": pairing_ok},
        "hardware_proof": {"ok": hardware_proof_present},
        "hardware_support": {"ok": hardware_supported and hardware_proof_present},
        "public_gate": {"ok": not blocked, "blocked_reasons": blocked},
    }


def _normalized_path(value: str) -> str:
    if not value:
        return ""
    try:
        return str(Path(value).resolve(strict=False)).lower()
    except OSError:
        return value.lower()
