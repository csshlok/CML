from dataclasses import asdict, dataclass
import ctypes
import hashlib
import os
import platform
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import quote
from urllib.error import URLError
from urllib.request import Request, urlopen
import json
import shutil
import threading

from backend.app.core.config import get_settings
from backend.app.core.database import utc_now
from backend.app.core import hardware as hardware_module
from backend.app.core.network_security import validate_huggingface_url


@dataclass(frozen=True)
class LocalModel:
    id: str
    name: str
    role: str
    hf_repo: str
    family: str
    quantization: str
    approximate_download_gb: float
    recommended_ram_gb: str
    notes: str
    expected_sha256: str = ""


@dataclass(frozen=True)
class ApprovedModelFamily:
    id: str
    name: str
    repo_prefixes: tuple[str, ...]
    model_type_prefixes: tuple[str, ...]
    architecture_keywords: tuple[str, ...]
    minimum_hardware_tier: str
    detail: str


MODEL_REGISTRY: tuple[LocalModel, ...] = (
    LocalModel(
        id="qwen3-4b-q4_k_m",
        name="Qwen3 4B Q4_K_M",
        role="default",
        hf_repo="Qwen/Qwen3-4B-GGUF",
        family="qwen",
        quantization="Q4_K_M",
        approximate_download_gb=2.5,
        recommended_ram_gb="8+",
        notes="Default local synthesis model for CML.",
    ),
    LocalModel(
        id="phi-4-mini-instruct-q4_k_m",
        name="Phi-4 Mini Instruct Q4_K_M",
        role="low-spec-fallback",
        hf_repo="unsloth/Phi-4-mini-instruct-GGUF",
        family="phi",
        quantization="Q4_K_M",
        approximate_download_gb=2.5,
        recommended_ram_gb="8+",
        notes="Fallback for weaker machines.",
    ),
    LocalModel(
        id="qwen3-8b-q4_k_m",
        name="Qwen3 8B Q4_K_M",
        role="quality-option",
        hf_repo="Qwen/Qwen3-8B-GGUF",
        family="qwen",
        quantization="Q4_K_M",
        approximate_download_gb=4.8,
        recommended_ram_gb="16+",
        notes="Higher-quality local synthesis option.",
    ),
    LocalModel(
        id="gemma-3-4b-it-q4_k_m",
        name="Gemma 3 4B IT Q4_K_M",
        role="optional",
        hf_repo="Aldaris/gemma-3-4b-it-Q4_K_M-GGUF",
        family="gemma",
        quantization="Q4_K_M",
        approximate_download_gb=2.5,
        recommended_ram_gb="8+",
        notes="Optional later candidate.",
    ),
    LocalModel(
        id="gemma-3-12b-it-q4_k_m",
        name="Gemma 3 12B IT Q4_K_M",
        role="optional-large",
        hf_repo="nocturne23/gemma-3-12b-it-Q4_K_M-GGUF",
        family="gemma",
        quantization="Q4_K_M",
        approximate_download_gb=6.9,
        recommended_ram_gb="24+",
        notes="Optional larger candidate for later experiments.",
    ),
)

APPROVED_MODEL_FAMILIES: tuple[ApprovedModelFamily, ...] = (
    ApprovedModelFamily(
        id="llama",
        name="Llama",
        repo_prefixes=("meta-llama", "llama",),
        model_type_prefixes=("llama",),
        architecture_keywords=("llama",),
        minimum_hardware_tier="cpu_minimum_spec",
        detail="Accepted when a local Llama Transformers checkpoint is present and passes the chat compatibility checks.",
    ),
    ApprovedModelFamily(
        id="qwen",
        name="Qwen",
        repo_prefixes=("qwen/",),
        model_type_prefixes=("qwen",),
        architecture_keywords=("qwen",),
        minimum_hardware_tier="cpu_minimum_spec",
        detail="Accepted when a local Qwen Transformers checkpoint is present and passes the chat compatibility checks.",
    ),
    ApprovedModelFamily(
        id="phi",
        name="Phi",
        repo_prefixes=("microsoft/phi-", "unsloth/phi-"),
        model_type_prefixes=("phi",),
        architecture_keywords=("phi",),
        minimum_hardware_tier="cpu_minimum_spec",
        detail="Accepted when a local Phi Transformers checkpoint is present and passes the chat compatibility checks.",
    ),
    ApprovedModelFamily(
        id="gemma",
        name="Gemma",
        repo_prefixes=("google/gemma", "gemma", "aldaris/gemma"),
        model_type_prefixes=("gemma",),
        architecture_keywords=("gemma",),
        minimum_hardware_tier="cpu_minimum_spec",
        detail="Accepted when a local Gemma Transformers checkpoint is present and passes the chat compatibility checks.",
    ),
)

_download_state: dict[str, dict[str, Any]] = {}
_download_lock = threading.Lock()
_cancelled_downloads: set[str] = set()
_download_threads: dict[str, threading.Thread] = {}
_download_responses: dict[str, Any] = {}
_download_done_events: dict[str, threading.Event] = {}
_download_state_loaded_from: Path | None = None
_download_state_last_persisted = 0.0
_MODEL_DISCOVERY_CACHE_LOCK = threading.Lock()
_MODEL_DISCOVERY_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
_MODEL_IMPORT_LOCK = threading.Lock()
MODEL_SCAN_SKIP_DIRS = {
    "$recycle.bin",
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "blobs",
    "node_modules",
    "program files",
    "program files (x86)",
    "refs",
    "tmp",
    "system volume information",
    "venv",
    "windows",
}
MODEL_CONFIG_FILES = ("config.json", "tokenizer_config.json", "tokenizer.json")


def models_dir() -> Path:
    settings = get_settings()
    path = settings.models_dir or settings.data_dir / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def imported_models_dir() -> Path:
    path = models_dir() / "imported"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _download_state_path() -> Path:
    return get_settings().data_dir / "model-downloads.json"


def _ensure_download_state_loaded() -> None:
    global _download_state_loaded_from
    state_path = _download_state_path()
    if _download_state_loaded_from == state_path:
        return
    # Tests and administrative recovery tools may seed an in-memory state before
    # changing the configured data directory. Preserve that explicit state.
    if _download_state:
        _download_state_loaded_from = state_path
        return
    loaded: dict[str, dict[str, Any]] = {}
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        rows = payload.get("downloads", {}) if isinstance(payload, dict) else {}
        if isinstance(rows, dict):
            loaded = {
                str(model_id): dict(state)
                for model_id, state in rows.items()
                if isinstance(state, dict)
            }
    except (OSError, json.JSONDecodeError):
        loaded = {}
    changed = False
    for state in loaded.values():
        if state.get("status") in {"resolving", "downloading", "cancelling"}:
            partial_value = str(state.get("partial_path") or "")
            partial_path = Path(partial_value) if partial_value else None
            downloaded = (
                partial_path.stat().st_size
                if partial_path is not None and partial_path.is_file()
                else int(state.get("bytes_downloaded") or 0)
            )
            state.update(
                {
                    "status": "interrupted",
                    "bytes_downloaded": downloaded,
                    "download_speed_bps": None,
                    "eta_seconds": None,
                    "resumable": bool(partial_path and partial_path.is_file()),
                    "error": "The app restarted during this download. Resume or cancel it.",
                    "updated_at": utc_now(),
                }
            )
            changed = True
    with _download_lock:
        _download_state.clear()
        _download_state.update(loaded)
        _download_state_loaded_from = state_path
        if changed:
            _persist_download_state_locked()


def _persist_download_state_locked(*, throttle_seconds: float = 0.0) -> None:
    global _download_state_last_persisted
    now = time.monotonic()
    if throttle_seconds and now - _download_state_last_persisted < throttle_seconds:
        return
    state_path = _download_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_name(f"{state_path.name}.{os.getpid()}.tmp")
    payload = {
        "schema_version": 1,
        "updated_at": utc_now(),
        "downloads": _download_state,
    }
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(state_path)
    _download_state_last_persisted = now


def registry_state_path() -> Path:
    return models_dir() / "registry-state.json"


def approved_family(family_id: str) -> ApprovedModelFamily | None:
    return next((family for family in APPROVED_MODEL_FAMILIES if family.id == family_id), None)


def list_models() -> list[dict[str, Any]]:
    rows = [model_status(model.id) for model in MODEL_REGISTRY]
    rows.extend(imported_model_statuses())
    return rows


def get_model(model_id: str) -> LocalModel | None:
    return next((model for model in MODEL_REGISTRY if model.id == model_id), None)


def imported_model_statuses() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    state = registry_state()
    for metadata_path, payload in _canonical_import_records(state):
        model_id = str(payload.get("id") or "")
        local_path = str(payload.get("local_path") or "")
        family = str(payload.get("family") or "")
        compatibility = model_compatibility_report(
            local_path,
            registered_family=family,
            include_replacement_recommendation=False,
        )
        rows.append(
            {
                "id": model_id,
                "name": str(payload.get("name") or model_id),
                "role": "custom-import",
                "family": family,
                "hf_repo": str(payload.get("hf_repo") or ""),
                "quantization": "",
                "approximate_download_gb": 0.0,
                "recommended_ram_gb": payload.get("recommended_ram_gb") or "",
                "notes": str(payload.get("notes") or "Imported local checkpoint."),
                "llama_cpp_ref": "",
                "installed": Path(local_path).is_file(),
                "local_path": local_path,
                "download": None,
                "integrity": {"status": "imported", "sha256": None, "expected_sha256": None},
                "active": state.get("active_chat_model_id") == model_id,
                "active_chat": state.get("active_chat_model_id") == model_id,
                "compatibility": compatibility,
                "source_kind": "custom_import",
            }
        )
    return rows


def _read_imported_model_records() -> list[tuple[Path, dict[str, Any]]]:
    records: list[tuple[Path, dict[str, Any]]] = []
    for metadata_path in sorted(imported_models_dir().glob("*/cml-model.json")):
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        records.append((metadata_path, payload))
    return records


def _import_record_identity(
    payload: dict[str, Any],
    metadata_path: Path,
    records_by_local_path: dict[str, tuple[Path, dict[str, Any]]] | None = None,
    visited: set[str] | None = None,
) -> str:
    content_sha256 = str(payload.get("content_sha256") or "").strip().lower()
    if content_sha256:
        return f"sha256:{content_sha256}"
    source_path = str(payload.get("source_path") or "").strip()
    if source_path:
        normalized_source = _normalized_path(Path(source_path))
        parent_record = (records_by_local_path or {}).get(normalized_source)
        current_key = _normalized_path(metadata_path)
        seen = set(visited or ())
        if parent_record is not None and current_key in seen:
            return f"cycle:{min(seen | {current_key})}"
        if parent_record is not None:
            seen.add(current_key)
            return _import_record_identity(
                parent_record[1],
                parent_record[0],
                records_by_local_path,
                seen,
            )
        return f"source:{normalized_source}"
    local_path = str(payload.get("local_path") or "").strip()
    if local_path:
        return f"local:{_normalized_path(Path(local_path))}"
    return f"metadata:{_normalized_path(metadata_path)}"


def _canonical_import_records(
    state: dict[str, Any] | None = None,
) -> list[tuple[Path, dict[str, Any]]]:
    registry = state or registry_state()
    active_model_id = str(registry.get("active_chat_model_id") or "")
    selected: dict[str, tuple[Path, dict[str, Any]]] = {}
    records = _read_imported_model_records()
    records_by_local_path = {
        _normalized_path(Path(str(payload.get("local_path")))): (metadata_path, payload)
        for metadata_path, payload in records
        if str(payload.get("local_path") or "").strip()
    }
    for metadata_path, payload in records:
        identity = _import_record_identity(payload, metadata_path, records_by_local_path)
        current = selected.get(identity)
        if current is None:
            selected[identity] = (metadata_path, payload)
            continue
        current_id = str(current[1].get("id") or "")
        candidate_id = str(payload.get("id") or "")
        if candidate_id == active_model_id and current_id != active_model_id:
            selected[identity] = (metadata_path, payload)
    return sorted(selected.values(), key=lambda item: str(item[0]).lower())


def _existing_import_for_source(source_file: Path) -> dict[str, Any] | None:
    normalized_source = _normalized_path(source_file)
    source_stat = source_file.stat()
    source_size = source_stat.st_size
    for _metadata_path, payload in _canonical_import_records():
        local_path = str(payload.get("local_path") or "").strip()
        if local_path and _normalized_path(Path(local_path)) == normalized_source:
            return payload
        original_path = str(payload.get("source_path") or "").strip()
        if not original_path or _normalized_path(Path(original_path)) != normalized_source:
            continue
        recorded_size = payload.get("source_size_bytes")
        if recorded_size is not None and int(recorded_size) != source_size:
            continue
        recorded_mtime = payload.get("source_mtime_ns")
        if recorded_mtime is not None and int(recorded_mtime) != source_stat.st_mtime_ns:
            continue
        managed_path = Path(local_path) if local_path else None
        if recorded_size is None and managed_path is not None:
            try:
                if managed_path.stat().st_size != source_size:
                    continue
            except OSError:
                continue
        return payload
    return None


def _existing_import_for_digest(content_sha256: str) -> dict[str, Any] | None:
    digest = content_sha256.strip().lower()
    if not digest:
        return None
    for _metadata_path, payload in _canonical_import_records():
        if str(payload.get("content_sha256") or "").strip().lower() == digest:
            return payload
    return None


def invalidate_model_discovery_cache() -> None:
    with _MODEL_DISCOVERY_CACHE_LOCK:
        _MODEL_DISCOVERY_CACHE.clear()


def model_status(model_id: str) -> dict[str, Any]:
    _ensure_download_state_loaded()
    model = get_model(model_id)
    if model is None:
        imported = next((item for item in imported_model_statuses() if item["id"] == model_id), None)
        if imported is not None:
            return imported
        raise KeyError(model_id)
    info = _model_to_dict(model)
    local_path = _find_local_model_file(model)
    state = _download_state.get(model_id)
    if state:
        state = _normalized_download_state(state)
    state_installed_path = state.get("local_path") if state and state.get("status") == "installed" else None
    registry = registry_state()
    resolved_local_path = local_path or _downloaded_model_path_from_registry(model_id)
    info.update(
        {
            "installed": resolved_local_path is not None or state_installed_path is not None,
            "local_path": str(resolved_local_path) if resolved_local_path else state_installed_path,
            "download": state,
            "integrity": _model_integrity_status(model, resolved_local_path),
            "active": registry.get("active_chat_model_id") == model_id,
            "active_chat": registry.get("active_chat_model_id") == model_id,
            "compatibility": _default_model_compatibility(model, resolved_local_path),
            "source_kind": "default_choice",
        }
    )
    return info


def model_integrity_manifest_status() -> dict[str, Any]:
    manifest = _trusted_integrity_manifest()
    entries = manifest.get("models", {})
    return {
        "available": bool(entries),
        "source": manifest.get("source") or "",
        "model_count": len(entries) if isinstance(entries, dict) else 0,
        "updated_at": manifest.get("updated_at") or "",
    }


def registry_state() -> dict[str, Any]:
    path = registry_state_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"active_chat_model_id": "", "approved_scan_roots": []}
    if not isinstance(payload, dict):
        return {"active_chat_model_id": "", "approved_scan_roots": []}
    legacy_active = str(payload.get("active_model_id") or "")
    payload.setdefault("active_chat_model_id", legacy_active)
    payload.setdefault("approved_scan_roots", [])
    return payload


def set_active_model(model_id: str, role: str = "chat") -> dict[str, Any]:
    rows = list_models()
    if not any(item["id"] == model_id for item in rows):
        raise KeyError(model_id)
    row = next(item for item in rows if item["id"] == model_id)
    compatibility = row.get("compatibility") or {}
    role = (role or "chat").strip().lower()
    state = registry_state()
    if role != "chat":
        raise ValueError("Unknown model activation role.")
    if not compatibility.get("chat_role_accepted"):
        raise ValueError("Model is not accepted for the chat role.")
    state["active_chat_model_id"] = model_id
    state["updated_at"] = utc_now()
    _write_registry_state(state)
    for row in list_models():
        if row["id"] == model_id:
            return row
    raise KeyError(model_id)


def activate_model_runtime(model_id: str, role: str = "chat") -> dict[str, Any]:
    from backend.app.core.model_runtime_supervisor import (
        ManagedRuntimeError,
        activate_managed_model,
    )

    row = model_status(model_id)
    role = (role or "chat").strip().lower()
    if role != "chat":
        raise ValueError("Unknown model activation role.")
    if not (row.get("compatibility") or {}).get("chat_role_accepted"):
        raise ValueError("Model is not accepted for the chat role.")
    local_path = Path(str(row.get("local_path") or ""))
    if not local_path.is_file() or local_path.suffix.casefold() != ".gguf":
        raise ValueError("Only an installed GGUF model can be started by Vault's local model engine.")
    if row.get("source_kind") == "default_choice":
        integrity = row.get("integrity") or {}
        if integrity.get("status") != "verified":
            raise ValueError(
                "Vault could not verify this model yet. Download it again before using it for chat."
            )

    previous_state = registry_state()
    try:
        activate_managed_model(model_id, str(local_path))
    except ManagedRuntimeError as exc:
        raise ValueError(str(exc)) from exc

    next_state = dict(previous_state)
    next_state["active_chat_model_id"] = model_id
    next_state["updated_at"] = utc_now()
    try:
        _write_registry_state(next_state)
    except OSError as exc:
        previous_model_id = str(previous_state.get("active_chat_model_id") or "")
        previous_model = (
            model_status(previous_model_id)
            if previous_model_id and previous_model_id != model_id
            else None
        )
        if previous_model and previous_model.get("local_path"):
            try:
                activate_managed_model(previous_model_id, str(previous_model["local_path"]))
            except ManagedRuntimeError:
                pass
        raise ValueError("Vault could not save the selected model; the previous model was restored.") from exc
    return model_status(model_id)


def _write_registry_state(state: dict[str, Any]) -> None:
    path = registry_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temporary.replace(path)


def _record_downloaded_model_path(model_id: str, local_path: Path) -> None:
    state = registry_state()
    downloaded_paths = state.get("downloaded_model_paths")
    if not isinstance(downloaded_paths, dict):
        downloaded_paths = {}
    downloaded_paths[model_id] = str(local_path)
    state["downloaded_model_paths"] = downloaded_paths
    state["updated_at"] = utc_now()
    _write_registry_state(state)


def approve_model_scan_root(root_path: str | Path) -> dict[str, Any]:
    raw = str(root_path or "").strip()
    if not raw:
        raise ValueError("Choose a model folder first.")
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("The selected model folder is not available.")
    state = registry_state()
    current = state.get("approved_scan_roots")
    approved = [str(item) for item in current] if isinstance(current, list) else []
    normalized = _normalized_path(root)
    if normalized not in {_normalized_path(Path(item)) for item in approved}:
        approved.append(str(root))
    state["approved_scan_roots"] = approved
    state["updated_at"] = utc_now()
    _write_registry_state(state)
    invalidate_model_discovery_cache()
    return {"path": str(root), "approved": True}


def active_chat_model_status() -> dict[str, Any] | None:
    active_model_id = str(registry_state().get("active_chat_model_id") or "")
    if not active_model_id:
        return None
    return next((item for item in list_models() if item["id"] == active_model_id), None)


def active_model_status() -> dict[str, Any] | None:
    return active_chat_model_status()


def model_recommendations(*, refresh: bool = False) -> dict[str, Any]:
    from backend.app.core.model_recommender import build_model_recommendations

    return build_model_recommendations(refresh=refresh)


def active_chat_setup_status() -> dict[str, Any]:
    chat_model = active_chat_model_status()
    chat_ok = bool(chat_model and (chat_model.get("compatibility") or {}).get("chat_role_accepted"))
    if not chat_ok:
        return {
            "accepted": False,
            "chat_model_id": chat_model.get("id") if chat_model else "",
            "detail": "Select an accepted chat model to complete local RAG setup.",
            "reasons": [],
        }
    return {
        "accepted": True,
        "chat_model_id": chat_model.get("id") if chat_model else "",
        "detail": "RAG-only mode uses a single accepted chat model.",
        "reasons": [],
    }


def start_model_download(model_id: str, *, target_dir: str | None = None) -> dict[str, Any]:
    _ensure_download_state_loaded()
    model = get_model(model_id)
    if model is None:
        raise KeyError(model_id)

    existing = model_status(model_id)
    if existing["installed"] and (existing.get("integrity") or {}).get("status") == "verified":
        return {"model_id": model_id, "status": "installed", "local_path": existing["local_path"]}

    try:
        target_root = _download_root_for_target(target_dir)
        approve_model_scan_root(target_root)
    except OSError as exc:
        state = _failed_model_download_state(model_id, f"Could not use selected model download location: {exc}")
        with _download_lock:
            _download_state[model_id] = state
            _persist_download_state_locked()
        return state

    disk_check = _model_disk_preflight(model, target_root=target_root)
    if not disk_check["ok"]:
        state = _failed_model_download_state(model_id, disk_check["message"])
        with _download_lock:
            _download_state[model_id] = state
            _persist_download_state_locked()
        return state

    with _download_lock:
        _cancelled_downloads.discard(model_id)
        active_other = next(
            (
                item
                for item in _download_state.values()
                if item.get("model_id") != model_id and item.get("status") in {"resolving", "downloading", "cancelling"}
            ),
            None,
        )
        if active_other:
            state = {
                "model_id": model_id,
                "status": "blocked",
                "bytes_downloaded": 0,
                "bytes_total": None,
                "total_bytes": None,
                "progress_percent": None,
                "download_speed_bps": None,
                "eta_seconds": None,
                "error": f"Another model download is already {active_other.get('status')}.",
                "started_at": utc_now(),
                "updated_at": utc_now(),
            }
            _download_state[model_id] = state
            _persist_download_state_locked()
            return state
        state = _download_state.get(model_id)
        if state and state["status"] in {"resolving", "downloading"}:
            return state
        _download_state[model_id] = {
            "model_id": model_id,
            "status": "resolving",
            "bytes_downloaded": 0,
            "bytes_total": None,
            "total_bytes": None,
            "progress_percent": None,
            "download_speed_bps": None,
            "eta_seconds": None,
            "error": None,
            "started_at": utc_now(),
            "updated_at": utc_now(),
        }
        _persist_download_state_locked()

    done_event = threading.Event()
    thread = threading.Thread(
        target=_download_model_with_ack,
        args=(model, target_root, done_event),
        daemon=True,
    )
    with _download_lock:
        _download_threads[model_id] = thread
        _download_done_events[model_id] = done_event
    thread.start()
    return _normalized_download_state(_download_state[model_id])


def cancel_model_download(model_id: str) -> dict[str, Any]:
    _ensure_download_state_loaded()
    model = get_model(model_id)
    if model is None:
        raise KeyError(model_id)
    response = None
    done_event = None
    worker_thread = None
    with _download_lock:
        state = _download_state.get(model_id)
        if state and state.get("status") == "installed":
            return state
        state_local_path = _installed_state_from_local_path(model_id, state)
        if state_local_path is not None:
            _download_state[model_id] = state_local_path
            _cancelled_downloads.discard(model_id)
            _persist_download_state_locked()
            return state_local_path
        local_path = _find_local_model_file(model)
        if local_path is not None:
            installed = _installed_download_state(model_id, local_path)
            _download_state[model_id] = installed
            _cancelled_downloads.discard(model_id)
            _persist_download_state_locked()
            return installed
        if not state or state.get("status") not in {"resolving", "downloading"}:
            _cleanup_partial_download(model)
            _download_state[model_id] = {
                "model_id": model_id,
                "status": "cancelled",
                "bytes_downloaded": state.get("bytes_downloaded") if state else 0,
                "bytes_total": state.get("bytes_total") if state else None,
                "total_bytes": state.get("total_bytes") if state else None,
                "progress_percent": state.get("progress_percent") if state else None,
                "download_speed_bps": None,
                "eta_seconds": None,
                "file_name": state.get("file_name") if state else None,
                "local_path": state.get("local_path") if state else None,
                "error": None,
                "started_at": state.get("started_at") if state else None,
                "updated_at": utc_now(),
            }
            _persist_download_state_locked()
            return _download_state[model_id]
        _cancelled_downloads.add(model_id)
        state.update({"status": "cancelling", "updated_at": utc_now()})
        response = _download_responses.get(model_id)
        done_event = _download_done_events.get(model_id)
        worker_thread = _download_threads.get(model_id)
        _persist_download_state_locked()
    if response is not None:
        try:
            response.close()
        except Exception:
            pass
    if done_event is not None and worker_thread is not threading.current_thread():
        done_event.wait(timeout=5.0)
    with _download_lock:
        current = _download_state.get(model_id, state)
        if current.get("status") == "cancelling":
            _cleanup_partial_download(model)
            current.update(
                {
                    "status": "cancelled",
                    "error": None,
                    "download_speed_bps": None,
                    "cancellation_acknowledged_at": utc_now(),
                    "updated_at": utc_now(),
                }
            )
            _persist_download_state_locked()
        return _normalized_download_state(current)


def _model_to_dict(model: LocalModel) -> dict[str, Any]:
    info = asdict(model)
    info["llama_cpp_ref"] = f"{model.hf_repo}:{model.quantization}"
    return info


def _is_transformers_model_dir(path: Path) -> bool:
    return path.is_dir() and any((path / name).exists() for name in MODEL_CONFIG_FILES)


def _runtime_dependency_status() -> dict[str, Any]:
    return {
        "available": True,
        "state": "not_required",
        "runtime": "rag_only",
        "detail": "RAG-only mode uses a single chat runtime and does not require a second model runtime.",
    }


def _missing_model_compatibility(family_id: str, notes: str = "") -> dict[str, Any]:
    family = approved_family(family_id)
    return {
        "status": "rejected",
        "accepted": False,
        "chat_role_accepted": False,
        "accepted_roles": [],
        "family": family_id,
        "family_name": family.name if family else family_id,
        "model_type": "",
        "architecture": "",
        "registered_family": family_id,
        "local_path": "",
        "runtime_dependencies": _runtime_dependency_status(),
        "hardware": hardware_module.hardware_status(),
        "reasons": [
            "No compatible local model is installed for this family."
        ],
        "selection_detail": "RAG-only mode uses a single local chat model.",
        "detail": notes or "Install or import a compatible local model to enable local chat.",
    }


def _default_model_compatibility(model: LocalModel, local_path: Path | None) -> dict[str, Any]:
    if local_path is None:
        return {
            **_missing_model_compatibility(model.family, model.notes),
            "detail": "Download this local chat model to use it in the chat role.",
        }
    hardware = hardware_module.hardware_status()
    family = approved_family(model.family)
    return {
        "status": "accepted",
        "accepted": True,
        "chat_role_accepted": True,
        "accepted_roles": ["chat"],
        "family": model.family,
        "family_name": family.name if family else model.family,
        "model_type": "gguf",
        "architecture": "",
        "registered_family": model.family,
        "local_path": str(local_path),
        "runtime_dependencies": _runtime_dependency_status(),
        "hardware": hardware,
        "reasons": [],
        "selection_detail": "Accepted for RAG-only local chat.",
        "detail": "Accepted local chat runtime model for RAG-only mode.",
    }


def model_compatibility_report(
    model_path: str | Path,
    *,
    registered_family: str = "",
    include_replacement_recommendation: bool = True,
) -> dict[str, Any]:
    target = Path(model_path) if str(model_path).strip() else Path("")
    runtime = _runtime_dependency_status()
    hardware = hardware_module.hardware_status()
    reasons: list[str] = []
    is_gguf = target.is_file() and target.suffix.casefold() == ".gguf"
    config = {} if is_gguf else _read_transformers_config(target)
    family = _detect_approved_family(config, registered_family=registered_family, model_path=str(target))
    model_type = str(config.get("model_type") or "")
    architectures = config.get("architectures") or []
    architecture = str(architectures[0] if isinstance(architectures, list) and architectures else "")

    if not model_path or not str(model_path).strip():
        reasons.append("Model path is required.")
    elif not target.exists():
        reasons.append("Model path does not exist.")
    elif not is_gguf:
        reasons.append("Vault's packaged local model engine accepts GGUF model files.")
    if not family:
        reasons.append("Model family is not in the approved Qwen/Phi/Gemma set.")
    if family and not _hardware_supports_family(family, hardware):
        reasons.append(f"Current hardware tier does not satisfy the minimum contract for the {family.name} family.")

    chat_role_accepted = not reasons
    accepted_roles = ["chat"] if chat_role_accepted else []
    replacement_recommendation = (
        _replacement_recommendation_for_current_hardware(family_id=family.id if family else "")
        if include_replacement_recommendation
        else {}
    )
    return {
        "status": "accepted" if chat_role_accepted else "rejected",
        "accepted": chat_role_accepted,
        "chat_role_accepted": chat_role_accepted,
        "accepted_roles": accepted_roles,
        "family": family.id if family else "",
        "family_name": family.name if family else "",
        "model_type": "gguf" if is_gguf else model_type,
        "architecture": architecture,
        "registered_family": registered_family,
        "local_path": str(target) if str(model_path).strip() else "",
        "runtime_dependencies": runtime,
        "hardware": hardware,
        "reasons": reasons,
        "selection_detail": (
            "Accepted for the chat role in RAG-only mode."
            if chat_role_accepted and family
            else "Rejected for the chat role."
        ),
        "replacement_recommendation": replacement_recommendation if not chat_role_accepted else {},
        "detail": (
            f"Accepted local {family.name} GGUF model for Vault RAG chat."
            if chat_role_accepted and family
            else "; ".join(reasons)
        ),
    }


def _replacement_recommendation_for_current_hardware(*, family_id: str = "") -> dict[str, Any]:
    try:
        recommendation = model_recommendations()
    except Exception:
        return {}
    recommended_chat = recommendation.get("recommended_chat_model_id") or ""
    chat_choice = recommendation.get("chat_recommendation") or {}
    if family_id and family_id == (chat_choice.get("family") or ""):
        return {
            "recommended_chat_model_id": recommended_chat,
            "detail": "This device is better aligned with the currently recommended chat model for the same family line.",
        }
    return {
        "recommended_chat_model_id": recommended_chat,
        "recommended_chat_summary": chat_choice.get("summary", ""),
        "detail": recommendation.get("detail", ""),
    }


def import_model_checkpoint(
    source_path: str | Path,
    *,
    name: str | None = None,
    progress_callback: Any | None = None,
    cancellation_callback: Any | None = None,
) -> dict[str, Any]:
    source_file = Path(source_path).resolve()
    with _MODEL_IMPORT_LOCK:
        return _import_model_checkpoint_locked(
            source_file,
            name=name,
            progress_callback=progress_callback,
            cancellation_callback=cancellation_callback,
        )


def _import_model_checkpoint_locked(
    source_file: Path,
    *,
    name: str | None,
    progress_callback: Any | None,
    cancellation_callback: Any | None,
) -> dict[str, Any]:
    report = model_compatibility_report(source_file)
    if not report["accepted"]:
        raise ValueError(report["detail"])
    if _paths_overlap(source_file, imported_models_dir()):
        raise ValueError("Imported checkpoint source and managed destination must be separate directories.")
    existing_payload = _existing_import_for_source(source_file)
    if existing_payload is not None:
        existing_id = str(existing_payload.get("id") or "")
        existing = next(
            (item for item in imported_model_statuses() if item["id"] == existing_id),
            None,
        )
        if existing is not None:
            return existing

    family = report["family"]
    destination_name = _safe_import_dir_name(name or source_file.stem or family)
    destination = imported_models_dir() / destination_name
    if _paths_overlap(source_file, destination):
        raise ValueError("Imported checkpoint source and managed destination must be separate directories.")
    if destination.exists():
        source_key = hashlib.sha256(_normalized_path(source_file).encode("utf-8")).hexdigest()[:10]
        destination_name = f"{destination_name}-{source_key}"
        destination = imported_models_dir() / destination_name
    staging = imported_models_dir() / f".{destination_name}.staging-{os.getpid()}-{time.time_ns()}"
    backup = imported_models_dir() / f".{destination_name}.backup-{os.getpid()}-{time.time_ns()}"
    model_id = f"custom-{destination_name}"
    local_model_path = destination / source_file.name
    source_stat = source_file.stat()
    metadata = {
        "id": model_id,
        "name": name or source_file.stem or destination_name,
        "family": family,
        "local_path": str(local_model_path),
        "source_path": str(source_file),
        "source_size_bytes": source_stat.st_size,
        "source_mtime_ns": source_stat.st_mtime_ns,
        "hf_repo": "",
        "notes": "Imported local checkpoint.",
        "recommended_ram_gb": "",
        "created_at": utc_now(),
    }
    staging.mkdir(parents=True)
    try:
        staged_file = staging / source_file.name
        total_bytes = source_stat.st_size
        copied_bytes = 0
        content_hasher = hashlib.sha256()
        with source_file.open("rb") as source, staged_file.open("wb") as target:
            while True:
                if cancellation_callback is not None:
                    cancellation_callback()
                chunk = source.read(4 * 1024 * 1024)
                if not chunk:
                    break
                target.write(chunk)
                content_hasher.update(chunk)
                copied_bytes += len(chunk)
                if progress_callback is not None:
                    progress_callback(copied_bytes, total_bytes)
        shutil.copystat(source_file, staged_file)
        metadata["content_sha256"] = content_hasher.hexdigest()
        duplicate_payload = _existing_import_for_digest(str(metadata["content_sha256"]))
        if duplicate_payload is not None:
            shutil.rmtree(staging)
            duplicate_id = str(duplicate_payload.get("id") or "")
            duplicate = next(
                (item for item in imported_model_statuses() if item["id"] == duplicate_id),
                None,
            )
            if duplicate is not None:
                return duplicate
        (staging / "cml-model.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        if destination.exists():
            destination.replace(backup)
        staging.replace(destination)
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if destination.exists() and backup.exists():
            shutil.rmtree(destination)
        if backup.exists() and not destination.exists():
            backup.replace(destination)
        if staging.exists():
            shutil.rmtree(staging)
        raise
    invalidate_model_discovery_cache()
    return next(item for item in imported_model_statuses() if item["id"] == model_id)


def preferred_chat_base_model() -> dict[str, Any] | None:
    active_chat = active_chat_model_status()
    if active_chat and (active_chat.get("compatibility") or {}).get("chat_role_accepted"):
        return active_chat

    for item in imported_model_statuses():
        if (item.get("compatibility") or {}).get("chat_role_accepted"):
            return item

    for root in installed_model_scan_roots():
        if not root.exists():
            continue
        for candidate in _iter_model_candidates(root, max_depth=2):
            compatibility = model_compatibility_report(candidate, include_replacement_recommendation=False)
            if compatibility.get("chat_role_accepted"):
                return {
                    "id": candidate.name,
                    "name": candidate.name,
                    "family": compatibility.get("family") or "",
                    "local_path": str(candidate.resolve()),
                    "compatibility": compatibility,
                    "source_kind": "local_search_root",
                }

    return None


def discover_installed_models(
    *,
    max_results: int = 32,
    include_rejected: bool = False,
    refresh: bool = False,
    progress_callback: Any | None = None,
    cancellation_callback: Any | None = None,
    scan_all_drives: bool = False,
) -> dict[str, Any]:
    settings = get_settings()
    locations = installed_model_scan_locations(scan_all_drives=scan_all_drives)
    cache_ttl = max(0, int(getattr(settings, "model_scan_cache_seconds", 30) or 0))
    cache_key = (
        tuple((_normalized_path(root), depth) for root, depth in locations),
        bool(include_rejected),
        int(max_results),
        bool(scan_all_drives),
    )
    if not refresh and cache_ttl > 0:
        with _MODEL_DISCOVERY_CACHE_LOCK:
            cached = _MODEL_DISCOVERY_CACHE.get(cache_key)
        if cached and (time.monotonic() - float(cached["stored_at"])) <= cache_ttl:
            return dict(cached["payload"])

    started = time.perf_counter()
    scanned_roots: list[str] = []
    missing_roots: list[str] = []
    models: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    compatible_count = 0
    truncated = False
    directories_checked = 0
    skipped_directories = 0
    imported_paths: set[str] = set()
    for _metadata_path, payload in _canonical_import_records():
        for key in ("local_path", "source_path"):
            candidate = str(payload.get(key) or "").strip()
            if candidate:
                imported_paths.add(_normalized_path(Path(candidate)))

    for root, scan_depth in locations:
        if cancellation_callback is not None:
            cancellation_callback()
        normalized_root = _normalized_path(root)
        if normalized_root in scanned_roots:
            continue
        if not root.exists():
            missing_roots.append(str(root))
            continue
        scanned_roots.append(normalized_root)
        if scan_depth < 0:
            walk_progress: dict[str, int] = {}

            def report_walk(progress: dict[str, int]) -> None:
                nonlocal directories_checked, skipped_directories
                directories_checked += int(progress.get("directories_checked") or 0)
                skipped_directories += int(progress.get("skipped_directories") or 0)
                if progress_callback is not None:
                    progress_callback(
                        {
                            "phase": "scanning",
                            "roots_scanned": len(scanned_roots),
                            "directories_checked": directories_checked,
                            "skipped_directories": skipped_directories,
                            "candidates_checked": len(seen_paths),
                            "models_found": len(models),
                        }
                    )

            candidates = _iter_model_candidates_with_progress(
                root,
                max_depth=scan_depth,
                progress_callback=report_walk,
                cancellation_callback=cancellation_callback,
            )
        else:
            candidates = _iter_model_candidates(root, max_depth=scan_depth)
        for candidate in candidates:
            if cancellation_callback is not None:
                cancellation_callback()
            normalized = _normalized_path(candidate)
            if normalized in seen_paths:
                continue
            seen_paths.add(normalized)
            compatibility = model_compatibility_report(candidate, include_replacement_recommendation=False)
            if compatibility.get("accepted"):
                compatible_count += 1
            accepted = bool(compatibility.get("accepted"))
            if not include_rejected and not accepted:
                continue
            metadata = _discovered_model_metadata(candidate, compatibility=compatibility, root=root)
            if _normalized_path(Path(metadata["local_path"])) in imported_paths:
                metadata["already_imported"] = True
            if len(models) < max_results:
                models.append(metadata)
            elif include_rejected and accepted:
                rejected_index = next(
                    (
                        index
                        for index, item in enumerate(models)
                        if not item["compatibility"].get("accepted")
                    ),
                    None,
                )
                if rejected_index is not None:
                    models[rejected_index] = metadata
                    truncated = True
                else:
                    truncated = True
            else:
                truncated = True
            if progress_callback is not None and len(seen_paths) % 25 == 0:
                progress_callback(
                    {
                        "phase": "scanning",
                        "roots_scanned": len(scanned_roots),
                        "directories_checked": directories_checked,
                        "skipped_directories": skipped_directories,
                        "candidates_checked": len(seen_paths),
                        "models_found": len(models),
                    }
                )

    models.sort(
        key=lambda item: (
            0 if item["compatibility"].get("accepted") else 1,
            0 if item.get("already_imported") else 1,
            item["name"].lower(),
        )
    )
    payload = {
        "models": models,
        "compatible_model_count": compatible_count,
        "scanned_root_count": len(scanned_roots),
        "scanned_roots": scanned_roots,
        "missing_roots": missing_roots,
        "directories_checked": directories_checked,
        "skipped_directories": skipped_directories,
        "truncated": truncated,
        "scan_duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }
    if cache_ttl > 0:
        with _MODEL_DISCOVERY_CACHE_LOCK:
            _MODEL_DISCOVERY_CACHE[cache_key] = {
                "stored_at": time.monotonic(),
                "payload": dict(payload),
            }
    return payload


def installed_model_scan_roots() -> list[Path]:
    return [root for root, _depth in installed_model_scan_locations()]


def installed_model_scan_locations(*, scan_all_drives: bool = False) -> list[tuple[Path, int]]:
    settings = get_settings()
    configured_depth = max(0, int(settings.model_scan_max_depth))
    locations: list[tuple[Path, int]] = [(models_dir(), configured_depth)]
    explicit = str(getattr(settings, "model_scan_roots", "") or "")
    for raw in explicit.split(os.pathsep):
        text = raw.strip()
        if text:
            locations.append((Path(text).expanduser(), configured_depth))

    if not explicit.strip():
        home = Path.home()
        user_profile = Path(os.environ.get("USERPROFILE", str(home)))
        local_appdata = Path(os.environ.get("LOCALAPPDATA", ""))
        appdata = Path(os.environ.get("APPDATA", ""))
        defaults = [
            home / ".cache" / "huggingface" / "hub",
            home / ".cache" / "lm-studio" / "models",
            home / ".lmstudio" / "models",
            user_profile / ".cache" / "huggingface" / "hub",
            user_profile / ".cache" / "lm-studio" / "models",
            local_appdata / "HuggingFace" / "hub",
            local_appdata / "lm-studio" / "models",
            appdata / "LM Studio" / "models",
        ]
        locations.extend((path, configured_depth) for path in defaults if str(path))
    state = registry_state()
    approved = state.get("approved_scan_roots")
    if isinstance(approved, list):
        locations.extend(
            (Path(str(path)).expanduser(), configured_depth)
            for path in approved
            if str(path).strip()
        )
    downloaded_paths = state.get("downloaded_model_paths")
    if isinstance(downloaded_paths, dict):
        for value in downloaded_paths.values():
            model_path = Path(str(value))
            if str(value).strip() and len(model_path.parents) >= 2:
                locations.append((model_path.parents[1], configured_depth))
    if scan_all_drives:
        locations.extend((root, -1) for root in _available_drive_roots())

    unique: list[tuple[Path, int]] = []
    seen: set[str] = set()
    for root, depth in locations:
        normalized = _normalized_path(root)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append((root, depth))
    return unique


def _available_drive_roots() -> list[Path]:
    if platform.system().casefold() == "windows":
        try:
            mask = int(ctypes.windll.kernel32.GetLogicalDrives())
        except Exception:
            mask = 0
        return [
            Path(f"{chr(ord('A') + index)}:\\")
            for index in range(26)
            if mask & (1 << index)
        ]
    try:
        import psutil

        roots = {
            Path(str(partition.mountpoint))
            for partition in psutil.disk_partitions(all=False)
            if str(partition.mountpoint).strip()
        }
        return sorted(roots, key=lambda item: str(item))
    except Exception:
        return [Path("/")]


def _download_root_for_target(target_dir: str | None) -> Path:
    raw = str(target_dir or "").strip()
    root = Path(raw).expanduser() if raw else models_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _model_disk_preflight(model: LocalModel, *, target_root: Path | None = None) -> dict[str, Any]:
    target_dir = (target_root or models_dir()) / model.id
    probe = target_dir if target_dir.exists() else _nearest_existing_parent(target_dir)
    required_bytes = int(model.approximate_download_gb * 1024 * 1024 * 1024 * 1.075)
    usage = shutil.disk_usage(probe)
    ok = int(usage.free) >= required_bytes
    return {
        "ok": ok,
        "message": (
            "Enough disk space is available."
            if ok
            else f"Not enough disk space is available for {model.name}."
        ),
    }


def _runtime_ready(runtime: dict[str, Any]) -> bool:
    return bool(
        runtime.get("available")
        or any("Will defer live smoke" in str(issue) for issue in runtime.get("issues", []))
    )


def _read_transformers_config(path: Path) -> dict[str, Any]:
    config_path = path / "config.json"
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _detect_approved_family(config: dict[str, Any], *, registered_family: str, model_path: str) -> ApprovedModelFamily | None:
    if registered_family:
        family = approved_family(registered_family)
        if family:
            return family
    repo_hint = str(config.get("_name_or_path") or config.get("name_or_path") or model_path).lower()
    model_type = str(config.get("model_type") or "").lower()
    architectures = [str(item).lower() for item in (config.get("architectures") or []) if item]
    file_name_hint = Path(model_path).name.lower()
    for family in APPROVED_MODEL_FAMILIES:
        if family.id in file_name_hint:
            return family
        if any(repo_hint.startswith(prefix) or prefix in repo_hint for prefix in family.repo_prefixes):
            return family
        if any(model_type.startswith(prefix) for prefix in family.model_type_prefixes):
            return family
        if any(any(keyword in architecture for keyword in family.architecture_keywords) for architecture in architectures):
            return family
    return None


def _hardware_supports_family(family: ApprovedModelFamily, hardware: dict[str, Any]) -> bool:
    tier = str(hardware.get("hardware_tier") or "unknown")
    rank = {"unsupported": 0, "unknown": 0, "cpu_minimum_spec": 1, "cpu_high_spec": 2, "gpu_or_high_spec_candidate": 3}
    return rank.get(tier, 0) >= rank.get(family.minimum_hardware_tier, 99)


def _safe_import_dir_name(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", name.strip()).strip("-_.").lower()
    return slug or "imported-model"


def _nearest_existing_parent(path: Path) -> Path:
    current = path
    while not current.exists():
        parent = current.parent
        if parent == current:
            return Path.cwd()
        current = parent
    return current


def _find_local_model_file(model: LocalModel) -> Path | None:
    pattern = f"*{model.quantization.lower()}*.gguf"
    repo_dir = models_dir() / model.id
    if repo_dir.exists():
        matches = sorted(repo_dir.glob(pattern))
        if matches:
            return matches[0]
    return _downloaded_model_path_from_registry(model.id)


def _iter_model_candidates(root: Path, *, max_depth: int) -> list[Path]:
    return _iter_model_candidates_with_progress(root, max_depth=max_depth)


def _iter_model_candidates_with_progress(
    root: Path,
    *,
    max_depth: int,
    progress_callback: Any | None = None,
    cancellation_callback: Any | None = None,
) -> list[Path]:
    discovered: list[Path] = []
    stack: list[tuple[Path, int]] = [(root, 0)]
    seen: set[str] = set()
    checked_since_report = 0
    skipped_since_report = 0

    def report(*, force: bool = False) -> None:
        nonlocal checked_since_report, skipped_since_report
        if progress_callback is None or (not force and checked_since_report < 250):
            return
        progress_callback(
            {
                "directories_checked": checked_since_report,
                "skipped_directories": skipped_since_report,
            }
        )
        checked_since_report = 0
        skipped_since_report = 0

    while stack:
        if cancellation_callback is not None and len(seen) % 100 == 0:
            cancellation_callback()
        current, depth = stack.pop()
        normalized = _normalized_path(current)
        if normalized in seen:
            continue
        seen.add(normalized)
        checked_since_report += 1
        report()
        if not current.exists() or not current.is_dir():
            skipped_since_report += 1
            continue
        if _is_transformers_model_dir(current):
            discovered.append(current)
            continue
        if max_depth >= 0 and depth >= max_depth:
            continue
        try:
            entries = sorted(current.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            skipped_since_report += 1
            continue
        for entry in entries:
            if entry.is_file() and entry.suffix.casefold() == ".gguf":
                discovered.append(entry)
        children = [entry for entry in entries if entry.is_dir()]
        for child in reversed(children):
            if child.name.lower() in MODEL_SCAN_SKIP_DIRS:
                skipped_since_report += 1
                continue
            stack.append((child, depth + 1))
    report(force=True)
    return discovered


def _iter_transformers_checkpoint_dirs(root: Path, *, max_depth: int) -> list[Path]:
    """Compatibility wrapper retained for diagnostics that only inspect directories."""
    return [
        candidate
        for candidate in _iter_model_candidates(root, max_depth=max_depth)
        if candidate.is_dir()
    ]


def _discovered_model_metadata(candidate: Path, *, compatibility: dict[str, Any], root: Path) -> dict[str, Any]:
    config = _read_transformers_config(candidate)
    name_or_path = str(config.get("_name_or_path") or config.get("name_or_path") or "").strip()
    display_name = _display_model_name(candidate, name_or_path=name_or_path, family=compatibility.get("family_name") or "")
    return {
        "id": f"discovered-{hashlib.sha1(str(candidate.resolve()).encode('utf-8')).hexdigest()[:12]}",
        "name": display_name,
        "family": str(compatibility.get("family") or ""),
        "family_name": str(compatibility.get("family_name") or ""),
        "local_path": str(candidate.resolve()),
        "source_root": str(root),
        "source_kind": "discovered_checkpoint",
        "already_imported": False,
        "compatibility": compatibility,
        "detail": str(compatibility.get("detail") or ""),
    }


def _display_model_name(candidate: Path, *, name_or_path: str, family: str) -> str:
    if name_or_path:
        label = name_or_path.replace("\\", "/").rstrip("/").split("/")[-1]
        if label:
            return label
    if family:
        return f"{family} ({candidate.name})"
    return candidate.name


def _normalized_path(path: Path) -> str:
    try:
        return str(path.expanduser().resolve(strict=False)).lower()
    except OSError:
        return str(path).lower()


def _paths_overlap(first: Path, second: Path) -> bool:
    try:
        first_path = str(first.expanduser().resolve(strict=False)).lower()
        second_path = str(second.expanduser().resolve(strict=False)).lower()
        common = os.path.commonpath([first_path, second_path])
    except (OSError, ValueError):
        return False
    return common in {first_path, second_path}


def _download_model_with_ack(
    model: LocalModel,
    target_root: Path | None,
    done_event: threading.Event,
) -> None:
    try:
        _download_model(model, target_root)
    finally:
        with _download_lock:
            _download_responses.pop(model.id, None)
            _download_threads.pop(model.id, None)
            _download_done_events.pop(model.id, None)
        done_event.set()


def _download_model(model: LocalModel, target_root: Path | None = None) -> None:
    try:
        _raise_if_cancelled(model.id)
        expected_sha256 = _download_expected_model_sha256(model)
        if not expected_sha256:
            raise RuntimeError(
                f"Managed model integrity pin is missing for {model.id}; refusing to download without a trusted SHA-256."
            )
        file_name = _resolve_gguf_filename(model)
        _raise_if_cancelled(model.id)
        safe_file_name = _safe_model_file_name(file_name)
        revision = _trusted_manifest_revision(model) or "main"
        url = (
            f"https://huggingface.co/{model.hf_repo}/resolve/"
            f"{quote(revision, safe='')}/{quote(file_name, safe='')}"
        )
        validate_huggingface_url(url)
        target_dir = (target_root or models_dir()) / model.id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / safe_file_name
        partial = target.with_suffix(target.suffix + ".part")
        partial_metadata = partial.with_suffix(partial.suffix + ".json")

        with _download_lock:
            _download_state[model.id].update(
                {
                    "status": "downloading",
                    "file_name": safe_file_name,
                    "local_path": str(target),
                    "partial_path": str(partial),
                    "updated_at": utc_now(),
                }
            )
            _persist_download_state_locked()

        resume_metadata = _read_partial_metadata(partial_metadata)
        resume_identity = {
            "url": url,
            "expected_sha256": expected_sha256.lower(),
            "file_name": safe_file_name,
        }
        if partial.is_file() and not all(
            resume_metadata.get(key) == value for key, value in resume_identity.items()
        ):
            _quarantine_stale_partial(partial, partial_metadata)
            resume_metadata = {}
        existing_bytes = partial.stat().st_size if partial.is_file() else 0
        headers = {"User-Agent": "CML-local-backend/0.1"}
        if existing_bytes > 0:
            headers["Range"] = f"bytes={existing_bytes}-"
            if resume_metadata.get("etag"):
                headers["If-Range"] = str(resume_metadata["etag"])
        request = Request(url, headers=headers)
        with urlopen(request, timeout=30) as response:
            with _download_lock:
                _download_responses[model.id] = response
            response_status = int(getattr(response, "status", 200) or 200)
            resumed = existing_bytes > 0 and response_status == 206
            content_range = response.headers.get("Content-Range") or ""
            if resumed:
                range_match = re.match(r"bytes\s+(\d+)-\d+/(\d+|\*)", content_range, re.IGNORECASE)
                if range_match is None or int(range_match.group(1)) != existing_bytes:
                    _quarantine_stale_partial(partial, partial_metadata)
                    raise RuntimeError("The model host returned an invalid resume range. Retry to start a clean download.")
            response_etag = response.headers.get("ETag") or response.headers.get("Etag")
            prior_etag = resume_metadata.get("etag")
            if resumed and prior_etag and response_etag and str(prior_etag) != str(response_etag):
                _quarantine_stale_partial(partial, partial_metadata)
                raise RuntimeError("The model file changed while resuming. Retry to start a verified clean download.")
            range_total = content_range.rsplit("/", 1)[-1] if "/" in content_range else ""
            content_length = response.headers.get("Content-Length")
            if range_total.isdigit():
                total_bytes = int(range_total)
            elif content_length and content_length.isdigit():
                total_bytes = int(content_length) + (existing_bytes if resumed else 0)
            else:
                total_bytes = None
            downloaded = existing_bytes if resumed else 0
            _write_partial_metadata(
                partial_metadata,
                {
                    **resume_identity,
                    "etag": response_etag,
                    "total_bytes": total_bytes,
                    "updated_at": utc_now(),
                },
            )
            started_monotonic = time.monotonic()
            with partial.open("ab" if resumed else "wb") as file:
                chunks_since_disk_check = 0
                while True:
                    _raise_if_cancelled(model.id)
                    chunk = response.read(1024 * 1024)
                    _raise_if_cancelled(model.id)
                    if not chunk:
                        break
                    file.write(chunk)
                    downloaded += len(chunk)
                    chunks_since_disk_check += 1
                    if chunks_since_disk_check >= 32:
                        _ensure_download_disk_space(partial.parent, downloaded, total_bytes)
                        chunks_since_disk_check = 0
                    _update_model_download_progress(
                        model.id,
                        downloaded,
                        total_bytes,
                        started_monotonic,
                        initial_bytes=existing_bytes if resumed else 0,
                    )
        actual_sha256 = _sha256_file(partial)
        if actual_sha256.lower() != expected_sha256.lower():
            raise RuntimeError(
                f"Model integrity check failed for {safe_file_name}: expected {expected_sha256}, got {actual_sha256}"
            )
        partial.replace(target)
        partial_metadata.unlink(missing_ok=True)
        _write_integrity_manifest(model, target, actual_sha256)
        _record_downloaded_model_path(model.id, target)
        with _download_lock:
            _download_state[model.id].update(
                {
                    "status": "installed",
                    "bytes_downloaded": target.stat().st_size,
                    "bytes_total": target.stat().st_size,
                    "total_bytes": target.stat().st_size,
                    "progress_percent": 100.0,
                    "download_speed_bps": None,
                    "eta_seconds": 0,
                    "local_path": str(target),
                    "sha256": actual_sha256,
                    "integrity_status": "verified",
                    "updated_at": utc_now(),
                }
            )
            _persist_download_state_locked()
    except Exception as exc:
        with _download_lock:
            cancelled = model.id in _cancelled_downloads
        if isinstance(exc, DownloadCancelled) or cancelled:
            _cleanup_partial_download(model)
            with _download_lock:
                _cancelled_downloads.discard(model.id)
                _download_state[model.id].update(
                    {
                        "status": "cancelled",
                        "error": None,
                        "download_speed_bps": None,
                        "cancellation_acknowledged_at": utc_now(),
                        "updated_at": utc_now(),
                    }
                )
                _persist_download_state_locked()
            return
        with _download_lock:
            _download_state[model.id].update({"status": "failed", "error": str(exc), "updated_at": utc_now()})
            _persist_download_state_locked()


def _update_model_download_progress(
    model_id: str,
    downloaded: int,
    total: int | None,
    started_monotonic: float,
    *,
    initial_bytes: int = 0,
) -> None:
    elapsed = max(0.001, time.monotonic() - started_monotonic)
    transferred = max(0, downloaded - initial_bytes)
    speed = int(transferred / elapsed) if transferred > 0 else None
    percent = None
    eta = None
    if total and total > 0:
        percent = round(min(100.0, (downloaded / total) * 100.0), 2)
        if speed:
            eta = max(0, int((total - downloaded) / speed))
    with _download_lock:
        _download_state[model_id].update(
            {
                "bytes_downloaded": downloaded,
                "bytes_total": total,
                "total_bytes": total,
                "progress_percent": percent,
                "download_speed_bps": speed,
                "eta_seconds": eta,
                "heartbeat_at": utc_now(),
                "updated_at": utc_now(),
            }
        )
        _persist_download_state_locked(throttle_seconds=0.25)


def _normalized_download_state(state: dict[str, Any]) -> dict[str, Any]:
    payload = dict(state)
    payload.setdefault("bytes_total", payload.get("total_bytes"))
    payload.setdefault("total_bytes", payload.get("bytes_total"))
    downloaded = payload.get("bytes_downloaded") or 0
    total = payload.get("bytes_total") or payload.get("total_bytes")
    payload["bytes_downloaded"] = downloaded
    if total and payload.get("progress_percent") is None:
        payload["progress_percent"] = round(min(100.0, (downloaded / total) * 100.0), 2)
    payload.setdefault("download_speed_bps", None)
    payload.setdefault("eta_seconds", None)
    payload.setdefault("started_at", None)
    payload.setdefault("updated_at", None)
    payload.setdefault("sha256", None)
    payload.setdefault("integrity_status", None)
    payload.setdefault("heartbeat_at", payload.get("updated_at"))
    payload.setdefault("cancellation_acknowledged_at", None)
    payload.setdefault("resumable", bool(payload.get("partial_path")))
    return payload


def _installed_download_state(model_id: str, local_path: Path) -> dict[str, Any]:
    size = local_path.stat().st_size
    return {
        "model_id": model_id,
        "status": "installed",
        "local_path": str(local_path),
        "bytes_downloaded": size,
        "bytes_total": size,
        "total_bytes": size,
        "progress_percent": 100.0,
        "download_speed_bps": None,
        "eta_seconds": 0,
        "error": None,
        "started_at": None,
        "updated_at": utc_now(),
    }


def _failed_model_download_state(model_id: str, error: str) -> dict[str, Any]:
    return {
        "model_id": model_id,
        "status": "failed",
        "bytes_downloaded": 0,
        "bytes_total": None,
        "total_bytes": None,
        "progress_percent": None,
        "download_speed_bps": None,
        "eta_seconds": None,
        "error": error,
        "started_at": utc_now(),
        "updated_at": utc_now(),
    }


def _downloaded_model_path_from_registry(model_id: str) -> Path | None:
    state = registry_state()
    downloaded_paths = state.get("downloaded_model_paths")
    if not isinstance(downloaded_paths, dict):
        return None
    return _existing_file_path(downloaded_paths.get(model_id))


def _existing_file_path(value: object) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    return path if path.is_file() else None


def _installed_state_from_local_path(model_id: str, state: dict[str, Any] | None) -> dict[str, Any] | None:
    if not state or not state.get("local_path"):
        return None
    local_path = Path(str(state["local_path"]))
    if not local_path.is_file():
        return None
    return _installed_download_state(model_id, local_path)


class DownloadCancelled(RuntimeError):
    pass


def _raise_if_cancelled(model_id: str) -> None:
    with _download_lock:
        if model_id in _cancelled_downloads:
            raise DownloadCancelled()


def _cleanup_partial_download(model: LocalModel) -> None:
    state = _download_state.get(model.id) or {}
    local_path = state.get("local_path")
    if not local_path:
        return
    partial = Path(str(local_path)).with_suffix(Path(str(local_path)).suffix + ".part")
    try:
        partial.unlink(missing_ok=True)
        partial.with_suffix(partial.suffix + ".json").unlink(missing_ok=True)
    except OSError:
        pass


def _read_partial_metadata(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_partial_metadata(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def _quarantine_stale_partial(partial: Path, metadata: Path) -> None:
    suffix = f".stale-{int(time.time())}"
    try:
        if partial.exists():
            partial.replace(partial.with_name(partial.name + suffix))
        if metadata.exists():
            metadata.replace(metadata.with_name(metadata.name + suffix))
    except OSError:
        partial.unlink(missing_ok=True)
        metadata.unlink(missing_ok=True)


def _ensure_download_disk_space(path: Path, downloaded: int, total: int | None) -> None:
    if not total or total <= downloaded:
        return
    remaining = total - downloaded
    reserve = 64 * 1024 * 1024
    if shutil.disk_usage(path).free < remaining + reserve:
        raise RuntimeError(
            "The selected drive ran out of safe free space during the model download. "
            "Free space or choose another location, then resume."
        )


def _resolve_gguf_filename(model: LocalModel) -> str:
    trusted_file_name = _trusted_manifest_file_name(model)
    if trusted_file_name:
        return trusted_file_name
    api_url = f"https://huggingface.co/api/models/{model.hf_repo}"
    validate_huggingface_url(api_url)
    request = Request(api_url, headers={"User-Agent": "CML-local-backend/0.1"})
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not resolve model files for {model.hf_repo}") from exc

    siblings = payload.get("siblings", [])
    quant = model.quantization.lower()
    candidates = [
        item.get("rfilename", "")
        for item in siblings
        if item.get("rfilename", "").lower().endswith(".gguf")
        and quant in item.get("rfilename", "").lower()
    ]
    if not candidates:
        raise RuntimeError(f"No {model.quantization} GGUF file found for {model.hf_repo}")
    return sorted(candidates, key=len)[0]


def _safe_model_file_name(file_name: str) -> str:
    name = Path(file_name).name
    if not name or name != file_name or not name.lower().endswith(".gguf"):
        raise RuntimeError("Resolved model filename was not safe")
    return name


def _expected_model_sha256(model: LocalModel) -> str:
    if model.expected_sha256:
        return model.expected_sha256
    trusted = _trusted_manifest_expected_sha256(model)
    if trusted:
        return trusted
    manifest = models_dir() / model.id / "integrity.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    expected = payload.get("expected_sha256", "")
    return expected if isinstance(expected, str) else ""


def _download_expected_model_sha256(model: LocalModel) -> str:
    if model.expected_sha256:
        return model.expected_sha256
    return _trusted_manifest_expected_sha256(model)


def _trusted_manifest_expected_sha256(model: LocalModel) -> str:
    entry = _trusted_manifest_model_entry(model)
    sha256 = entry.get("sha256") or entry.get("expected_sha256") or ""
    return sha256 if _is_sha256(str(sha256)) else ""


def _trusted_manifest_file_name(model: LocalModel) -> str:
    entry = _trusted_manifest_model_entry(model)
    file_name = str(entry.get("file_name") or "")
    if not file_name:
        return ""
    return _safe_model_file_name(file_name)


def _trusted_manifest_revision(model: LocalModel) -> str:
    revision = str(_trusted_manifest_model_entry(model).get("repo_commit") or "").strip()
    return revision if re.fullmatch(r"[0-9a-f]{40}", revision, flags=re.IGNORECASE) else ""


def _trusted_manifest_model_entry(model: LocalModel) -> dict[str, Any]:
    manifest = _trusted_integrity_manifest()
    models = manifest.get("models", {})
    if not isinstance(models, dict):
        return {}
    entry = models.get(model.id) or {}
    if not isinstance(entry, dict):
        return {}
    hf_repo = str(entry.get("hf_repo") or "")
    if hf_repo and hf_repo != model.hf_repo:
        return {}
    return entry


def _trusted_integrity_manifest() -> dict[str, Any]:
    settings = get_settings()
    if settings.model_integrity_manifest_url:
        return _read_remote_integrity_manifest(settings.model_integrity_manifest_url)
    if settings.model_integrity_manifest_path:
        return _read_local_integrity_manifest(settings.model_integrity_manifest_path)
    default_path = Path(__file__).resolve().parents[3] / "docs" / "model-integrity-manifest.json"
    return _read_local_integrity_manifest(default_path)


def _read_local_integrity_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"source": str(path), "models": {}}
    if not isinstance(payload, dict):
        return {"source": str(path), "models": {}}
    payload.setdefault("source", str(path))
    payload.setdefault("models", {})
    return payload


def _read_remote_integrity_manifest(url: str) -> dict[str, Any]:
    if not url.startswith("https://"):
        return {"source": url, "models": {}, "error": "Remote integrity manifests must use https."}
    request = Request(url, headers={"User-Agent": "CML-local-backend/0.1"})
    try:
        with urlopen(request, timeout=10) as response:
            raw = response.read(512 * 1024 + 1)
    except OSError as exc:
        return {"source": url, "models": {}, "error": str(exc)}
    if len(raw) > 512 * 1024:
        return {"source": url, "models": {}, "error": "Remote integrity manifest is too large."}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        return {"source": url, "models": {}, "error": str(exc)}
    if not isinstance(payload, dict):
        return {"source": url, "models": {}, "error": "Remote integrity manifest must be a JSON object."}
    payload.setdefault("source", url)
    payload.setdefault("models", {})
    return payload


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdefABCDEF" for char in value)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_integrity_manifest(model: LocalModel, target: Path, sha256: str) -> None:
    manifest = {
        "model_id": model.id,
        "file_name": target.name,
        "sha256": sha256,
        "expected_sha256": _expected_model_sha256(model),
        "status": "verified" if _expected_model_sha256(model) else "recorded",
        "updated_at": utc_now(),
    }
    (target.parent / "integrity.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _model_integrity_status(model: LocalModel, local_path: Path | None) -> dict[str, Any]:
    if local_path is None:
        return {"status": "missing", "sha256": None, "expected_sha256": _expected_model_sha256(model)}
    manifest = local_path.parent / "integrity.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "status": "unverified",
            "sha256": None,
            "expected_sha256": _expected_model_sha256(model),
            "detail": "No integrity manifest exists for this local model file.",
        }
    expected = str(payload.get("expected_sha256") or "")
    actual = str(payload.get("sha256") or "")
    if expected:
        status = "verified" if actual.lower() == expected.lower() else "mismatch"
    else:
        status = "recorded" if actual else "unverified"
    return {"status": status, "sha256": actual or None, "expected_sha256": expected or None}
