from __future__ import annotations

from typing import Any

from backend.app.core.model_recommender.benchmark_store import load_internal_benchmark_bundle
from backend.app.core.model_recommender.catalog import CatalogModelSpec, catalog_specs
from backend.app.core.model_recommender.family import (
    guess_parameter_count_b,
    is_probably_derivative,
    normalize_family_line,
    normalize_family_name,
)


def resolve_benchmark_evidence(model_row: dict[str, Any]) -> dict[str, Any]:
    specs = catalog_specs()
    bundle = load_internal_benchmark_bundle()
    model_id = str(model_row.get("id") or "")
    compatibility = model_row.get("compatibility") or {}
    source_kind = str(model_row.get("source_kind") or "")
    row_name = str(model_row.get("name") or model_id)
    local_path = str(model_row.get("local_path") or "")
    family = normalize_family_name(str(model_row.get("family") or ""))
    family_line = normalize_family_line(row_name or model_id or family)
    param_guess = guess_parameter_count_b(model_id, row_name, local_path)
    runtime_format = "transformers" if source_kind == "custom_import" else "gguf"

    measured = _internal_measured_evidence(bundle, model_id)
    if measured is not None:
        return measured

    source_records = _source_records(bundle)
    aliases = _candidate_aliases(model_id, row_name, family_line)

    if model_id in specs:
        spec = specs[model_id]
        layered_exact = _resolve_layered_exact_match(
            aliases=aliases,
            family=spec.family,
            family_line=normalize_family_line(spec.family_line),
            parameter_count_total_b=spec.parameter_count_total_b,
            runtime_format=spec.runtime_format,
            records=source_records,
            bundle_version=str(bundle.get("version") or ""),
        )
        if layered_exact is not None:
            return layered_exact
        return {
            "score": spec.benchmark.score,
            "source": "catalog_estimate",
            "confidence": min(spec.benchmark.confidence, 0.5),
            "updated_at": spec.benchmark.updated_at,
            "detail": (
                f"Catalog estimate for {spec.name}, combined with detected memory, "
                "graphics capacity, model size, and quantization."
            ),
            "bundle_version": str(bundle.get("version") or ""),
        }

    if source_kind == "custom_import" and compatibility.get("accepted"):
        if is_probably_derivative(f"{row_name} {local_path}"):
            return {
                "score": None,
                "source": "none",
                "confidence": 0.0,
                "updated_at": "",
                "detail": "Derivative naming lowered trust below the approved evidence floor.",
                "bundle_version": str(bundle.get("version") or ""),
            }
        exact = _resolve_layered_exact_match(
            aliases=aliases,
            family=family,
            family_line=family_line,
            parameter_count_total_b=param_guess,
            runtime_format=runtime_format,
            records=source_records,
            bundle_version=str(bundle.get("version") or ""),
        )
        if exact is not None:
            return exact
        family_specs = [spec for spec in specs.values() if spec.family == family]
        variant_match = _best_variant_match(
            family_specs=family_specs,
            family=family,
            family_line=family_line,
            param_guess=param_guess,
            runtime_format=runtime_format,
            records=source_records,
            bundle_version=str(bundle.get("version") or ""),
        )
        if variant_match is not None:
            return variant_match
        if family:
            return {
                "score": 58.0,
                "source": "self_reported",
                "confidence": 0.35,
                "updated_at": "",
                "detail": "Using weak self-reported family metadata because no approved benchmark lineage matched cleanly.",
                "bundle_version": str(bundle.get("version") or ""),
            }

    detail = str(compatibility.get("detail") or "")
    if detail:
        return {
            "score": None,
            "source": "none",
            "confidence": 0.0,
            "updated_at": "",
            "detail": detail,
            "bundle_version": str(bundle.get("version") or ""),
        }
    return {
        "score": None,
        "source": "none",
        "confidence": 0.0,
        "updated_at": "",
        "detail": "",
        "bundle_version": str(bundle.get("version") or ""),
    }


def _internal_measured_evidence(bundle: dict[str, Any], model_id: str) -> dict[str, Any] | None:
    internal_models = bundle.get("models") or {}
    if model_id in internal_models and isinstance(internal_models[model_id], dict):
        measured = internal_models[model_id]
        return {
            "score": measured.get("score"),
            "source": "internal_measured",
            "confidence": 1.0,
            "updated_at": str(measured.get("measured_at") or measured.get("updated_at") or ""),
            "detail": f"Internal measured benchmark from bundle {bundle.get('version') or 'unknown'}.",
            "bundle_version": str(bundle.get("version") or ""),
        }
    return None


def _source_records(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for layer_name, layer_source in (
        ("current", bundle.get("current_sources") or {}),
        ("frozen", bundle.get("frozen_sources") or {}),
        ("internal", bundle.get("cml_internal_sources") or {}),
    ):
        if not isinstance(layer_source, dict):
            continue
        for key, raw in layer_source.items():
            if not isinstance(raw, dict):
                continue
            records.append(
                {
                    "key": normalize_family_line(str(key or raw.get("model_id") or raw.get("name") or "")),
                    "score": raw.get("score"),
                    "family": normalize_family_name(str(raw.get("family") or "")),
                    "family_line": normalize_family_line(str(raw.get("family_line") or raw.get("family") or "")),
                    "parameter_count_total_b": _coerce_float(raw.get("parameter_count_total_b")),
                    "runtime_format": str(raw.get("runtime_format") or ""),
                    "updated_at": str(raw.get("updated_at") or raw.get("measured_at") or ""),
                    "layer": layer_name,
                    "display_name": str(raw.get("name") or key or ""),
                }
            )
    return records


def _candidate_aliases(model_id: str, row_name: str, family_line: str) -> set[str]:
    aliases = {
        normalize_family_line(model_id),
        normalize_family_line(row_name),
        normalize_family_line(family_line),
    }
    return {alias for alias in aliases if alias}


def _resolve_layered_exact_match(
    *,
    aliases: set[str],
    family: str,
    family_line: str,
    parameter_count_total_b: float | None,
    runtime_format: str,
    records: list[dict[str, Any]],
    bundle_version: str,
) -> dict[str, Any] | None:
    exact_matches = [
        record
        for record in records
        if record.get("key") in aliases and _runtime_formats_compatible(runtime_format, str(record.get("runtime_format") or ""))
    ]
    if not exact_matches:
        return None
    preferred = sorted(exact_matches, key=_record_sort_key)[0]
    if preferred.get("layer") == "current":
        return _record_to_evidence(
            preferred,
            source="direct",
            confidence=1.0,
            detail=f"Direct benchmark evidence from the current source set for {preferred.get('display_name') or preferred.get('key')}.",
            bundle_version=bundle_version,
        )
    if preferred.get("layer") == "internal":
        return _record_to_evidence(
            preferred,
            source="internal_measured",
            confidence=1.0,
            detail=f"Internal benchmark evidence from the calibrated source set for {preferred.get('display_name') or preferred.get('key')}.",
            bundle_version=bundle_version,
        )
    newer_lineage_exists = any(
        record.get("layer") == "current"
        and record.get("family") == family
        and record.get("family_line") == family_line
        and record.get("updated_at")
        for record in records
    )
    if newer_lineage_exists:
        return _record_to_evidence(
            preferred,
            source="variant",
            confidence=0.42,
            detail="Frozen-only benchmark evidence was demoted because newer current-source lineage exists for the same family line.",
            bundle_version=bundle_version,
        )
    if _size_ratio_within_limit(parameter_count_total_b, preferred.get("parameter_count_total_b")):
        return _record_to_evidence(
            preferred,
            source="direct",
            confidence=0.72,
            detail="Frozen-source direct benchmark reused because no newer current-source lineage exists for this exact variant.",
            bundle_version=bundle_version,
        )
    return None


def _best_variant_match(
    *,
    family_specs: list[CatalogModelSpec],
    family: str,
    family_line: str,
    param_guess: float | None,
    runtime_format: str,
    records: list[dict[str, Any]],
    bundle_version: str,
) -> dict[str, Any] | None:
    if not family_specs and not records:
        return None
    lineage_records = [
        record
        for record in records
        if record.get("family") == family and _runtime_formats_compatible(runtime_format, str(record.get("runtime_format") or ""))
    ]
    if lineage_records and param_guess is not None:
        same_line = [record for record in lineage_records if record.get("family_line") == family_line]
        sized_same_line = [record for record in same_line if _size_ratio_within_limit(param_guess, record.get("parameter_count_total_b"))]
        if sized_same_line:
            nearest = min(sized_same_line, key=lambda record: abs(float(record.get("parameter_count_total_b") or 0.0) - param_guess))
            size_delta = abs(float(nearest.get("parameter_count_total_b") or 0.0) - param_guess)
            if size_delta <= 0.75:
                confidence = 0.55 if nearest.get("layer") != "frozen" else 0.45
                detail = f"Inherited from the nearest approved {family_line or family} variant in the {nearest.get('layer')} source set."
                return _record_to_evidence(nearest, source="variant", confidence=confidence, detail=detail, bundle_version=bundle_version)
            interpolated = _line_interpolated_record_score(sized_same_line, param_guess)
            if interpolated is not None:
                confidence = 0.35 if any(record.get("layer") == "current" for record in sized_same_line) else 0.25
                return {
                    "score": interpolated,
                    "source": "line_interp",
                    "confidence": confidence,
                    "updated_at": max((str(record.get("updated_at") or "") for record in sized_same_line), default=""),
                    "detail": f"Interpolated from approved {family_line or family} models on the same family line.",
                    "bundle_version": bundle_version,
                }
        sized_family = [record for record in lineage_records if _size_ratio_within_limit(param_guess, record.get("parameter_count_total_b"))]
        if sized_family:
            nearest_family = min(sized_family, key=lambda record: abs(float(record.get("parameter_count_total_b") or 0.0) - param_guess))
            confidence = 0.60 if nearest_family.get("layer") != "frozen" else 0.48
            detail = f"Inherited from the nearest approved {family} checkpoint family in the {nearest_family.get('layer')} source set."
            return _record_to_evidence(nearest_family, source="base_model", confidence=confidence, detail=detail, bundle_version=bundle_version)
    if family_specs:
        line_matches = [spec for spec in family_specs if normalize_family_line(spec.family_line) == family_line]
        if line_matches and param_guess is not None:
            nearest = min(line_matches, key=lambda spec: abs(spec.parameter_count_total_b - param_guess))
            size_delta = abs(nearest.parameter_count_total_b - param_guess)
            if size_delta <= 0.75:
                return {
                    "score": nearest.benchmark.score,
                    "source": "variant",
                    "confidence": 0.55,
                    "updated_at": nearest.benchmark.updated_at,
                    "detail": f"Inherited from the nearest approved {nearest.family_line} variant.",
                    "bundle_version": bundle_version,
                }
            if _size_ratio_within_limit(param_guess, nearest.parameter_count_total_b):
                interpolated = _line_interpolated_score(line_matches, param_guess)
                return {
                    "score": interpolated,
                    "source": "line_interp",
                    "confidence": 0.35,
                    "updated_at": max((spec.benchmark.updated_at for spec in line_matches), default=""),
                    "detail": f"Interpolated from approved {nearest.family_line} models on the same family line.",
                    "bundle_version": bundle_version,
                }
        nearest_family = family_specs[0] if family_specs else None
        if nearest_family and _size_ratio_within_limit(param_guess, nearest_family.parameter_count_total_b):
            return {
                "score": nearest_family.benchmark.score,
                "source": "base_model",
                "confidence": 0.60,
                "updated_at": nearest_family.benchmark.updated_at,
                "detail": f"Inherited benchmark from the approved {nearest_family.family} base line.",
                "bundle_version": bundle_version,
            }
    return None


def _line_interpolated_record_score(records: list[dict[str, Any]], param_guess: float) -> float | None:
    with_params = [
        record
        for record in records
        if record.get("score") is not None and _coerce_float(record.get("parameter_count_total_b")) is not None
    ]
    if not with_params:
        return None
    ordered = sorted(with_params, key=lambda record: float(record.get("parameter_count_total_b") or 0.0))
    lower = ordered[0]
    upper = ordered[-1]
    for record in ordered:
        current_size = float(record.get("parameter_count_total_b") or 0.0)
        if current_size <= param_guess:
            lower = record
        if current_size >= param_guess:
            upper = record
            break
    if lower is upper:
        return float(lower.get("score") or 0.0)
    lower_size = float(lower.get("parameter_count_total_b") or 0.0)
    upper_size = float(upper.get("parameter_count_total_b") or 0.0)
    span = max(upper_size - lower_size, 0.1)
    weight = (param_guess - lower_size) / span
    lower_score = float(lower.get("score") or 0.0)
    upper_score = float(upper.get("score") or 0.0)
    return round(lower_score + (upper_score - lower_score) * max(0.0, min(1.0, weight)), 2)


def _line_interpolated_score(matches: list[CatalogModelSpec], param_guess: float) -> float:
    if not matches:
        return 0.0
    ordered = sorted(matches, key=lambda spec: spec.parameter_count_total_b)
    lower = ordered[0]
    upper = ordered[-1]
    for spec in ordered:
        if spec.parameter_count_total_b <= param_guess:
            lower = spec
        if spec.parameter_count_total_b >= param_guess:
            upper = spec
            break
    if lower.id == upper.id:
        return float(lower.benchmark.score or 0.0)
    span = max(upper.parameter_count_total_b - lower.parameter_count_total_b, 0.1)
    weight = (param_guess - lower.parameter_count_total_b) / span
    lower_score = float(lower.benchmark.score or 0.0)
    upper_score = float(upper.benchmark.score or 0.0)
    return round(lower_score + (upper_score - lower_score) * max(0.0, min(1.0, weight)), 2)


def _record_to_evidence(
    record: dict[str, Any],
    *,
    source: str,
    confidence: float,
    detail: str,
    bundle_version: str,
) -> dict[str, Any]:
    return {
        "score": record.get("score"),
        "source": source,
        "confidence": confidence,
        "updated_at": str(record.get("updated_at") or ""),
        "detail": detail,
        "bundle_version": bundle_version,
    }


def _record_sort_key(record: dict[str, Any]) -> tuple[int, str]:
    layer_order = {"internal": 0, "current": 1, "frozen": 2}
    return (layer_order.get(str(record.get("layer") or ""), 9), str(record.get("updated_at") or ""))


def _runtime_formats_compatible(candidate_runtime_format: str, record_runtime_format: str) -> bool:
    if not record_runtime_format:
        return True
    return normalize_family_line(candidate_runtime_format) == normalize_family_line(record_runtime_format)


def _size_ratio_within_limit(left: float | None, right: float | None) -> bool:
    left_value = _coerce_float(left)
    right_value = _coerce_float(right)
    if left_value is None or right_value is None:
        return True
    minimum = max(min(left_value, right_value), 0.1)
    maximum = max(left_value, right_value)
    return (maximum / minimum) <= 2.0


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
