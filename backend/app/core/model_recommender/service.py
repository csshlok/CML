from __future__ import annotations

from copy import deepcopy
from typing import Any

from backend.app.core.model_recommender.benchmark_evidence import resolve_benchmark_evidence
from backend.app.core.model_recommender.benchmark_store import load_internal_benchmark_bundle
from backend.app.core.model_recommender.catalog import catalog_specs, default_catalog_models
from backend.app.core.model_recommender.explanations import (
    build_chat_reasons,
    concise_chat_summary,
)
from backend.app.core.model_recommender.family import (
    guess_parameter_count_b,
    normalize_family_line,
    normalize_family_name,
)
from backend.app.core.model_recommender.fit import estimate_chat_fit
from backend.app.core.model_recommender.hardware_profile import build_hardware_profile
from backend.app.core.model_recommender.scoring import score_chat_candidate
from backend.app.core.model_recommender.snapshot_store import (
    build_input_fingerprint,
    load_cached_recommendation_snapshot,
    persist_recommendation_snapshot,
)
from backend.app.core.model_recommender.speed import estimate_chat_speed
from backend.app.core.model_registry import active_chat_setup_status, discover_installed_models, list_models


def build_model_recommendations(
    *,
    refresh: bool = False,
    hardware_profile_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = _resolved_hardware_profile(hardware_profile_override)
    model_rows = list_models()
    detected = discover_installed_models(max_results=12)
    specs = catalog_specs()
    catalog_version = "cml-recommender-v1"
    benchmark_bundle_version = str(load_internal_benchmark_bundle().get("version") or "")
    input_fingerprint = build_input_fingerprint(
        hardware=profile,
        model_rows=model_rows,
        catalog_version=catalog_version,
        benchmark_bundle_version=benchmark_bundle_version,
    )
    use_snapshot_cache = hardware_profile_override is None
    if use_snapshot_cache and not refresh:
        cached = load_cached_recommendation_snapshot(fingerprint=input_fingerprint)
        if cached is not None:
            return cached

    chat_candidates: list[dict[str, Any]] = []
    rejected_candidates: list[dict[str, Any]] = []

    for row in model_rows:
        candidate = _normalize_candidate(row, specs)
        evidence = resolve_benchmark_evidence(row)
        if not _is_chat_candidate_row(row):
            rejected_candidates.append(
                {
                    "candidate_id": candidate["id"],
                    "rejection_type": "chat_not_accepted",
                    "detail": str((row.get("compatibility") or {}).get("detail") or "Model is not accepted for chat."),
                }
            )
            continue
        fit = estimate_chat_fit(profile, candidate)
        speed = estimate_chat_speed(profile, candidate, fit)
        score = score_chat_candidate(candidate, fit, speed, evidence)
        candidate.update(
            {
                "fit": fit,
                "speed": speed,
                "evidence": evidence,
                "score": round(score, 2),
                "reasons": build_chat_reasons(candidate, fit, speed, evidence),
                "summary": concise_chat_summary(candidate),
            }
        )
        if fit["feasible"]:
            chat_candidates.append(candidate)
        else:
            rejected_candidates.append(
                {
                    "candidate_id": candidate["id"],
                    "rejection_type": "chat_fit_failed",
                    "detail": "; ".join(fit["warnings"]),
                }
            )

    chat_candidates.sort(key=lambda item: item["score"], reverse=True)
    recommended_chat = chat_candidates[0] if chat_candidates else None
    fallback_low_spec = _fallback_low_spec(chat_candidates)
    fallback_fastest = _fallback_fastest(chat_candidates)
    warnings = _collect_warnings(profile, recommended_chat)
    reasons = list((recommended_chat or {}).get("reasons") or [])
    confidence = _recommendation_confidence(profile, recommended_chat)
    detail = _detail_text(recommended_chat)
    benchmark_bundle_version = (recommended_chat or {}).get("evidence", {}).get("bundle_version", benchmark_bundle_version)
    input_fingerprint = build_input_fingerprint(
        hardware=profile,
        model_rows=model_rows,
        catalog_version=catalog_version,
        benchmark_bundle_version=benchmark_bundle_version,
    )
    result = {
        "hardware": profile,
        "recommended_model_id": recommended_chat["id"] if recommended_chat else "",
        "recommended_chat_model_id": recommended_chat["id"] if recommended_chat else "",
        "chat_fit_type": (recommended_chat or {}).get("fit", {}).get("fit_type", ""),
        "chat_estimated_tok_per_sec": (recommended_chat or {}).get("speed", {}).get("estimated_tok_per_sec"),
        "evidence_level": (recommended_chat or {}).get("evidence", {}).get("source", "none"),
        "confidence": confidence,
        "warnings": warnings,
        "reasons": reasons,
        "fallback_low_spec": fallback_low_spec,
        "fallback_fastest": fallback_fastest,
        "active_chat_setup": active_chat_setup_status(),
        "chat_recommendation": recommended_chat or {},
        "models": model_rows,
        "detected_compatible_models": detected["models"],
        "detected_compatible_model_count": detected["compatible_model_count"],
        "rejected_candidates": rejected_candidates,
        "detail": detail,
        "operator_summary": _operator_summary(recommended_chat),
        "scoring_breakdown": _scoring_breakdown(recommended_chat),
        "candidate_table": _candidate_table(chat_candidates),
        "benchmark_evidence_audit": _benchmark_evidence_audit(chat_candidates),
        "catalog_version": catalog_version,
        "benchmark_bundle_version": benchmark_bundle_version,
        "catalog_models": default_catalog_models(),
    }
    if use_snapshot_cache:
        persist_recommendation_snapshot(
            fingerprint=input_fingerprint,
            hardware=profile,
            catalog_version=catalog_version,
            benchmark_bundle_version=benchmark_bundle_version,
            recommendation=result,
        )
    return result


def _resolved_hardware_profile(hardware_profile_override: dict[str, Any] | None) -> dict[str, Any]:
    profile = deepcopy(build_hardware_profile())
    if not hardware_profile_override:
        return profile
    for key, value in hardware_profile_override.items():
        if key == "gpus" and isinstance(value, list):
            profile["gpus"] = [dict(item) for item in value if isinstance(item, dict)]
            continue
        profile[key] = value
    return profile


def _normalize_candidate(row: dict[str, Any], specs: dict[str, Any]) -> dict[str, Any]:
    model_id = str(row.get("id") or "")
    spec = specs.get(model_id)
    family = normalize_family_name(str(row.get("family") or (spec.family if spec else "")))
    runtime_format = spec.runtime_format if spec else ("transformers" if row.get("source_kind") == "custom_import" else "gguf")
    quantization = spec.quantization if spec else ""
    total_b = spec.parameter_count_total_b if spec else _param_guess(row)
    active_b = spec.parameter_count_active_b if spec else None
    estimated_weight_bytes = spec.estimated_weight_bytes if spec else int(max(total_b, 1.0) * 1.8 * 1024**3)
    minimum_chat_tier = spec.minimum_chat_tier if spec else "cpu_minimum_spec"
    return {
        "id": model_id,
        "name": str(row.get("name") or (spec.name if spec else model_id)),
        "family": family,
        "family_line": spec.family_line if spec else normalize_family_line(f"{row.get('name') or ''} {row.get('local_path') or ''} {family}"),
        "runtime_format": runtime_format,
        "quantization": quantization,
        "parameter_count_total_b": total_b,
        "parameter_count_active_b": active_b,
        "estimated_weight_bytes": estimated_weight_bytes,
        "minimum_chat_tier": minimum_chat_tier,
        "installed": bool(row.get("installed")),
        "local_path": str(row.get("local_path") or ""),
        "source_kind": str(row.get("source_kind") or ""),
        "compatibility": row.get("compatibility") or {},
        "active_chat": bool(row.get("active_chat")),
        "role_kind": "chat",
    }


def _param_guess(row: dict[str, Any]) -> float:
    value = guess_parameter_count_b(
        str(row.get("id") or ""),
        str(row.get("name") or ""),
        str(row.get("local_path") or ""),
    )
    return value if value is not None else 4.0


def _is_chat_candidate_row(row: dict[str, Any]) -> bool:
    source_kind = str(row.get("source_kind") or "")
    compatibility = row.get("compatibility") or {}
    if source_kind == "default_choice":
        return True
    return bool(compatibility.get("chat_role_accepted"))


def _detail_text(chat: dict[str, Any] | None) -> str:
    if not chat:
        return "No approved chat model fits this device conservatively. Start with the lowest-cost local runtime path or a weaker machine profile."
    return f"{chat['name']} is the best local chat recommendation for this device in RAG-only mode."


def _fallback_low_spec(chat_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not chat_candidates:
        return {}
    choice = min(
        chat_candidates,
        key=lambda item: (
            float(item.get("parameter_count_total_b") or 0.0),
            float(item.get("estimated_weight_bytes") or 0),
            -float(item.get("score") or 0.0),
        ),
    )
    return {
        "id": choice.get("id", ""),
        "name": choice.get("name", ""),
        "detail": "Lowest-cost approved fallback when the machine needs the safest chat runtime.",
    }


def _fallback_fastest(chat_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not chat_candidates:
        return {}
    choice = max(
        chat_candidates,
        key=lambda item: float((item.get("speed") or {}).get("estimated_tok_per_sec") or 0.0),
    )
    return {
        "id": choice.get("id", ""),
        "name": choice.get("name", ""),
        "detail": "Fastest approved chat fallback under the current conservative speed estimate.",
    }


def _collect_warnings(profile: dict[str, Any], recommended_chat: dict[str, Any] | None) -> list[str]:
    warnings: list[str] = list(profile.get("warnings") or [])
    warnings.extend(list((recommended_chat or {}).get("fit", {}).get("warnings") or []))
    deduped: list[str] = []
    seen: set[str] = set()
    for warning in warnings:
        text = str(warning or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _recommendation_confidence(profile: dict[str, Any], recommended_chat: dict[str, Any] | None) -> str:
    evidence_confidence = float((recommended_chat or {}).get("evidence", {}).get("confidence") or 0.0)
    speed_confidence = str((recommended_chat or {}).get("speed", {}).get("confidence") or "low")
    detection_confidence = str(profile.get("detection_confidence") or "low")
    runtime_detected = bool(profile.get("runtime_detected"))
    if not runtime_detected:
        return "low"
    if detection_confidence == "high" and evidence_confidence >= 0.8 and speed_confidence in {"high", "medium"}:
        return "high"
    if detection_confidence in {"high", "medium"} and evidence_confidence >= 0.55:
        return "medium"
    return "low"


def _operator_summary(chat_choice: dict[str, Any] | None) -> str:
    if not chat_choice:
        return "No feasible approved chat runtime candidate passed the current conservative fit gate."
    return (
        f"Chat recommendation resolved to {chat_choice.get('id')} with "
        f"{chat_choice.get('fit', {}).get('fit_type')} fit for RAG-only operation."
    )


def _scoring_breakdown(chat_choice: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "chat": {
            "id": (chat_choice or {}).get("id", ""),
            "score": (chat_choice or {}).get("score"),
            "fit_type": (chat_choice or {}).get("fit", {}).get("fit_type"),
            "estimated_tok_per_sec": (chat_choice or {}).get("speed", {}).get("estimated_tok_per_sec"),
            "evidence_source": (chat_choice or {}).get("evidence", {}).get("source"),
            "evidence_confidence": (chat_choice or {}).get("evidence", {}).get("confidence"),
        }
    }


def _candidate_table(chat_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candidate in chat_candidates:
        rows.append(
            {
                "candidate_id": candidate.get("id", ""),
                "role": "chat",
                "family": candidate.get("family", ""),
                "score": candidate.get("score"),
                "fit_type": candidate.get("fit", {}).get("fit_type"),
                "estimated_tok_per_sec": candidate.get("speed", {}).get("estimated_tok_per_sec"),
                "evidence_source": candidate.get("evidence", {}).get("source"),
                "evidence_detail": candidate.get("evidence", {}).get("detail"),
            }
        )
    return rows


def _benchmark_evidence_audit(chat_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    audit_rows: list[dict[str, Any]] = []
    for candidate in chat_candidates:
        evidence = candidate.get("evidence") or {}
        audit_rows.append(
            {
                "candidate_id": candidate.get("id", ""),
                "family": candidate.get("family", ""),
                "source": evidence.get("source", "none"),
                "confidence": evidence.get("confidence", 0.0),
                "updated_at": evidence.get("updated_at", ""),
                "detail": evidence.get("detail", ""),
                "bundle_version": evidence.get("bundle_version", ""),
            }
        )
    return audit_rows
