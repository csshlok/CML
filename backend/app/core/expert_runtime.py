import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import OrderedDict
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
    dependency_ready = bool(dependency_status["available"])
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
    if dependency_status["available"] and dependency_status.get("external_runtime"):
        detail_parts.append(
            f"Runtime dependencies are importable in configured runtime python "
            f"{dependency_status.get('resolved_runtime_python') or dependency_status['runtime_python']}."
        )
    elif dependency_status["available"]:
        detail_parts.append("Runtime dependencies are importable in the active backend environment.")
    else:
        detail_parts.append(_runtime_dependency_detail(dependency_status))
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
    runtime_python = runtime_python_executable()
    if not _same_executable(runtime_python, sys.executable):
        return _external_runtime_dependency_status(runtime_python)

    packages = {name: _package_status(name) for name in ("torch", "transformers", "peft")}
    available = all(item["importable"] for item in packages.values())
    issues = []
    for name, status in packages.items():
        if not status["importable"]:
            issues.append(f"{name} is not importable")
    return {
        "available": available,
        "runtime_python": runtime_python,
        "resolved_runtime_python": sys.executable,
        "external_runtime": False,
        "runtime_python_exists": True,
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
    batch = run_adapter_runtime_batch(
        adapter_path=adapter_path,
        base_model=base_model,
        prompts=[prompt or getattr(get_settings(), "lora_runtime_prompt", "Reply with the single word CML.")],
        max_new_tokens=max_new_tokens,
    )
    report = dict(batch)
    first_response = (batch.get("responses") or [{}])[0]
    report["prompt"] = first_response.get("prompt") or prompt or getattr(
        get_settings(),
        "lora_runtime_prompt",
        "Reply with the single word CML.",
    )
    report["response_text"] = first_response.get("response_text") or batch.get("response_text") or ""
    return report


def run_adapter_runtime_batch(
    *,
    adapter_path: str | Path,
    base_model: str,
    prompts: list[str],
    max_new_tokens: int | None = None,
    max_new_tokens_per_prompt: list[int] | None = None,
) -> dict:
    adapter_dir = Path(adapter_path)
    plan = runtime_adapter_load_plan(adapter_path=adapter_dir, base_model=base_model)
    report = {
        "ok": False,
        "adapter_path": str(adapter_dir),
        "base_model": base_model,
        "plan": plan,
        "responses": [],
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
            "prompt": prompts[0] if prompts else "",
            "prompts": prompts,
            "max_new_tokens": int(max_new_tokens or getattr(get_settings(), "lora_runtime_max_new_tokens", 48)),
            "max_new_tokens_per_prompt": [int(item) for item in (max_new_tokens_per_prompt or [])],
            "repetition_penalty": float(getattr(get_settings(), "lora_runtime_repetition_penalty", 1.1)),
            "no_repeat_ngram_size": int(getattr(get_settings(), "lora_runtime_no_repeat_ngram_size", 4)),
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
        timeout_seconds = _runtime_batch_timeout_seconds(len(prompts))
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
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


def _runtime_batch_timeout_seconds(prompt_count: int) -> int:
    settings = get_settings()
    base_timeout = max(60, int(getattr(settings, "lora_runtime_batch_timeout_seconds", 1800) or 1800))
    per_prompt_timeout = max(
        0,
        int(getattr(settings, "lora_runtime_batch_timeout_per_prompt_seconds", 15) or 15),
    )
    normalized_prompt_count = max(1, int(prompt_count or 0))
    return base_timeout + (per_prompt_timeout * normalized_prompt_count)


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


def run_cluster_expert_compression(
    conn,
    *,
    cluster_id: str,
    prompt: str,
    citations: list[dict],
    cluster_profile: dict | None = None,
    artifact_id: str | None = None,
    max_new_tokens: int | None = None,
) -> dict:
    if not citations:
        return {
            "ok": False,
            "mode": "no_evidence",
            "detail": "Expert compression requires retrieved evidence.",
            "artifact_id": None,
            "digest": "",
            "warnings": [],
            "unsupported_claims": [],
            "behavior_profile": _empty_behavior_profile(),
        }
    compression_prompt = build_expert_behavior_prompt(
        prompt=prompt,
        citations=citations,
        cluster_profile=cluster_profile,
    )
    attempted: list[dict[str, str]] = []
    for artifact in select_cluster_expert_candidates(conn, cluster_id=cluster_id, artifact_id=artifact_id):
        attempted.append({"artifact_id": str(artifact["id"]), "base_model": str(artifact["base_model"])})
        smoke = run_adapter_runtime_smoke(
            adapter_path=artifact["local_path"],
            base_model=str(artifact["base_model"]),
            prompt=compression_prompt,
            max_new_tokens=max_new_tokens,
        )
        if not smoke["ok"]:
            continue
        parsed = _parse_expert_compression_output(str(smoke.get("response_text") or ""))
        unsupported_claims = _unsupported_claims_against_evidence(
            parsed.get("digest") or "",
            citations,
            cluster_profile=cluster_profile,
        )
        unsupported_claims.extend(str(item).strip() for item in parsed.get("unsupported_claims") or [] if str(item).strip())
        unsupported_claims = list(OrderedDict.fromkeys(item for item in unsupported_claims if item))
        if unsupported_claims:
            return {
                "ok": False,
                "mode": "unsupported_claims",
                "detail": "Expert digest contained unsupported claims and was discarded.",
                "artifact_id": artifact["id"],
                "attempted_artifacts": attempted,
                "warnings": ["Expert digest failed grounding validation."],
                "unsupported_claims": unsupported_claims,
                "runtime_smoke": smoke,
                "behavior_profile": dict(parsed.get("behavior_profile") or _empty_behavior_profile()),
            }
        return {
            "ok": True,
            "mode": "retrieval_grounded_behavior",
            "cluster_id": cluster_id,
            "artifact_id": artifact["id"],
            "attempted_artifacts": attempted,
            "digest": str(parsed.get("digest") or "").strip(),
            "local_terms": list(parsed.get("local_terms") or []),
            "reasoning_hints": list(parsed.get("reasoning_hints") or []),
            "uncertainties": list(parsed.get("uncertainties") or []),
            "unsupported_claims": [],
            "warnings": [],
            "behavior_profile": dict(parsed.get("behavior_profile") or _empty_behavior_profile()),
            "runtime_smoke": smoke,
            "load_plan": smoke.get("plan") or {},
        }
    return {
        "ok": False,
        "mode": "expert_unavailable",
        "detail": "No compatible ready adapter could be loaded for retrieval-grounded compression.",
        "artifact_id": None,
        "attempted_artifacts": attempted,
        "warnings": [],
        "unsupported_claims": [],
        "behavior_profile": _empty_behavior_profile(),
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


def build_expert_behavior_prompt(
    *,
    prompt: str,
    citations: list[dict],
    cluster_profile: dict | None = None,
) -> str:
    evidence_lines = []
    for index, citation in enumerate(citations[:5], start=1):
        evidence_lines.append(
            f"[{index}] {citation.get('source_title') or 'Untitled source'} :: "
            f"{' '.join(str(citation.get('snippet') or '').split())}"
        )
    local_terms = ", ".join(str(item) for item in (cluster_profile or {}).get("local_terms") or [] if str(item).strip())
    style_profile = str((cluster_profile or {}).get("style_profile") or "").strip()
    answer_contract = dict((cluster_profile or {}).get("answer_contract") or {})
    behavior_profile = dict((cluster_profile or {}).get("behavior_profile") or {})
    return (
        "Task: Produce a grounded cluster-aware context digest and behavior profile.\n"
        "Authority: Use only the evidence below.\n"
        "Forbidden: Do not invent citations, source titles, names, dates, quantities, or facts.\n"
        "Output: JSON with keys digest, local_terms, reasoning_hints, uncertainties, unsupported_claims, behavior_profile.\n"
        "The behavior_profile must contain: voice, terminology_shift, style_markers, reasoning_order, framing_rules, refusal_style, practicality_bias.\n\n"
        f"User query: {prompt.strip()}\n"
        f"Cluster local terms: {local_terms or 'none'}\n"
        f"Cluster style profile: {style_profile or 'none'}\n\n"
        f"Cluster answer contract: {json.dumps(answer_contract, ensure_ascii=False, separators=(',', ':'))}\n"
        f"Seed behavior profile: {json.dumps(behavior_profile, ensure_ascii=False, separators=(',', ':'))}\n\n"
        "Retrieved evidence:\n"
        f"{chr(10).join(evidence_lines)}"
    )


def build_expert_compression_prompt(
    *,
    prompt: str,
    citations: list[dict],
    cluster_profile: dict | None = None,
) -> str:
    return build_expert_behavior_prompt(
        prompt=prompt,
        citations=citations,
        cluster_profile=cluster_profile,
    )


def _parse_expert_compression_output(text: str) -> dict:
    stripped = str(text or "").strip()
    if not stripped:
        return {
            "digest": "",
            "local_terms": [],
            "reasoning_hints": [],
            "uncertainties": [],
            "unsupported_claims": [],
            "behavior_profile": _empty_behavior_profile(),
        }
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            return {
                "digest": str(payload.get("digest") or "").strip(),
                "local_terms": [str(item).strip() for item in payload.get("local_terms") or [] if str(item).strip()],
                "reasoning_hints": [str(item).strip() for item in payload.get("reasoning_hints") or [] if str(item).strip()],
                "uncertainties": [str(item).strip() for item in payload.get("uncertainties") or [] if str(item).strip()],
                "unsupported_claims": [str(item).strip() for item in payload.get("unsupported_claims") or [] if str(item).strip()],
                "behavior_profile": _normalize_behavior_profile(payload.get("behavior_profile")),
            }
    return {
        "digest": stripped,
        "local_terms": [],
        "reasoning_hints": [],
        "uncertainties": [],
        "unsupported_claims": [],
        "behavior_profile": _empty_behavior_profile(),
    }


def _unsupported_claims_against_evidence(
    digest: str,
    citations: list[dict],
    *,
    cluster_profile: dict | None = None,
) -> list[str]:
    evidence_titles = {
        str(item.get("source_title") or "").strip()
        for item in citations
        if str(item.get("source_title") or "").strip()
    }
    evidence_text = " ".join(
        part
        for item in citations
        for part in (
            str(item.get("source_title") or "").strip(),
            str(item.get("snippet") or "").strip(),
        )
        if part
    )
    allowed_terms = {
        str(item).strip()
        for item in (cluster_profile or {}).get("local_terms") or []
        if str(item).strip()
    }
    unsupported: list[str] = []
    for title in re.findall(r"'([^']+)'|\"([^\"]+)\"", digest):
        candidate = next((part for part in title if part), "").strip()
        if candidate and candidate not in evidence_titles:
            unsupported.append(f"unsupported source title: {candidate}")
    evidence_lower = evidence_text.lower()
    for number in re.findall(r"\b\d[\d,./:-]*\b", digest):
        if number.lower() not in evidence_lower:
            unsupported.append(f"unsupported quantity/date: {number}")
    stop_words = {
        "The",
        "This",
        "That",
        "These",
        "Those",
        "Use",
        "Retrieved",
        "Cluster",
        "Evidence",
        "Digest",
        "Reasoning",
        "Local",
    }
    for token in re.findall(r"\b[A-Z][a-zA-Z0-9_-]{2,}\b", digest):
        if token in stop_words or token in allowed_terms:
            continue
        if token.lower() not in evidence_lower:
            unsupported.append(f"unsupported entity: {token}")
    return unsupported


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


def _external_runtime_dependency_status(runtime_python: str) -> dict:
    resolved = _resolve_runtime_python(runtime_python)
    if resolved is None:
        return {
            "available": False,
            "runtime_python": runtime_python,
            "resolved_runtime_python": "",
            "external_runtime": True,
            "runtime_python_exists": False,
            "packages": _missing_runtime_packages(),
            "issues": [f"Configured LoRA runtime python was not found: {runtime_python}"],
        }

    script = """
import importlib.util
import json
from importlib import metadata

packages = {}
for name in ("torch", "transformers", "peft"):
    try:
        version = metadata.version(name)
    except metadata.PackageNotFoundError:
        version = None
    packages[name] = {
        "installed": version is not None,
        "importable": importlib.util.find_spec(name.replace("-", "_")) is not None,
        "version": version,
    }
print(json.dumps(packages, separators=(",", ":")))
"""
    try:
        completed = subprocess.run(
            [resolved, "-c", script],
            capture_output=True,
            text=True,
            timeout=20,
            cwd=str(ROOT_DIR),
        )
    except Exception as exc:
        return {
            "available": False,
            "runtime_python": runtime_python,
            "resolved_runtime_python": resolved,
            "external_runtime": True,
            "runtime_python_exists": True,
            "packages": _missing_runtime_packages(),
            "issues": [f"Configured LoRA runtime python could not be inspected: {exc}"],
        }
    if completed.returncode != 0:
        return {
            "available": False,
            "runtime_python": runtime_python,
            "resolved_runtime_python": resolved,
            "external_runtime": True,
            "runtime_python_exists": True,
            "packages": _missing_runtime_packages(),
            "issues": [
                "Configured LoRA runtime python failed dependency inspection"
                + (f": {completed.stderr[-500:]}" if completed.stderr else ".")
            ],
        }
    try:
        parsed_packages = json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError:
        packages = _missing_runtime_packages()
        issues = ["Configured LoRA runtime python returned invalid dependency inspection output."]
    else:
        if not isinstance(parsed_packages, dict):
            packages = _missing_runtime_packages()
            issues = ["Configured LoRA runtime python returned invalid dependency inspection output."]
        else:
            packages = parsed_packages
            issues = [
                f"{name} is not importable in configured runtime python"
                for name, status in packages.items()
                if not isinstance(status, dict) or not status.get("importable")
            ]
    return {
        "available": not issues,
        "runtime_python": runtime_python,
        "resolved_runtime_python": resolved,
        "external_runtime": True,
        "runtime_python_exists": True,
        "packages": packages,
        "issues": issues,
    }


def _resolve_runtime_python(runtime_python: str) -> str | None:
    if not runtime_python:
        return None
    candidate = Path(runtime_python)
    if candidate.exists() and not candidate.is_dir():
        return str(candidate.resolve())
    resolved = shutil.which(runtime_python)
    return resolved


def _same_executable(left: str, right: str) -> bool:
    try:
        left_path = Path(left).resolve(strict=False)
        right_path = Path(right).resolve(strict=False)
    except OSError:
        return left == right
    return os.path.normcase(str(left_path)) == os.path.normcase(str(right_path))


def _missing_runtime_packages() -> dict[str, dict]:
    return {
        name: {"installed": False, "importable": False, "version": None}
        for name in ("torch", "transformers", "peft")
    }


def _runtime_dependency_detail(status: dict) -> str:
    issues = [str(item) for item in status.get("issues") or [] if item]
    if not status.get("external_runtime"):
        if issues:
            return (
                "Install peft, transformers, and torch or configure CML_LORA_RUNTIME_PYTHON. "
                "Missing: " + "; ".join(issues) + "."
            )
        return "Install peft, transformers, and torch or configure CML_LORA_RUNTIME_PYTHON."
    if issues:
        return "LoRA runtime dependency gate failed: " + "; ".join(issues) + "."
    return "Install peft, transformers, and torch or configure CML_LORA_RUNTIME_PYTHON."


def _empty_behavior_profile() -> dict:
    return {
        "voice": "",
        "terminology_shift": [],
        "style_markers": [],
        "reasoning_order": [],
        "framing_rules": [],
        "refusal_style": "",
        "practicality_bias": "",
    }


def _normalize_behavior_profile(payload: Any) -> dict:
    profile = _empty_behavior_profile()
    if not isinstance(payload, dict):
        return profile
    profile["voice"] = str(payload.get("voice") or "").strip()
    for key in ("terminology_shift", "style_markers", "reasoning_order", "framing_rules"):
        value = payload.get(key) or []
        if isinstance(value, list):
            profile[key] = [str(item).strip() for item in value if str(item).strip()]
        elif value:
            profile[key] = [str(value).strip()]
    profile["refusal_style"] = str(payload.get("refusal_style") or "").strip()
    profile["practicality_bias"] = str(payload.get("practicality_bias") or "").strip()
    return profile
