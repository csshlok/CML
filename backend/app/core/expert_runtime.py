import json
import logging
import os
import subprocess
import sys
import tempfile
from importlib import metadata
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from backend.app.core.config import ROOT_DIR, get_settings
from backend.app.core.database import dict_from_row
from backend.app.core.lora_training import adapter_validation_report

LOGGER = logging.getLogger(__name__)
MODEL_CONFIG_FILES = ("config.json", "tokenizer_config.json", "tokenizer.json")


def runtime_adapter_load_plan(*, adapter_path: str | Path, base_model: str) -> dict:
    adapter_dir = Path(adapter_path)
    validation = adapter_validation_report(adapter_dir)
    metadata_report = adapter_metadata_report(adapter_dir)
    resolved_model = resolve_local_base_model(base_model, adapter_dir=adapter_dir)
    dependency_status = runtime_dependency_status()
    dependency_ready = bool(
        dependency_status["available"] or dependency_status["runtime_python"] != sys.executable
    )
    available = bool(validation["valid"] and resolved_model["available"] and dependency_ready)
    failure_code = ""
    if not validation["valid"]:
        failure_code = "adapter_invalid"
    elif not resolved_model["available"] or not dependency_ready:
        failure_code = "runtime_load_failed"
    detail_parts: list[str] = []
    if validation["valid"]:
        detail_parts.append("Adapter artifacts validated.")
    else:
        detail_parts.append(f"Adapter validation failed: {', '.join(validation['errors'])}")
    if resolved_model["available"]:
        detail_parts.append(f"Resolved local base model at {resolved_model['base_model_path']}.")
    else:
        detail_parts.append(resolved_model["detail"])
    if dependency_status["available"]:
        detail_parts.append("Runtime dependencies are importable in the active backend environment.")
    elif dependency_ready:
        detail_parts.append(f"Live runtime smoke can use {dependency_status['runtime_python']}.")
    else:
        detail_parts.append("Install peft, transformers, and torch or configure CML_LORA_RUNTIME_PYTHON.")
    return {
        "available": available,
        "runtime": "transformers-peft-local",
        "adapter_path": str(adapter_dir),
        "base_model": base_model,
        "base_model_path": resolved_model.get("base_model_path"),
        "failure_code": failure_code,
        "detail": " ".join(detail_parts),
        "validation": validation,
        "adapter_metadata": metadata_report,
        "resolved_base_model": resolved_model,
        "runtime_dependencies": dependency_status,
        "smoke_command": [
            runtime_python_executable(),
            "-m",
            "backend.app.core.expert_runtime_worker",
            "<payload.json>",
        ],
    }


def adapter_metadata_report(adapter_path: str | Path) -> dict:
    adapter_dir = Path(adapter_path)
    config_path = adapter_dir / "adapter_config.json"
    result: dict[str, Any] = {
        "adapter_path": str(adapter_dir),
        "config_path": str(config_path),
        "available": False,
        "base_model_name_or_path": "",
        "peft_type": "",
        "task_type": "",
        "peft_version": "",
        "target_modules": [],
        "warnings": [],
    }
    if not config_path.exists():
        result["warnings"].append("adapter_config.json is missing.")
        return result
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        result["warnings"].append("adapter_config.json is not valid JSON.")
        return result
    if not isinstance(payload, dict):
        result["warnings"].append("adapter_config.json must contain an object.")
        return result
    result["available"] = True
    result["base_model_name_or_path"] = str(payload.get("base_model_name_or_path") or "")
    result["peft_type"] = str(payload.get("peft_type") or "")
    result["task_type"] = str(payload.get("task_type") or "")
    result["peft_version"] = str(payload.get("peft_version") or "")
    target_modules = payload.get("target_modules") or []
    if isinstance(target_modules, list):
        result["target_modules"] = [str(item) for item in target_modules]
    elif target_modules:
        result["target_modules"] = [str(target_modules)]
    if not result["base_model_name_or_path"]:
        result["warnings"].append("Adapter metadata does not declare base_model_name_or_path.")
    return result


def runtime_dependency_status() -> dict:
    packages = {name: _package_status(name) for name in ("torch", "transformers", "peft")}
    runtime_python = runtime_python_executable()
    available = all(item["importable"] for item in packages.values())
    issues = []
    for name, status in packages.items():
        if not status["importable"]:
            issues.append(f"{name} is not importable")
    if not available and runtime_python != sys.executable:
        issues.append(f"Will defer live smoke to configured runtime python: {runtime_python}")
    return {
        "available": available,
        "runtime_python": runtime_python,
        "packages": packages,
        "issues": issues,
    }


def runtime_python_executable() -> str:
    settings = get_settings()
    configured = str(getattr(settings, "lora_runtime_python", "") or "").strip()
    return configured or sys.executable


def local_model_search_roots() -> list[Path]:
    settings = get_settings()
    roots: list[Path] = []
    extra_dirs = str(getattr(settings, "lora_model_dirs", "") or "")
    for raw in extra_dirs.split(os.pathsep):
        text = raw.strip()
        if text:
            roots.append(Path(text))
    if settings.models_dir:
        roots.append(settings.models_dir)
    roots.append(settings.data_dir / "models")
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            normalized = str(root.resolve(strict=False)).lower()
        except OSError:
            normalized = str(root).lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(root)
    return unique


def resolve_local_base_model(base_model: str, *, adapter_dir: str | Path | None = None) -> dict:
    adapter_metadata = adapter_metadata_report(adapter_dir) if adapter_dir else {}
    candidates = _base_model_candidate_strings(base_model, adapter_metadata)
    for candidate in candidates:
        direct_path = Path(candidate)
        if direct_path.exists() and _is_transformers_model_dir(direct_path):
            return {
                "available": True,
                "base_model": base_model,
                "base_model_path": str(direct_path.resolve()),
                "search_roots": [str(item) for item in local_model_search_roots()],
                "matched_by": "direct_path",
                "detail": "Resolved base model from direct filesystem path.",
            }
    for root in local_model_search_roots():
        if not root.exists():
            continue
        for match in _iter_model_dir_matches(root, candidates):
            return {
                "available": True,
                "base_model": base_model,
                "base_model_path": str(match.resolve()),
                "search_roots": [str(item) for item in local_model_search_roots()],
                "matched_by": "search_root",
                "detail": f"Resolved base model under configured model directory {root}.",
            }
    return {
        "available": False,
        "base_model": base_model,
        "base_model_path": None,
        "search_roots": [str(item) for item in local_model_search_roots()],
        "matched_by": "",
        "detail": (
            "No compatible local Transformers model directory was found for "
            f"{base_model or adapter_metadata.get('base_model_name_or_path') or 'the adapter'}."
        ),
    }


def run_adapter_runtime_smoke(
    *,
    adapter_path: str | Path,
    base_model: str,
    prompt: str | None = None,
    max_new_tokens: int | None = None,
) -> dict:
    adapter_dir = Path(adapter_path)
    plan = runtime_adapter_load_plan(adapter_path=adapter_dir, base_model=base_model)
    report = {
        "ok": False,
        "adapter_path": str(adapter_dir),
        "base_model": base_model,
        "plan": plan,
        "response_text": "",
        "error": "",
        "stdout": "",
        "stderr": "",
        "unloaded": False,
        "failure_code": plan.get("failure_code") or "",
    }
    if not plan["validation"]["valid"]:
        report["error"] = "; ".join(plan["validation"]["errors"])
        report["failure_code"] = "adapter_invalid"
        LOGGER.warning("Cluster expert runtime smoke rejected invalid adapter at %s", adapter_dir)
        return report
    if not plan["resolved_base_model"]["available"]:
        report["error"] = plan["resolved_base_model"]["detail"]
        report["failure_code"] = "runtime_load_failed"
        LOGGER.warning("Cluster expert runtime smoke could not resolve base model for %s", adapter_dir)
        return report

    with tempfile.TemporaryDirectory(prefix="cml-lora-smoke-") as temp_dir:
        payload_path = Path(temp_dir) / "payload.json"
        report_path = Path(temp_dir) / "report.json"
        payload = {
            "adapter_path": str(adapter_dir.resolve()),
            "base_model_path": str(plan["resolved_base_model"]["base_model_path"]),
            "prompt": prompt or getattr(get_settings(), "lora_runtime_prompt", "Reply with the single word CML."),
            "max_new_tokens": int(max_new_tokens or getattr(get_settings(), "lora_runtime_max_new_tokens", 48)),
            "device": getattr(get_settings(), "lora_runtime_device", "auto"),
            "dtype": getattr(get_settings(), "lora_runtime_dtype", "auto"),
            "report_path": str(report_path),
        }
        payload_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        command = [
            runtime_python_executable(),
            "-m",
            "backend.app.core.expert_runtime_worker",
            str(payload_path),
        ]
        LOGGER.info(
            "Running cluster expert runtime smoke for adapter=%s base_model=%s",
            adapter_dir,
            plan["resolved_base_model"]["base_model_path"],
        )
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=1800,
                cwd=str(ROOT_DIR),
            )
        except Exception as exc:
            report["error"] = str(exc)
            report["failure_code"] = "runtime_load_failed"
            LOGGER.warning(
                "Cluster expert runtime smoke failed to launch for adapter=%s: %s",
                adapter_dir,
                report["error"],
            )
            return report
        report["stdout"] = completed.stdout[-50_000:]
        report["stderr"] = completed.stderr[-50_000:]
        if report_path.exists():
            try:
                payload_report = json.loads(report_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload_report = {}
            if isinstance(payload_report, dict):
                report.update(payload_report)
        if completed.returncode != 0 and not report["error"]:
            report["error"] = f"Runtime smoke failed with exit code {completed.returncode}."
        completed_ok = bool(report.get("ok")) and completed.returncode == 0
        if not completed_ok and not report.get("failure_code"):
            report["failure_code"] = "runtime_load_failed"
        report["ok"] = completed_ok
        report["unloaded"] = bool(report.get("unloaded"))
    if report["ok"]:
        LOGGER.info("Cluster expert runtime smoke succeeded for adapter=%s", adapter_dir)
    else:
        LOGGER.warning(
            "Cluster expert runtime smoke failed for adapter=%s: %s",
            adapter_dir,
            report.get("error") or "unknown runtime error",
        )
    return report


def run_cluster_expert_prompt(
    conn,
    *,
    cluster_id: str,
    prompt: str,
    artifact_id: str | None = None,
) -> dict:
    attempted: list[dict[str, str]] = []
    for artifact in select_cluster_expert_candidates(conn, cluster_id=cluster_id, artifact_id=artifact_id):
        attempted.append({"artifact_id": str(artifact["id"]), "base_model": str(artifact["base_model"])})
        smoke = run_adapter_runtime_smoke(
            adapter_path=artifact["local_path"],
            base_model=str(artifact["base_model"]),
            prompt=prompt,
        )
        if smoke["ok"]:
            return {
                "ok": True,
                "cluster_id": cluster_id,
                "artifact_id": artifact["id"],
                "used_fallback": len(attempted) > 1,
                "attempted_artifacts": attempted,
                "response_text": smoke["response_text"],
                "runtime_smoke": smoke,
            }
    detail = "No compatible ready adapter could be loaded for this cluster."
    LOGGER.warning("Cluster expert selection fell back to retrieval-only for cluster=%s", cluster_id)
    return {
        "ok": False,
        "cluster_id": cluster_id,
        "artifact_id": None,
        "used_fallback": False,
        "attempted_artifacts": attempted,
        "response_text": "",
        "runtime_smoke": None,
        "detail": detail,
    }


def select_cluster_expert_candidates(conn, *, cluster_id: str, artifact_id: str | None = None) -> list[dict]:
    params: list[Any] = [cluster_id]
    artifact_filter = ""
    if artifact_id:
        artifact_filter = "AND id = ?"
        params.append(artifact_id)
    rows = conn.execute(
        f"""
        SELECT *
        FROM expert_artifacts
        WHERE cluster_id = ?
          AND status = 'ready'
          AND deleted_at IS NULL
          {artifact_filter}
        ORDER BY active DESC, updated_at DESC, created_at DESC
        """,
        params,
    ).fetchall()
    candidates = [dict_from_row(row) for row in rows]
    if artifact_id:
        fallback_rows = conn.execute(
            """
            SELECT *
            FROM expert_artifacts
            WHERE cluster_id = ?
              AND id != ?
              AND status = 'ready'
              AND deleted_at IS NULL
            ORDER BY active DESC, updated_at DESC, created_at DESC
            """,
            (cluster_id, artifact_id),
        ).fetchall()
        candidates.extend(dict_from_row(row) for row in fallback_rows)
    if artifact_id or candidates:
        return candidates
    fallback_rows = conn.execute(
        """
        SELECT *
        FROM expert_artifacts
        WHERE cluster_id = ?
          AND status = 'ready'
          AND deleted_at IS NULL
        ORDER BY active DESC, updated_at DESC, created_at DESC
        """,
        (cluster_id,),
    ).fetchall()
    return [dict_from_row(row) for row in fallback_rows]


def _base_model_candidate_strings(base_model: str, adapter_metadata: dict | None) -> list[str]:
    candidates: list[str] = []
    for value in (
        base_model,
        str((adapter_metadata or {}).get("base_model_name_or_path") or ""),
    ):
        text = value.strip()
        if not text or text in candidates:
            continue
        candidates.append(text)
        if "/" in text:
            candidates.append(text.split("/")[-1])
        if ":" in text:
            candidates.append(text.split(":", 1)[0])
        candidates.append(text.replace("/", "--"))
        candidates.append(text.replace("/", "_"))
    unique: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        normalized = item.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(item)
    return unique


def _iter_model_dir_matches(root: Path, candidates: list[str]):
    normalized_candidates = {item.lower() for item in candidates if item}
    direct_dirs = [item for item in root.iterdir() if item.is_dir()] if root.exists() else []
    for directory in direct_dirs:
        if not _is_transformers_model_dir(directory):
            continue
        names = {
            directory.name.lower(),
            str(directory).lower(),
        }
        if any(candidate in names or directory.name.lower().startswith(candidate) for candidate in normalized_candidates):
            yield directory
    for config_path in root.rglob("config.json"):
        directory = config_path.parent
        if not _is_transformers_model_dir(directory):
            continue
        name = directory.name.lower()
        path_text = str(directory).lower()
        if any(candidate == name or candidate in path_text for candidate in normalized_candidates):
            yield directory


def _is_transformers_model_dir(path: Path) -> bool:
    return path.is_dir() and any((path / name).exists() for name in MODEL_CONFIG_FILES)


def _package_status(name: str) -> dict:
    try:
        version = metadata.version(name)
    except metadata.PackageNotFoundError:
        version = None
    return {
        "installed": version is not None,
        "importable": find_spec(name.replace("-", "_")) is not None,
        "version": version,
    }
