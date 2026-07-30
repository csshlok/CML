from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any

from backend.app.core.hardware import hardware_status

_GIB = 1024**3
_LANES = {
    "interactive_chat",
    "extraction",
    "embeddings",
    "clustering",
    "local_model",
    "database",
    "maintenance",
}


@dataclass(frozen=True)
class ResourceBudget:
    cpu_workers: int
    io_workers: int
    local_model_slots: int
    memory_pressure: str
    accelerator: str
    lane_limits: dict[str, int]
    fingerprint: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def capability_fingerprint(snapshot: dict | None = None) -> str:
    status = dict(snapshot or hardware_status())
    gpus = [
        {
            "vendor": str(gpu.get("vendor") or "").casefold(),
            "vram_bytes": int(gpu.get("usable_vram_bytes") or gpu.get("vram_bytes") or 0),
            "shared_memory": bool(gpu.get("shared_memory")),
        }
        for gpu in status.get("gpus") or []
        if isinstance(gpu, dict)
    ]
    payload = {
        "cpu_count": max(1, int(status.get("cpu_count") or 1)),
        "total_memory_bytes": int(status.get("total_memory_bytes") or 0),
        "gpus": gpus,
        "runtime": str(status.get("runtime") or ""),
        "model": str(status.get("model") or ""),
        "embedding_model": str(status.get("embedding_model") or ""),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def resource_budget(snapshot: dict | None = None) -> ResourceBudget:
    """Return conservative resource lanes; unknown telemetry never means unlimited work."""

    status = dict(snapshot or hardware_status())
    logical_cpus = max(1, int(status.get("cpu_count") or 1))
    available_memory = _nonnegative_int(status.get("available_memory_bytes"))
    total_memory = _positive_int(status.get("total_memory_bytes"))
    memory_ratio = (
        available_memory / total_memory
        if available_memory is not None and total_memory is not None
        else None
    )
    if (
        (available_memory is not None and available_memory < 2 * _GIB)
        or (memory_ratio is not None and memory_ratio < 0.12)
    ):
        pressure = "critical"
    elif (
        (available_memory is not None and available_memory < 4 * _GIB)
        or (memory_ratio is not None and memory_ratio < 0.25)
    ):
        pressure = "high"
    else:
        pressure = "normal"

    cpu_workers = max(1, min(8, logical_cpus // 2))
    io_workers = max(1, min(8, logical_cpus))
    if pressure == "high":
        cpu_workers = max(1, cpu_workers // 2)
        io_workers = max(1, io_workers // 2)
    elif pressure == "critical":
        cpu_workers = 1
        io_workers = 1

    accelerator = "cpu"
    local_model_slots = 1
    for gpu in status.get("gpus") or []:
        if not isinstance(gpu, dict) or bool(gpu.get("shared_memory")):
            continue
        usable_vram = int(gpu.get("usable_vram_bytes") or gpu.get("vram_bytes") or 0)
        if usable_vram >= 4 * _GIB:
            accelerator = str(gpu.get("vendor") or "gpu").lower()
        if usable_vram >= 12 * _GIB and pressure == "normal":
            local_model_slots = 2
        break

    lane_limits = {
        "interactive_chat": 1,
        "extraction": io_workers,
        "embeddings": max(1, min(cpu_workers, 4)),
        "clustering": max(1, min(cpu_workers, 4)),
        "local_model": local_model_slots,
        "database": 1,
        "maintenance": max(1, min(cpu_workers, 2)),
    }
    return ResourceBudget(
        cpu_workers=cpu_workers,
        io_workers=io_workers,
        local_model_slots=local_model_slots,
        memory_pressure=pressure,
        accelerator=accelerator,
        lane_limits=lane_limits,
        fingerprint=capability_fingerprint(status),
    )


def lane_limit(
    lane: str,
    snapshot: dict | None = None,
    *,
    interactive_pending: bool = False,
) -> int:
    normalized = _normalize_lane(lane)
    budget = resource_budget(snapshot)
    safe_default = int(budget.lane_limits[normalized])
    learned = _load_lane_state(budget.fingerprint, normalized)
    current = int(learned.get("current_limit") or safe_default) if learned else safe_default
    current = max(1, min(current, _lane_ceiling(normalized, budget)))
    if interactive_pending and normalized == "local_model":
        return 0
    if interactive_pending and normalized not in {"interactive_chat", "database"}:
        return max(1, current // 2)
    return current


def record_lane_observation(
    lane: str,
    *,
    success: bool,
    latency_ms: float | None = None,
    pressure_event: str | None = None,
    snapshot: dict | None = None,
) -> dict[str, Any]:
    """Persist bounded AIMD feedback after complete work units, never mid-transaction."""

    normalized = _normalize_lane(lane)
    budget = resource_budget(snapshot)
    state = _load_lane_state(budget.fingerprint, normalized)
    current = max(
        1,
        int((state or {}).get("current_limit") or budget.lane_limits[normalized]),
    )
    stable = max(0, int((state or {}).get("stable_observations") or 0))
    failures = max(0, int((state or {}).get("failure_count") or 0))
    pressure = str(pressure_event or "").strip().casefold()
    constrained = not success or pressure in {
        "oom",
        "context_limit",
        "runtime_reset",
        "database_lock",
        "memory_pressure",
    }
    if constrained:
        current = max(1, current // 2)
        stable = 0
        failures += 1
    else:
        stable += 1
        # Three complete stable units form the hysteresis window. Growth is
        # additive and bounded by the current capability snapshot.
        if stable >= 3:
            current = min(current + 1, _lane_ceiling(normalized, budget))
            stable = 0
    result = {
        "fingerprint": budget.fingerprint,
        "lane": normalized,
        "current_limit": current,
        "stable_observations": stable,
        "failure_count": failures,
        "last_latency_ms": max(0.0, float(latency_ms or 0.0)),
        "last_pressure_event": pressure,
    }
    _store_lane_state(result)
    return result


def source_import_worker_count(total_files: int, snapshot: dict | None = None) -> int:
    if total_files <= 0:
        return 1
    return max(1, min(int(total_files), lane_limit("extraction", snapshot)))


def job_lane(job_type: str) -> str:
    normalized = str(job_type or "").casefold()
    if normalized.startswith("chat_"):
        return "interactive_chat"
    if normalized in {"source_import_batch", "integration_refresh", "model_discovery"}:
        return "extraction"
    if normalized in {"reindex_source", "vector_reconcile_incremental"}:
        return "embeddings"
    if "cluster" in normalized or normalized.startswith("project_structure"):
        return "clustering"
    if normalized in {
        "source_semantic_enrichment",
        "cluster_profile_refresh",
        "atomic_semantic_enrichment",
        "local_model_recovery",
    }:
        return "local_model"
    if normalized.startswith("turbovec") or normalized.endswith("_cleanup"):
        return "maintenance"
    return "database"


def _normalize_lane(lane: str) -> str:
    normalized = str(lane or "").strip().casefold()
    if normalized not in _LANES:
        raise ValueError(f"unknown_scheduler_lane:{normalized}")
    return normalized


def _lane_ceiling(lane: str, budget: ResourceBudget) -> int:
    ceilings = {
        "interactive_chat": 1,
        "extraction": max(1, budget.io_workers),
        "embeddings": max(1, min(budget.cpu_workers, 4)),
        "clustering": max(1, min(budget.cpu_workers, 4)),
        "local_model": max(1, budget.local_model_slots),
        "database": 1,
        "maintenance": max(1, min(budget.cpu_workers, 2)),
    }
    return ceilings[lane]


def _load_lane_state(fingerprint: str, lane: str) -> dict[str, Any] | None:
    try:
        from backend.app.core.database import connect, dict_from_row

        with connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM scheduler_lane_state
                WHERE capability_fingerprint = ? AND lane = ?
                """,
                (fingerprint, lane),
            ).fetchone()
        return dict_from_row(row) if row is not None else None
    except Exception:
        # Startup and migration must remain usable before this optional learned
        # state table exists. The conservative live budget is the fallback.
        return None


def _store_lane_state(state: dict[str, Any]) -> None:
    try:
        from backend.app.core.database import connect, utc_now

        with connect() as conn:
            conn.execute(
                """
                INSERT INTO scheduler_lane_state (
                    capability_fingerprint, lane, current_limit,
                    stable_observations, failure_count, last_latency_ms,
                    last_pressure_event, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(capability_fingerprint, lane) DO UPDATE SET
                    current_limit = excluded.current_limit,
                    stable_observations = excluded.stable_observations,
                    failure_count = excluded.failure_count,
                    last_latency_ms = excluded.last_latency_ms,
                    last_pressure_event = excluded.last_pressure_event,
                    updated_at = excluded.updated_at
                """,
                (
                    state["fingerprint"],
                    state["lane"],
                    state["current_limit"],
                    state["stable_observations"],
                    state["failure_count"],
                    state["last_latency_ms"],
                    state["last_pressure_event"],
                    utc_now(),
                ),
            )
    except Exception:
        # Learning is an optimization. Failure to persist it cannot stop work.
        return


def _nonnegative_int(value: object) -> int | None:
    return int(value) if isinstance(value, int) and value >= 0 else None


def _positive_int(value: object) -> int | None:
    return int(value) if isinstance(value, int) and value > 0 else None
