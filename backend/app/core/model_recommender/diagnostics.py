from __future__ import annotations

from typing import Any

from backend.app.core.database import utc_now
from backend.app.core.model_recommender.benchmark_store import load_internal_benchmark_bundle
from backend.app.core.model_recommender.service import build_model_recommendations


def export_recommendation_diagnostics(
    *,
    hardware_profile_override: dict[str, Any] | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    recommendation = build_model_recommendations(
        refresh=refresh,
        hardware_profile_override=hardware_profile_override,
    )
    benchmark_bundle = load_internal_benchmark_bundle()
    return {
        "generated_at": utc_now(),
        "catalog_version": recommendation.get("catalog_version", ""),
        "benchmark_bundle_version": recommendation.get("benchmark_bundle_version", ""),
        "benchmark_bundle": benchmark_bundle,
        "hardware": recommendation.get("hardware", {}),
        "recommendation": recommendation,
        "fit_speed_report": build_fit_speed_report(recommendation),
        "calibration_summary": build_calibration_summary(recommendation, benchmark_bundle),
    }


def build_fit_speed_report(recommendation: dict[str, Any]) -> dict[str, Any]:
    candidate_rows = list(recommendation.get("candidate_table") or [])
    chat_rows = [row for row in candidate_rows if row.get("role") == "chat"]
    return {
        "machine_profile": {
            "hardware_tier": str((recommendation.get("hardware") or {}).get("hardware_tier") or ""),
            "detection_confidence": str((recommendation.get("hardware") or {}).get("detection_confidence") or ""),
            "runtime_backend": str((recommendation.get("hardware") or {}).get("runtime_backend") or ""),
        },
        "recommended_chat": _candidate_fit_speed_row(recommendation.get("chat_recommendation") or {}, role="chat"),
        "chat_candidates": chat_rows,
    }


def build_calibration_summary(recommendation: dict[str, Any], benchmark_bundle: dict[str, Any]) -> dict[str, Any]:
    model_measurements = benchmark_bundle.get("models") or {}
    candidate_rows = list(recommendation.get("candidate_table") or [])

    model_rows: list[dict[str, Any]] = []
    speed_band_matches = 0
    speed_band_mismatches = 0
    fit_matches = 0
    fit_mismatches = 0

    for row in candidate_rows:
        if row.get("role") != "chat":
            continue
        measurement = model_measurements.get(str(row.get("candidate_id") or ""))
        if not isinstance(measurement, dict):
            continue
        estimated_speed = _coerce_float(row.get("estimated_tok_per_sec"))
        measured_speed = _coerce_float(measurement.get("estimated_tok_per_sec"))
        estimated_band = _speed_band(estimated_speed)
        measured_band = _speed_band(measured_speed)
        fit_type = str(row.get("fit_type") or "")
        runtime_success = measurement.get("runtime_success")
        fit_outcome = _fit_outcome_from_runtime(runtime_success)
        fit_match = fit_outcome is None or _fit_prediction_matches_outcome(fit_type, fit_outcome)
        speed_match = estimated_band == measured_band and estimated_band != "unknown"
        if fit_match:
            fit_matches += 1
        else:
            fit_mismatches += 1
        if speed_match:
            speed_band_matches += 1
        elif measured_band != "unknown" and estimated_band != "unknown":
            speed_band_mismatches += 1
        model_rows.append(
            {
                "candidate_id": str(row.get("candidate_id") or ""),
                "estimated_tok_per_sec": estimated_speed,
                "measured_tok_per_sec": measured_speed,
                "estimated_speed_band": estimated_band,
                "measured_speed_band": measured_band,
                "fit_type": fit_type,
                "runtime_success": runtime_success,
                "fit_prediction_match": fit_match,
                "speed_band_match": speed_match,
                "measured_at": str(measurement.get("measured_at") or ""),
            }
        )

    comparable_speed_count = speed_band_matches + speed_band_mismatches
    comparable_fit_count = fit_matches + fit_mismatches
    return {
        "measured_model_count": len(model_rows),
        "recommended_chat_model_id": str(recommendation.get("recommended_chat_model_id") or ""),
        "speed_band_match_rate": _safe_rate(speed_band_matches, comparable_speed_count),
        "speed_band_mismatch_rate": _safe_rate(speed_band_mismatches, comparable_speed_count),
        "fit_match_rate": _safe_rate(fit_matches, comparable_fit_count),
        "fit_mismatch_rate": _safe_rate(fit_mismatches, comparable_fit_count),
        "model_calibration_rows": model_rows,
    }


def _candidate_fit_speed_row(candidate: dict[str, Any], *, role: str) -> dict[str, Any]:
    if not candidate:
        return {}
    fit = candidate.get("fit") or {}
    speed = candidate.get("speed") or {}
    return {
        "candidate_id": str(candidate.get("id") or ""),
        "name": str(candidate.get("name") or ""),
        "fit_type": str(fit.get("fit_type") or ""),
        "feasible": bool(fit.get("feasible")),
        "required_gib": fit.get("required_gib"),
        "estimated_tok_per_sec": _coerce_float(speed.get("estimated_tok_per_sec")),
        "estimated_speed_band": _speed_band(_coerce_float(speed.get("estimated_tok_per_sec"))),
        "thresholds": dict(speed.get("thresholds") or {}),
        "warnings": list(fit.get("warnings") or []),
        "speed_notes": list(speed.get("notes") or []),
    }


def _speed_band(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value >= 8.0:
        return "comfortable"
    if value >= 4.0:
        return "acceptable"
    if value >= 1.5:
        return "degraded"
    return "too_slow"


def _fit_outcome_from_runtime(runtime_success: Any) -> str | None:
    if runtime_success is None:
        return None
    return "runnable" if bool(runtime_success) else "not_runnable"


def _fit_prediction_matches_outcome(fit_type: str, outcome: str) -> bool:
    if outcome == "runnable":
        return fit_type in {"full_gpu", "partial_offload", "cpu_only", "cpu_local_runtime"}
    return fit_type in {"cannot_run", "blocked"}


def _safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
