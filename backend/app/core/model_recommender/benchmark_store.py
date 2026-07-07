from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from backend.app.core.config import get_settings

_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {
    "path": None,
    "mtime": None,
    "payload": {},
}


def load_internal_benchmark_bundle() -> dict[str, Any]:
    bundle_path = _bundle_path()
    if bundle_path is None or not bundle_path.exists():
        return _empty_bundle()
    try:
        mtime = bundle_path.stat().st_mtime
    except OSError:
        return _empty_bundle()
    with _CACHE_LOCK:
        if _CACHE["path"] == str(bundle_path) and _CACHE["mtime"] == mtime:
            return dict(_CACHE["payload"])
    try:
        payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_bundle()
    normalized = _normalize_bundle(payload)
    with _CACHE_LOCK:
        _CACHE["path"] = str(bundle_path)
        _CACHE["mtime"] = mtime
        _CACHE["payload"] = dict(normalized)
    return normalized


def invalidate_internal_benchmark_bundle_cache() -> None:
    with _CACHE_LOCK:
        _CACHE["path"] = None
        _CACHE["mtime"] = None
        _CACHE["payload"] = {}


def _empty_bundle() -> dict[str, Any]:
    return {
        "version": "",
        "models": {},
        "current_sources": {},
        "frozen_sources": {},
        "cml_internal_sources": {},
    }


def _normalize_bundle(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _empty_bundle()
    normalized = _empty_bundle()
    normalized["version"] = str(payload.get("version") or "")
    for key in ("models", "current_sources", "frozen_sources", "cml_internal_sources"):
        value = payload.get(key) or {}
        normalized[key] = dict(value) if isinstance(value, dict) else {}
    return normalized


def record_model_measurement(
    model_id: str,
    *,
    score: float | None = None,
    estimated_tok_per_sec: float | None = None,
    startup_seconds: float | None = None,
    runtime_success: bool | None = None,
    training_success: bool | None = None,
    measured_at: str,
) -> dict[str, Any]:
    payload = load_internal_benchmark_bundle()
    models = dict(payload.get("models") or {})
    current = dict(models.get(model_id) or {})
    if score is not None:
        current["score"] = float(score)
    if estimated_tok_per_sec is not None:
        current["estimated_tok_per_sec"] = float(estimated_tok_per_sec)
    if startup_seconds is not None:
        current["startup_seconds"] = float(startup_seconds)
    if runtime_success is not None:
        current["runtime_success"] = bool(runtime_success)
    if training_success is not None:
        current["training_success"] = bool(training_success)
    current["measured_at"] = str(measured_at)
    models[model_id] = current
    payload["models"] = models
    if not payload.get("version"):
        payload["version"] = "local-measured-v1"
    _write_bundle(payload)
    return current
def _bundle_path() -> Path | None:
    explicit = os.environ.get("CML_MODEL_RECOMMENDER_BENCHMARK_BUNDLE")
    if explicit and explicit.strip():
        return Path(explicit)
    return get_settings().data_dir / "model-recommender-benchmarks.json"


def _write_bundle(payload: dict[str, Any]) -> None:
    bundle_path = _bundle_path()
    if bundle_path is None:
        return
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(json.dumps(_normalize_bundle(payload), indent=2), encoding="utf-8")
    invalidate_internal_benchmark_bundle_cache()
