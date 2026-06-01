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
]
FAILURE_CODES = [
    "hardware_unsupported",
    "insufficient_dataset",
    "trainer_missing",
    "trainer_failed",
    "adapter_missing",
    "quality_gate_failed",
]


def graduation_contract() -> dict:
    settings = get_settings()
    return {
        "supported_statuses": SUPPORTED_EXPERT_STATUSES,
        "minimum_sources": settings.lora_min_sources,
        "minimum_quality_score": settings.lora_min_quality_score,
        "required_artifact_files": list(REQUIRED_ADAPTER_FILES),
        "failure_codes": FAILURE_CODES,
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
        raise RuntimeError("LoRA trainer command is not configured.")

    command = settings.lora_trainer_command.format(
        dataset_dir=shlex.quote(str(dataset_manifest["dataset_dir"])),
        train_path=shlex.quote(str(dataset_manifest["train_path"])),
        validation_path=shlex.quote(str(dataset_manifest["validation_path"])),
        output_dir=shlex.quote(str(output_dir)),
        config_path=shlex.quote(str(config_path)),
    )
    env = {
        **os.environ,
        "CML_LORA_DATASET_DIR": str(dataset_manifest["dataset_dir"]),
        "CML_LORA_TRAIN_PATH": str(dataset_manifest["train_path"]),
        "CML_LORA_VALIDATION_PATH": str(dataset_manifest["validation_path"]),
        "CML_LORA_OUTPUT_DIR": str(output_dir),
        "CML_LORA_CONFIG_PATH": str(config_path),
    }
    result = subprocess.run(command, shell=True, capture_output=True, text=True, env=env, timeout=7200)
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


def new_artifact_dir(cluster_id: str) -> Path:
    return get_settings().data_dir / "experts" / cluster_id / f"adapter-{uuid4()}"


def _verify_adapter_files(output_dir: Path) -> None:
    missing = [name for name in REQUIRED_ADAPTER_FILES if not (output_dir / name).exists()]
    if missing:
        raise RuntimeError(f"LoRA adapter is missing required files: {', '.join(missing)}")


def _write_test_adapter(output_dir: Path, config: dict) -> None:
    (output_dir / "adapter_config.json").write_text(
        json.dumps({"peft_type": "LORA", "base_model_name_or_path": config["base_model"]}, indent=2),
        encoding="utf-8",
    )
    (output_dir / "adapter_model.safetensors").write_bytes(b"CML test adapter placeholder\n")


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
