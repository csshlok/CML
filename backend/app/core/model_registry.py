from dataclasses import asdict, dataclass
import hashlib
import os
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
from backend.app.core.expert_runtime import _is_transformers_model_dir, runtime_dependency_status
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
        detail="Accepted when a local Llama Transformers checkpoint is present and expert runtime dependencies are available.",
    ),
    ApprovedModelFamily(
        id="qwen",
        name="Qwen",
        repo_prefixes=("qwen/",),
        model_type_prefixes=("qwen",),
        architecture_keywords=("qwen",),
        minimum_hardware_tier="cpu_minimum_spec",
        detail="Accepted when a local Qwen Transformers checkpoint is present and expert runtime dependencies are available.",
    ),
    ApprovedModelFamily(
        id="phi",
        name="Phi",
        repo_prefixes=("microsoft/phi-", "unsloth/phi-"),
        model_type_prefixes=("phi",),
        architecture_keywords=("phi",),
        minimum_hardware_tier="cpu_minimum_spec",
        detail="Accepted when a local Phi Transformers checkpoint is present and expert runtime dependencies are available.",
    ),
    ApprovedModelFamily(
        id="gemma",
        name="Gemma",
        repo_prefixes=("google/gemma", "gemma", "aldaris/gemma"),
        model_type_prefixes=("gemma",),
        architecture_keywords=("gemma",),
        minimum_hardware_tier="cpu_minimum_spec",
        detail="Accepted when a local Gemma Transformers checkpoint is present and expert runtime dependencies are available.",
    ),
)

_download_state: dict[str, dict[str, Any]] = {}
_download_lock = threading.Lock()
_cancelled_downloads: set[str] = set()
_MODEL_DISCOVERY_CACHE_LOCK = threading.Lock()
_MODEL_DISCOVERY_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
MODEL_SCAN_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "blobs",
    "node_modules",
    "refs",
    "tmp",
    "venv",
}


def models_dir() -> Path:
    settings = get_settings()
    path = settings.models_dir or settings.data_dir / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def imported_models_dir() -> Path:
    path = models_dir() / "imported"
    path.mkdir(parents=True, exist_ok=True)
    return path


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
    for metadata_path in sorted(imported_models_dir().glob("*/cml-model.json")):
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        model_id = str(payload.get("id") or "")
        local_path = str(payload.get("local_path") or "")
        family = str(payload.get("family") or "")
        compatibility = model_compatibility_report(local_path, registered_family=family)
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
                "installed": True,
                "local_path": local_path,
                "download": None,
                "integrity": {"status": "imported", "sha256": None, "expected_sha256": None},
                "active": state.get("active_chat_model_id") == model_id or state.get("active_expert_model_id") == model_id,
                "active_chat": state.get("active_chat_model_id") == model_id,
                "active_expert": state.get("active_expert_model_id") == model_id,
                "compatibility": compatibility,
                "source_kind": "custom_import",
            }
        )
    return rows


def invalidate_model_discovery_cache() -> None:
    with _MODEL_DISCOVERY_CACHE_LOCK:
        _MODEL_DISCOVERY_CACHE.clear()


def model_status(model_id: str) -> dict[str, Any]:
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
    info.update(
        {
            "installed": local_path is not None or state_installed_path is not None,
            "local_path": str(local_path) if local_path else state_installed_path,
            "download": state,
            "integrity": _model_integrity_status(model, local_path),
            "active": registry.get("active_chat_model_id") == model_id or registry.get("active_expert_model_id") == model_id,
            "active_chat": registry.get("active_chat_model_id") == model_id,
            "active_expert": registry.get("active_expert_model_id") == model_id,
            "compatibility": _default_model_compatibility(model, local_path),
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
        return {"active_chat_model_id": "", "active_expert_model_id": ""}
    if not isinstance(payload, dict):
        return {"active_chat_model_id": "", "active_expert_model_id": ""}
    legacy_active = str(payload.get("active_model_id") or "")
    payload.setdefault("active_chat_model_id", legacy_active)
    payload.setdefault("active_expert_model_id", legacy_active)
    return payload


def set_active_model(model_id: str, role: str = "chat") -> dict[str, Any]:
    if not any(item["id"] == model_id for item in list_models()):
        raise KeyError(model_id)
    row = next(item for item in list_models() if item["id"] == model_id)
    compatibility = row.get("compatibility") or {}
    role = (role or "chat").strip().lower()
    state = registry_state()
    if role == "chat":
        if not compatibility.get("chat_role_accepted"):
            raise ValueError("Model is not accepted for the chat role.")
        state["active_chat_model_id"] = model_id
    elif role == "expert":
        if not compatibility.get("expert_role_accepted"):
            raise ValueError("Model is not accepted for the expert role.")
        state["active_expert_model_id"] = model_id
    elif role == "pair":
        if not compatibility.get("chat_role_accepted") or not compatibility.get("expert_role_accepted"):
            raise ValueError("Model is not accepted for both chat and expert roles.")
        state["active_chat_model_id"] = model_id
        state["active_expert_model_id"] = model_id
    else:
        raise ValueError("Unknown model activation role.")
    state["updated_at"] = utc_now()
    registry_state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")
    for row in list_models():
        if row["id"] == model_id:
            return row
    raise KeyError(model_id)


def active_chat_model_status() -> dict[str, Any] | None:
    active_model_id = str(registry_state().get("active_chat_model_id") or "")
    if not active_model_id:
        return None
    return next((item for item in list_models() if item["id"] == active_model_id), None)


def active_expert_model_status() -> dict[str, Any] | None:
    active_model_id = str(registry_state().get("active_expert_model_id") or "")
    if not active_model_id:
        return None
    return next((item for item in list_models() if item["id"] == active_model_id), None)


def active_model_status() -> dict[str, Any] | None:
    return active_expert_model_status() or active_chat_model_status()


def model_recommendations() -> dict[str, Any]:
    hardware = hardware_module.hardware_status()
    tier = hardware.get("hardware_tier") or "unknown"
    if tier == "gpu_or_high_spec_candidate":
        preferred_id = "qwen3-8b-q4_k_m"
    elif tier == "cpu_minimum_spec":
        preferred_id = "qwen3-4b-q4_k_m"
    elif tier == "cpu_high_spec":
        preferred_id = "qwen3-8b-q4_k_m"
    else:
        preferred_id = "phi-4-mini-instruct-q4_k_m"
    ordered = sorted(
        list_models(),
        key=lambda item: (0 if item["id"] == preferred_id else 1, item["role"], item["name"]),
    )
    preferred_chat = next((item for item in ordered if item["id"] == preferred_id), None)
    current_pair = active_model_pair_status()
    discovered = discover_installed_models(max_results=12)
    return {
        "hardware": hardware,
        "recommended_model_id": preferred_id,
        "recommended_chat_model_id": preferred_id,
        "recommended_expert_family": preferred_chat.get("family") if preferred_chat else "",
        "active_pair": current_pair,
        "models": ordered,
        "detected_compatible_models": discovered["models"],
        "detected_compatible_model_count": discovered["compatible_model_count"],
        "detail": (
            f"Recommended chat model selection for hardware tier {tier}. "
            "Expert mode still requires a separate accepted local checkpoint."
        ),
    }


def active_model_pair_status() -> dict[str, Any]:
    chat_model = active_chat_model_status()
    expert_model = active_expert_model_status()
    chat_ok = bool(chat_model and (chat_model.get("compatibility") or {}).get("chat_role_accepted"))
    expert_ok = bool(expert_model and (expert_model.get("compatibility") or {}).get("expert_role_accepted"))
    accepted = chat_ok and expert_ok
    detail = (
        "Accepted chat/expert model pair is active."
        if accepted
        else "Select an accepted chat model and an accepted expert checkpoint to complete dual-model setup."
    )
    if accepted and chat_model and expert_model and chat_model.get("family") != expert_model.get("family"):
        detail = (
            "Accepted cross-family chat/expert pair is active. This is allowed because retrieval, not model memory, remains the citation authority."
        )
    return {
        "accepted": accepted,
        "chat_model_id": chat_model.get("id") if chat_model else "",
        "expert_model_id": expert_model.get("id") if expert_model else "",
        "detail": detail,
    }


def start_model_download(model_id: str) -> dict[str, Any]:
    model = get_model(model_id)
    if model is None:
        raise KeyError(model_id)

    existing = model_status(model_id)
    if existing["installed"]:
        return {"model_id": model_id, "status": "installed", "local_path": existing["local_path"]}

    disk_check = _model_disk_preflight(model)
    if not disk_check["ok"]:
        state = {
            "model_id": model_id,
            "status": "failed",
            "bytes_downloaded": 0,
            "bytes_total": None,
            "total_bytes": None,
            "progress_percent": None,
            "download_speed_bps": None,
            "eta_seconds": None,
            "error": disk_check["message"],
            "started_at": utc_now(),
            "updated_at": utc_now(),
        }
        with _download_lock:
            _download_state[model_id] = state
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

    thread = threading.Thread(target=_download_model, args=(model,), daemon=True)
    thread.start()
    return _normalized_download_state(_download_state[model_id])


def cancel_model_download(model_id: str) -> dict[str, Any]:
    model = get_model(model_id)
    if model is None:
        raise KeyError(model_id)
    with _download_lock:
        state = _download_state.get(model_id)
        if state and state.get("status") == "installed":
            return state
        state_local_path = _installed_state_from_local_path(model_id, state)
        if state_local_path is not None:
            _download_state[model_id] = state_local_path
            _cancelled_downloads.discard(model_id)
            return state_local_path
        local_path = _find_local_model_file(model)
        if local_path is not None:
            installed = _installed_download_state(model_id, local_path)
            _download_state[model_id] = installed
            _cancelled_downloads.discard(model_id)
            return installed
        if not state or state.get("status") not in {"resolving", "downloading"}:
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
            return _download_state[model_id]
        _cancelled_downloads.add(model_id)
        state.update({"status": "cancelling", "updated_at": utc_now()})
        return state


def _model_to_dict(model: LocalModel) -> dict[str, Any]:
    info = asdict(model)
    info["llama_cpp_ref"] = f"{model.hf_repo}:{model.quantization}"
    return info


def _missing_model_compatibility(family_id: str, notes: str = "") -> dict[str, Any]:
    family = approved_family(family_id)
    return {
        "status": "rejected",
        "accepted": False,
        "chat_role_accepted": False,
        "expert_role_accepted": False,
        "accepted_roles": [],
        "family": family_id,
        "family_name": family.name if family else family_id,
        "model_type": "",
        "architecture": "",
        "registered_family": family_id,
        "local_path": "",
        "runtime_dependencies": runtime_dependency_status(),
        "hardware": hardware_module.hardware_status(),
        "reasons": [
            "No compatible local Transformers checkpoint is installed for this model family."
        ],
        "pairing_detail": "A separate approved expert checkpoint is required for expert workflows.",
        "detail": notes or "Install or import a compatible local Transformers checkpoint to enable expert features.",
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
        "expert_role_accepted": False,
        "accepted_roles": ["chat"],
        "family": model.family,
        "family_name": family.name if family else model.family,
        "model_type": "gguf",
        "architecture": "",
        "registered_family": model.family,
        "local_path": str(local_path),
        "runtime_dependencies": runtime_dependency_status(),
        "hardware": hardware,
        "reasons": [],
        "pairing_detail": "Accepted for chat. Pair this with an approved expert checkpoint for expert workflows.",
        "detail": "Accepted local chat runtime model. A separate approved expert checkpoint is still required for expert workflows.",
    }


def model_compatibility_report(model_path: str | Path, *, registered_family: str = "") -> dict[str, Any]:
    target = Path(model_path) if str(model_path).strip() else Path("")
    runtime = runtime_dependency_status()
    hardware = hardware_module.hardware_status()
    reasons: list[str] = []
    config = _read_transformers_config(target)
    family = _detect_approved_family(config, registered_family=registered_family, model_path=str(target))
    model_type = str(config.get("model_type") or "")
    architectures = config.get("architectures") or []
    architecture = str(architectures[0] if isinstance(architectures, list) and architectures else "")

    if not model_path or not str(model_path).strip():
        reasons.append("Model path is required.")
    elif not target.exists():
        reasons.append("Model path does not exist.")
    elif not target.is_dir():
        reasons.append("Model path must point to a local Transformers checkpoint directory.")
    elif not _is_transformers_model_dir(target):
        reasons.append("Checkpoint directory is missing config/tokenizer files required by the expert runtime.")
    if not family:
        reasons.append("Model family is not in the approved Qwen/Phi/Gemma set.")
    if not _runtime_ready(runtime):
        reasons.append("Expert runtime dependencies are not available.")
    if family and not _hardware_supports_family(family, hardware):
        reasons.append(f"Current hardware tier does not satisfy the minimum contract for the {family.name} family.")

    expert_role_accepted = not reasons
    accepted_roles = ["expert"] if expert_role_accepted else []
    return {
        "status": "accepted" if expert_role_accepted else "rejected",
        "accepted": expert_role_accepted,
        "chat_role_accepted": False,
        "expert_role_accepted": expert_role_accepted,
        "accepted_roles": accepted_roles,
        "family": family.id if family else "",
        "family_name": family.name if family else "",
        "model_type": model_type,
        "architecture": architecture,
        "registered_family": registered_family,
        "local_path": str(target) if str(model_path).strip() else "",
        "runtime_dependencies": runtime,
        "hardware": hardware,
        "reasons": reasons,
        "pairing_detail": (
            "Accepted for the expert role. Pair this checkpoint with any accepted chat runtime model; retrieval remains the citation authority."
            if expert_role_accepted and family
            else "Rejected for the expert role."
        ),
        "detail": (
            f"Accepted local {family.name} checkpoint for Vault and LoRA expert runtime."
            if expert_role_accepted and family
            else "; ".join(reasons)
        ),
    }


def import_model_checkpoint(source_path: str | Path, *, name: str | None = None) -> dict[str, Any]:
    source_dir = Path(source_path).resolve()
    report = model_compatibility_report(source_dir)
    if not report["accepted"]:
        raise ValueError(report["detail"])
    family = report["family"]
    destination_name = _safe_import_dir_name(name or source_dir.name or family)
    destination = imported_models_dir() / destination_name
    if _paths_overlap(source_dir, destination):
        raise ValueError("Imported checkpoint source and managed destination must be separate directories.")
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source_dir, destination)
    model_id = f"custom-{destination_name}"
    metadata = {
        "id": model_id,
        "name": name or source_dir.name or destination_name,
        "family": family,
        "local_path": str(destination),
        "source_path": str(source_dir),
        "hf_repo": "",
        "notes": "Imported local checkpoint.",
        "recommended_ram_gb": "",
        "created_at": utc_now(),
    }
    (destination / "cml-model.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    invalidate_model_discovery_cache()
    if not active_expert_model_status():
        set_active_model(model_id, role="expert")
    return next(item for item in imported_model_statuses() if item["id"] == model_id)


def preferred_expert_base_model() -> dict[str, Any] | None:
    active = active_expert_model_status()
    if active and (active.get("compatibility") or {}).get("accepted"):
        return active

    for item in imported_model_statuses():
        if (item.get("compatibility") or {}).get("accepted"):
            return item

    from backend.app.core.expert_runtime import local_model_search_roots

    for root in local_model_search_roots():
        if not root.exists():
            continue
        for candidate in sorted(root.glob("*")):
            if not candidate.is_dir():
                continue
            compatibility = model_compatibility_report(candidate)
            if compatibility.get("accepted"):
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
) -> dict[str, Any]:
    settings = get_settings()
    roots = installed_model_scan_roots()
    cache_ttl = max(0, int(getattr(settings, "model_scan_cache_seconds", 30) or 0))
    cache_key = (
        tuple(_normalized_path(root) for root in roots),
        int(settings.model_scan_max_depth),
        bool(include_rejected),
        int(max_results),
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
    imported_paths = {item["local_path"] for item in imported_model_statuses()}

    for root in roots:
        normalized_root = _normalized_path(root)
        if normalized_root in scanned_roots:
            continue
        if not root.exists():
            missing_roots.append(str(root))
            continue
        scanned_roots.append(normalized_root)
        for candidate in _iter_transformers_checkpoint_dirs(root, max_depth=int(settings.model_scan_max_depth)):
            normalized = _normalized_path(candidate)
            if normalized in seen_paths:
                continue
            seen_paths.add(normalized)
            compatibility = model_compatibility_report(candidate)
            if compatibility.get("accepted"):
                compatible_count += 1
            if not include_rejected and not compatibility.get("accepted"):
                continue
            metadata = _discovered_model_metadata(candidate, compatibility=compatibility, root=root)
            if metadata["local_path"] in imported_paths:
                metadata["already_imported"] = True
            models.append(metadata)
            if len(models) >= max_results:
                truncated = True
                break
        if truncated:
            break

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
    settings = get_settings()
    roots: list[Path] = []
    explicit = str(getattr(settings, "model_scan_roots", "") or "")
    for raw in explicit.split(os.pathsep):
        text = raw.strip()
        if text:
            roots.append(Path(text).expanduser())

    from backend.app.core.expert_runtime import local_model_search_roots

    roots.extend(local_model_search_roots())

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
    roots.extend(path for path in defaults if str(path))
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        normalized = _normalized_path(root)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(root)
    return unique


def _model_disk_preflight(model: LocalModel) -> dict[str, Any]:
    target_dir = models_dir() / model.id
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
    for family in APPROVED_MODEL_FAMILIES:
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
    if not repo_dir.exists():
        return None
    matches = sorted(repo_dir.glob(pattern))
    return matches[0] if matches else None


def _iter_transformers_checkpoint_dirs(root: Path, *, max_depth: int) -> list[Path]:
    discovered: list[Path] = []
    stack: list[tuple[Path, int]] = [(root, 0)]
    seen: set[str] = set()
    while stack:
        current, depth = stack.pop()
        normalized = _normalized_path(current)
        if normalized in seen:
            continue
        seen.add(normalized)
        if not current.exists() or not current.is_dir():
            continue
        if _is_transformers_model_dir(current):
            discovered.append(current)
            continue
        if depth >= max_depth:
            continue
        try:
            children = sorted(
                (entry for entry in current.iterdir() if entry.is_dir()),
                key=lambda item: item.name.lower(),
            )
        except OSError:
            continue
        for child in reversed(children):
            if child.name.lower() in MODEL_SCAN_SKIP_DIRS:
                continue
            stack.append((child, depth + 1))
    return discovered


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


def _download_model(model: LocalModel) -> None:
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
        url = f"https://huggingface.co/{model.hf_repo}/resolve/main/{quote(file_name, safe='')}"
        validate_huggingface_url(url)
        target_dir = models_dir() / model.id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / safe_file_name
        partial = target.with_suffix(target.suffix + ".part")

        with _download_lock:
            _download_state[model.id].update(
                {
                    "status": "downloading",
                    "file_name": safe_file_name,
                    "local_path": str(target),
                    "updated_at": utc_now(),
                }
            )

        request = Request(url, headers={"User-Agent": "CML-local-backend/0.1"})
        with urlopen(request, timeout=30) as response:
            total = response.headers.get("Content-Length")
            total_bytes = int(total) if total and total.isdigit() else None
            downloaded = 0
            started_monotonic = time.monotonic()
            with partial.open("wb") as file:
                while True:
                    _raise_if_cancelled(model.id)
                    chunk = response.read(1024 * 1024)
                    _raise_if_cancelled(model.id)
                    if not chunk:
                        break
                    file.write(chunk)
                    downloaded += len(chunk)
                    _update_model_download_progress(model.id, downloaded, total_bytes, started_monotonic)
        actual_sha256 = _sha256_file(partial)
        if actual_sha256.lower() != expected_sha256.lower():
            raise RuntimeError(
                f"Model integrity check failed for {safe_file_name}: expected {expected_sha256}, got {actual_sha256}"
            )
        partial.replace(target)
        _write_integrity_manifest(model, target, actual_sha256)
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
    except Exception as exc:
        if isinstance(exc, DownloadCancelled):
            _cleanup_partial_download(model)
            with _download_lock:
                _cancelled_downloads.discard(model.id)
                _download_state[model.id].update({"status": "cancelled", "error": None, "updated_at": utc_now()})
            return
        with _download_lock:
            _download_state[model.id].update({"status": "failed", "error": str(exc), "updated_at": utc_now()})


def _update_model_download_progress(model_id: str, downloaded: int, total: int | None, started_monotonic: float) -> None:
    elapsed = max(0.001, time.monotonic() - started_monotonic)
    speed = int(downloaded / elapsed) if downloaded > 0 else None
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
                "updated_at": utc_now(),
            }
        )


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
    except OSError:
        pass


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
