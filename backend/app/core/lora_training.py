import json
import os
import shlex
import shutil
import subprocess
from importlib import metadata
from importlib.util import find_spec
from pathlib import Path
from uuid import uuid4

from backend.app.core.config import get_settings
from backend.app.core.embeddings import content_hash

REQUIRED_ADAPTER_FILES = ("adapter_config.json", "adapter_model.safetensors")
SUPPORTED_EXPERT_STATUSES = [
    "retrieval_ready",
    "training_pending",
    "training_running",
    "training_ready",
    "training_failed",
    "hardware_unsupported",
    "rollback_ready",
    "needs-update",
    "paused",
]
FAILURE_CODES = [
    "hardware_unsupported",
    "insufficient_dataset",
    "trainer_missing",
    "trainer_failed",
    "adapter_missing",
    "adapter_invalid",
    "quality_gate_failed",
    "runtime_load_failed",
    "dataset_changed",
]


class LoraTrainerMissingError(RuntimeError):
    """Raised when real LoRA training is requested without a configured trainer."""


def graduation_contract() -> dict:
    settings = get_settings()
    return {
        "supported_statuses": SUPPORTED_EXPERT_STATUSES,
        "minimum_sources": settings.lora_min_sources,
        "minimum_unique_sources": settings.lora_min_unique_sources,
        "minimum_estimated_tokens": settings.lora_min_tokens,
        "minimum_validation_records": settings.lora_min_validation_records,
        "minimum_quality_score": settings.lora_min_quality_score,
        "minimum_quality_delta": settings.lora_min_quality_delta,
        "maximum_duplicate_ratio": settings.lora_max_duplicate_ratio,
        "required_artifact_files": list(REQUIRED_ADAPTER_FILES),
        "failure_codes": FAILURE_CODES,
        "graduation_gate": (
            "A cluster graduates only when the dataset meets source/token/validation/diversity gates, "
            "the trainer exits successfully, required adapter files validate, adapter quality beats "
            "the retrieval-only baseline, and the runtime load contract is available."
        ),
        "rollback_behavior": "Only one active adapter is allowed per cluster; activating a new adapter deactivates previous adapters and rollback reactivates the latest non-deleted ready adapter.",
    }


def trainer_dependency_status() -> dict:
    packages = {
        name: _package_status(name)
        for name in ("llamafactory", "peft", "trl", "gradio", "transformers", "torch")
    }
    settings = get_settings()
    cli_path = _llamafactory_cli_path()
    issues = []
    if not packages["llamafactory"]["importable"]:
        issues.append("llamafactory is not importable")
    if not packages["peft"]["importable"]:
        issues.append("peft is not importable")
    if not cli_path and not settings.lora_trainer_command:
        issues.append("No llamafactory-cli executable or CML_LORA_TRAINER_COMMAND is configured")
    return {
        "available": not issues,
        "packages": packages,
        "llamafactory_cli": cli_path,
        "trainer_command_configured": bool(settings.lora_trainer_command),
        "test_trainer_enabled": bool(settings.allow_lora_test_trainer),
        "issues": issues,
    }


def training_config(base_model: str, dataset_hash: str) -> dict:
    payload = {
        "trainer": "llama-factory-compatible",
        "base_model": base_model,
        "dataset_hash": dataset_hash,
        "finetuning_type": "lora",
        "template": "chatml",
        "cutoff_len": 4096,
        "learning_rate": 0.0002,
        "num_train_epochs": 1,
    }
    payload["training_config_hash"] = content_hash(json.dumps(payload, sort_keys=True))
    return payload


def run_lora_training_process(*, dataset_manifest: dict, output_dir: Path, config: dict) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = output_dir / "training-config.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    stdout_path = output_dir / "trainer.stdout.log"
    stderr_path = output_dir / "trainer.stderr.log"

    settings = get_settings()
    if settings.allow_lora_test_trainer:
        _write_test_adapter(output_dir, config)
        stdout_path.write_text("test trainer completed\n", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return {
            "status": "succeeded",
            "adapter_path": str(output_dir),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }

    if not settings.lora_trainer_command:
        raise LoraTrainerMissingError("LoRA trainer command is not configured.")

    env = {
        **os.environ,
        "CML_LORA_DATASET_DIR": str(dataset_manifest["dataset_dir"]),
        "CML_LORA_TRAIN_PATH": str(dataset_manifest["train_path"]),
        "CML_LORA_VALIDATION_PATH": str(dataset_manifest["validation_path"]),
        "CML_LORA_OUTPUT_DIR": str(output_dir),
        "CML_LORA_CONFIG_PATH": str(config_path),
    }
    command = _trainer_command_argv(settings.lora_trainer_command, dataset_manifest, output_dir, config_path)
    result = subprocess.run(command, shell=False, capture_output=True, text=True, env=env, timeout=7200)
    stdout_path.write_text(result.stdout[-200_000:], encoding="utf-8")
    stderr_path.write_text(result.stderr[-200_000:], encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"LoRA trainer failed with exit code {result.returncode}.")
    _verify_adapter_files(output_dir)
    return {
        "status": "succeeded",
        "adapter_path": str(output_dir),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }


def verify_adapter_artifact(path: str | Path) -> None:
    _verify_adapter_files(Path(path))


def adapter_validation_report(path: str | Path) -> dict:
    adapter_dir = Path(path)
    errors = _adapter_validation_errors(adapter_dir)
    return {
        "adapter_path": str(adapter_dir),
        "valid": not errors,
        "errors": errors,
        "required_files": list(REQUIRED_ADAPTER_FILES),
    }


def dataset_graduation_report(dataset: dict, *, validation_count: int | None = None) -> dict:
    settings = get_settings()
    source_count = int(dataset.get("source_count") or 0)
    unique_count = int(dataset.get("unique_content_hash_count") or source_count)
    duplicate_ratio = float(dataset.get("duplicate_content_ratio") or 0.0)
    token_count = int(dataset.get("estimated_token_count") or 0)
    validation_records = int(validation_count if validation_count is not None else dataset.get("validation_count") or 0)
    checks = {
        "minimum_sources": source_count >= settings.lora_min_sources,
        "minimum_unique_sources": unique_count >= settings.lora_min_unique_sources,
        "minimum_estimated_tokens": token_count >= settings.lora_min_tokens,
        "maximum_duplicate_ratio": duplicate_ratio <= settings.lora_max_duplicate_ratio,
    }
    if validation_count is not None or "validation_count" in dataset:
        checks["minimum_validation_records"] = validation_records >= settings.lora_min_validation_records
    return {
        "passes": all(checks.values()),
        "checks": checks,
        "source_count": source_count,
        "unique_content_hash_count": unique_count,
        "duplicate_content_ratio": duplicate_ratio,
        "estimated_token_count": token_count,
        "validation_count": validation_records,
        "minimum_sources": settings.lora_min_sources,
        "minimum_unique_sources": settings.lora_min_unique_sources,
        "minimum_estimated_tokens": settings.lora_min_tokens,
        "minimum_validation_records": settings.lora_min_validation_records,
        "maximum_duplicate_ratio": settings.lora_max_duplicate_ratio,
    }
def new_artifact_dir(cluster_id: str) -> Path:
    return get_settings().data_dir / "experts" / cluster_id / f"adapter-{uuid4()}"


def _verify_adapter_files(output_dir: Path) -> None:
    errors = _adapter_validation_errors(output_dir)
    if errors:
        raise RuntimeError("; ".join(errors))


def _adapter_validation_errors(output_dir: Path) -> list[str]:
    errors = []
    if not output_dir.exists() or not output_dir.is_dir():
        return [f"LoRA adapter directory does not exist: {output_dir}"]
    missing = [name for name in REQUIRED_ADAPTER_FILES if not (output_dir / name).exists()]
    if missing:
        errors.append(f"LoRA adapter is missing required files: {', '.join(missing)}")
    config_path = output_dir / "adapter_config.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            errors.append("LoRA adapter_config.json is not valid JSON")
        else:
            if not isinstance(config, dict):
                errors.append("LoRA adapter_config.json must contain an object")
            else:
                peft_type = str(config.get("peft_type") or "").upper()
                if peft_type != "LORA":
                    errors.append("LoRA adapter_config.json must declare peft_type=LORA")
                if not str(config.get("base_model_name_or_path") or "").strip():
                    errors.append("LoRA adapter_config.json must include base_model_name_or_path")
    model_path = output_dir / "adapter_model.safetensors"
    if model_path.exists() and model_path.stat().st_size <= 0:
        errors.append("LoRA adapter_model.safetensors is empty")
    return errors


def _write_test_adapter(output_dir: Path, config: dict) -> None:
    (output_dir / "adapter_config.json").write_text(
        json.dumps({"peft_type": "LORA", "base_model_name_or_path": config["base_model"]}, indent=2),
        encoding="utf-8",
    )
    (output_dir / "adapter_model.safetensors").write_bytes(b"CML test adapter placeholder\n")


def _trainer_command_argv(
    command_template: str,
    dataset_manifest: dict,
    output_dir: Path,
    config_path: Path,
) -> list[str]:
    values = {
        "dataset_dir": str(dataset_manifest["dataset_dir"]),
        "train_path": str(dataset_manifest["train_path"]),
        "validation_path": str(dataset_manifest["validation_path"]),
        "output_dir": str(output_dir),
        "config_path": str(config_path),
    }
    stripped = command_template.strip()
    if stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise RuntimeError("CML_LORA_TRAINER_COMMAND JSON argv is invalid.") from exc
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            raise RuntimeError("CML_LORA_TRAINER_COMMAND JSON argv must be a list of strings.")
        argv = [_replace_trainer_placeholders(item, values) for item in parsed]
    else:
        argv = shlex.split(_replace_trainer_placeholders(stripped, values), posix=os.name != "nt")
    if not argv:
        raise RuntimeError("LoRA trainer command is empty.")
    return argv


def _replace_trainer_placeholders(template: str, values: dict[str, str]) -> str:
    result = template
    for key, value in values.items():
        result = result.replace(f"{{{key}}}", value)
    return result


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


def _llamafactory_cli_path() -> str | None:
    resolved = shutil.which("llamafactory-cli")
    if resolved:
        return resolved
    candidate = Path(sys_executable_dir()) / "llamafactory-cli.exe"
    return str(candidate) if candidate.exists() else None


def sys_executable_dir() -> Path:
    import sys

    return Path(sys.executable).resolve().parent
