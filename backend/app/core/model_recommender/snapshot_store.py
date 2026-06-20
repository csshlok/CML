from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from backend.app.core.config import get_settings
from backend.app.core.database import utc_now


def recommendation_snapshot_path() -> Path:
    path = get_settings().data_dir / "model-recommender-snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def build_input_fingerprint(
    *,
    hardware: dict[str, Any],
    model_rows: list[dict[str, Any]],
    catalog_version: str,
    benchmark_bundle_version: str,
) -> str:
    normalized_models = [
        {
            "id": row.get("id", ""),
            "family": row.get("family", ""),
            "installed": bool(row.get("installed")),
            "active_chat": bool(row.get("active_chat")),
            "active_expert": bool(row.get("active_expert")),
            "source_kind": row.get("source_kind", ""),
            "compatibility": {
                "chat": bool((row.get("compatibility") or {}).get("chat_role_accepted")),
                "expert": bool((row.get("compatibility") or {}).get("expert_role_accepted")),
                "family": (row.get("compatibility") or {}).get("family", ""),
            },
        }
        for row in model_rows
    ]
    payload = {
        "hardware": hardware,
        "models": normalized_models,
        "catalog_version": catalog_version,
        "benchmark_bundle_version": benchmark_bundle_version,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_cached_recommendation_snapshot(*, fingerprint: str) -> dict[str, Any] | None:
    path = recommendation_snapshot_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("input_fingerprint") or "") != fingerprint:
        return None
    snapshot = payload.get("recommendation")
    return dict(snapshot) if isinstance(snapshot, dict) else None


def persist_recommendation_snapshot(
    *,
    fingerprint: str,
    hardware: dict[str, Any],
    catalog_version: str,
    benchmark_bundle_version: str,
    recommendation: dict[str, Any],
) -> None:
    payload = {
        "generated_at": utc_now(),
        "input_fingerprint": fingerprint,
        "hardware_snapshot": hardware,
        "catalog_version": catalog_version,
        "benchmark_bundle_version": benchmark_bundle_version,
        "recommendation": recommendation,
    }
    recommendation_snapshot_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")
