import json
import os
import shlex
import shutil
import subprocess
import ctypes
import importlib.util
from contextlib import contextmanager
from importlib import metadata
from importlib.util import find_spec
from pathlib import Path
from uuid import uuid4

from backend.app.core.config import get_settings
from backend.app.core.embeddings import content_hash
from backend.app.core.expert_evaluation import EVALUATION_CATEGORIES
from backend.app.core.training_dataset import LEGACY_CATEGORY_BY_RECORD_TYPE, TRAINING_RECORD_TYPES

REQUIRED_ADAPTER_FILES = ("adapter_config.json", "adapter_model.safetensors")
SUPPORTED_EXPERT_STATUSES = [
    "retrieval_ready",
    "retrieval_only",
    "expert_training_pending",
    "expert_training_running",
    "expert_compression_ready",
    "training_failed",
    "hardware_unsupported",
    "rollback_ready",
    "expert_stale",
    "paused",
]
LEGACY_EXPERT_STATUS_ALIASES = {
    "training_pending": "expert_training_pending",
    "training_running": "expert_training_running",
    "training_ready": "expert_compression_ready",
    "needs-update": "expert_stale",
    "ready": "expert_compression_ready",
    "searchable": "retrieval_ready",
}
FAILURE_CODES = [
    "hardware_unsupported",
    "insufficient_dataset",
    "insufficient_benchmark_diversity",
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
        "legacy_status_aliases": dict(LEGACY_EXPERT_STATUS_ALIASES),
        "minimum_sources": settings.lora_min_sources,
        "minimum_unique_sources": settings.lora_min_unique_sources,
        "minimum_estimated_tokens": settings.lora_min_tokens,
        "minimum_validation_records": settings.lora_min_validation_records,
        "benchmark_minimum_train_records": settings.lora_benchmark_min_train_records,
        "benchmark_minimum_validation_records": settings.lora_benchmark_min_validation_records,
        "benchmark_minimum_validation_records_per_category": settings.lora_benchmark_min_validation_records_per_category,
        "benchmark_minimum_unique_sources": settings.lora_benchmark_min_unique_sources,
        "benchmark_minimum_unique_content_hashes": settings.lora_benchmark_min_unique_content_hashes,
        "benchmark_maximum_train_record_share_per_source": settings.lora_benchmark_max_train_record_share_per_source,
        "benchmark_maximum_validation_record_share_per_source": settings.lora_benchmark_max_validation_record_share_per_source,
        "benchmark_maximum_validation_record_share_per_source_per_category": settings.lora_benchmark_max_validation_record_share_per_source_per_category,
        "minimum_quality_score": settings.lora_min_quality_score,
        "minimum_quality_delta": settings.lora_min_quality_delta,
        "maximum_duplicate_ratio": settings.lora_max_duplicate_ratio,
        "required_artifact_files": list(REQUIRED_ADAPTER_FILES),
        "failure_codes": FAILURE_CODES,
        "graduation_gate": (
            "A cluster graduates only when the dataset meets source/token/validation/diversity gates, "
            "the trainer exits successfully, required adapter files validate, expert-compression bundle quality beats "
            "the retrieval-grounded bundle benchmark, and the runtime load contract is available."
        ),
        "benchmark_gate": (
            "A benchmark is considered meaningful only when the post-filter, post-split record set meets "
            "minimum train/validation volume, minimum validation records per category, distinct source and "
            "content-hash floors, and per-source share caps for total and per-category validation records."
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
    settings = get_settings()
    payload = {
        "trainer": "llama-factory-compatible",
        "base_model": base_model,
        "dataset_hash": dataset_hash,
        "finetuning_type": "lora",
        "template": "chatml",
        "cutoff_len": int(settings.lora_training_cutoff_len),
        "learning_rate": 0.0002,
        "num_train_epochs": float(settings.lora_training_num_train_epochs),
    }
    payload["training_config_hash"] = content_hash(json.dumps(payload, sort_keys=True))
    return payload


def run_lora_training_process(*, dataset_manifest: dict, output_dir: Path, config: dict) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    cml_config_path = output_dir / "training-config.json"
    cml_config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    _write_llamafactory_dataset_info(dataset_manifest)
    llamafactory_config_path = output_dir / "llamafactory-train-config.yaml"
    llamafactory_config = _llamafactory_training_config(dataset_manifest, output_dir, config)
    llamafactory_config_path.write_text(json.dumps(llamafactory_config, indent=2), encoding="utf-8")
    stdout_path = output_dir / "trainer.stdout.log"
    stderr_path = output_dir / "trainer.stderr.log"

    settings = get_settings()
    if settings.allow_lora_test_trainer:
        _write_test_adapter(output_dir, config)
        _package_dataset_artifacts(dataset_manifest, output_dir)
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

    _ensure_windows_virtual_memory_headroom(config["base_model"])

    env = {
        **os.environ,
        "CML_LORA_DATASET_DIR": str(dataset_manifest["dataset_dir"]),
        "CML_LORA_TRAIN_PATH": str(dataset_manifest["train_path"]),
        "CML_LORA_VALIDATION_PATH": str(dataset_manifest["validation_path"]),
        "CML_LORA_OUTPUT_DIR": str(output_dir),
        "CML_LORA_CONFIG_PATH": str(cml_config_path),
        "CML_LORA_LLAMAFACTORY_CONFIG_PATH": str(llamafactory_config_path),
    }
    env["PATH"] = _path_with_python_scripts(env.get("PATH", ""))
    command = _trainer_command_argv(
        settings.lora_trainer_command,
        dataset_manifest,
        output_dir,
        llamafactory_config_path,
        cml_config_path=cml_config_path,
    )
    if _looks_like_llamafactory_train_command(command):
        env.setdefault("NPROC_PER_NODE", "1")
    result = subprocess.run(
        command,
        shell=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=_trainer_timeout_seconds(),
    )
    stdout_path.write_text(result.stdout[-200_000:], encoding="utf-8")
    stderr_path.write_text(result.stderr[-200_000:], encoding="utf-8")
    if result.returncode != 0:
        if "os error 1455" in result.stderr.lower() or "paging file is too small" in result.stderr.lower():
            raise RuntimeError(_windows_virtual_memory_failure_detail(config["base_model"]))
        raise RuntimeError(f"LoRA trainer failed with exit code {result.returncode}.")
    _package_dataset_artifacts(dataset_manifest, output_dir)
    _verify_adapter_files(output_dir)
    return {
        "status": "succeeded",
        "adapter_path": str(output_dir),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "cml_config_path": str(cml_config_path),
        "llamafactory_config_path": str(llamafactory_config_path),
    }


def _ensure_windows_virtual_memory_headroom(base_model: str) -> None:
    if os.name != "nt":
        return
    report = _windows_virtual_memory_report(base_model)
    if not report["check_performed"]:
        return
    if report["available_pagefile_bytes"] >= report["recommended_available_pagefile_bytes"]:
        return
    raise RuntimeError(_windows_virtual_memory_failure_detail(base_model, report=report))


def _windows_virtual_memory_failure_detail(base_model: str, *, report: dict | None = None) -> str:
    payload = report or _windows_virtual_memory_report(base_model)
    recommended_gib = payload["recommended_available_pagefile_bytes"] / (1024 ** 3)
    available_gib = payload["available_pagefile_bytes"] / (1024 ** 3)
    model_gib = payload["model_weight_bytes"] / (1024 ** 3)
    return (
        "Windows virtual-memory headroom is too low for this LoRA run. "
        f"Base model weights are about {model_gib:.2f} GiB, available pagefile headroom is about {available_gib:.2f} GiB, "
        f"and CML requires roughly {recommended_gib:.2f} GiB free before starting training. "
        "Increase the Windows paging file, close other memory-heavy apps, or use a smaller base model, then retry."
    )


def _windows_virtual_memory_report(base_model: str) -> dict:
    model_weight_bytes = _model_weight_bytes(base_model)
    report = {
        "check_performed": False,
        "model_weight_bytes": model_weight_bytes,
        "available_pagefile_bytes": 0,
        "total_pagefile_bytes": 0,
        "recommended_available_pagefile_bytes": max(8 * 1024 ** 3, model_weight_bytes * 2),
    }
    if model_weight_bytes <= 0:
        return report
    status = _windows_memory_status()
    if status is None:
        return report
    report["check_performed"] = True
    report["available_pagefile_bytes"] = int(status["avail_pagefile"])
    report["total_pagefile_bytes"] = int(status["total_pagefile"])
    return report


def _model_weight_bytes(base_model: str) -> int:
    base_model_path = Path(str(base_model))
    if base_model_path.is_file():
        return int(base_model_path.stat().st_size)
    if not base_model_path.exists():
        return 0
    weight_paths = list(base_model_path.glob("*.safetensors")) + list(base_model_path.glob("*.bin"))
    return int(sum(path.stat().st_size for path in weight_paths if path.is_file()))


def _windows_memory_status() -> dict | None:
    if os.name != "nt":
        return None

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return {
        "total_phys": int(status.ullTotalPhys),
        "avail_phys": int(status.ullAvailPhys),
        "total_pagefile": int(status.ullTotalPageFile),
        "avail_pagefile": int(status.ullAvailPageFile),
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


def benchmark_eligibility_report(dataset_manifest: dict) -> dict:
    settings = get_settings()
    accounting = dict(dataset_manifest.get("benchmark_record_accounting") or {})
    train = dict(accounting.get("train") or {})
    validation = dict(accounting.get("validation") or {})
    raw_validation_counts = dict(validation.get("record_type_counts") or validation.get("category_counts") or {})
    raw_validation_shares = dict(
        validation.get("max_record_share_per_source_per_record_type")
        or validation.get("max_record_share_per_source_per_category")
        or {}
    )
    validation_counts_are_record_types = any(str(key) in TRAINING_RECORD_TYPES for key in raw_validation_counts)
    validation_shares_are_record_types = any(str(key) in TRAINING_RECORD_TYPES for key in raw_validation_shares)
    validation_dimension_names = TRAINING_RECORD_TYPES if validation_counts_are_record_types else EVALUATION_CATEGORIES
    validation_record_type_counts = {
        record_type: (
            int(raw_validation_counts.get(record_type, 0))
            if validation_counts_are_record_types
            else int(raw_validation_counts.get(LEGACY_CATEGORY_BY_RECORD_TYPE.get(record_type, ""), 0))
        )
        for record_type in TRAINING_RECORD_TYPES
    }
    if validation_counts_are_record_types:
        validation_record_type_minimums = {
            record_type: validation_record_type_counts.get(record_type, 0) >= settings.lora_benchmark_min_validation_records_per_category
            for record_type in validation_dimension_names
        }
    else:
        validation_record_type_minimums = {
            category: int(raw_validation_counts.get(category, 0)) >= settings.lora_benchmark_min_validation_records_per_category
            for category in validation_dimension_names
        }
    if validation_shares_are_record_types:
        validation_record_type_source_share = {
            record_type: float(raw_validation_shares.get(record_type, 0.0))
            for record_type in validation_dimension_names
        }
    else:
        validation_record_type_source_share = {
            category: float(raw_validation_shares.get(category, 0.0))
            for category in validation_dimension_names
        }
    minimum_validation_records_per_dimension = all(validation_record_type_minimums.values())
    maximum_validation_share_per_dimension = all(
        share <= settings.lora_benchmark_max_validation_record_share_per_source_per_category
        for share in validation_record_type_source_share.values()
    )
    checks = {
        "minimum_train_records": int(train.get("record_count") or 0) >= settings.lora_benchmark_min_train_records,
        "minimum_validation_records": int(validation.get("record_count") or 0) >= settings.lora_benchmark_min_validation_records,
        "minimum_unique_sources": int(accounting.get("used_source_count") or 0) >= settings.lora_benchmark_min_unique_sources,
        "minimum_unique_content_hashes": int(accounting.get("used_unique_content_hash_count") or 0) >= settings.lora_benchmark_min_unique_content_hashes,
        "maximum_train_record_share_per_source": float(train.get("max_record_share_per_source") or 0.0) <= settings.lora_benchmark_max_train_record_share_per_source,
        "maximum_validation_record_share_per_source": float(validation.get("max_record_share_per_source") or 0.0) <= settings.lora_benchmark_max_validation_record_share_per_source,
        "maximum_train_duplicate_ratio": float(train.get("duplicate_content_ratio") or 0.0) <= settings.lora_max_duplicate_ratio,
        "maximum_validation_duplicate_ratio": float(validation.get("duplicate_content_ratio") or 0.0) <= settings.lora_max_duplicate_ratio,
        "minimum_validation_records_per_record_type": minimum_validation_records_per_dimension,
        "maximum_validation_record_share_per_source_per_record_type": maximum_validation_share_per_dimension,
        "minimum_validation_records_per_category": minimum_validation_records_per_dimension,
        "maximum_validation_record_share_per_source_per_category": maximum_validation_share_per_dimension,
    }
    checks["maximum_validation_record_share_per_source_per_category"] = checks[
        "maximum_validation_record_share_per_source_per_record_type"
    ]
    checks["minimum_validation_records_per_category"] = checks["minimum_validation_records_per_record_type"]
    return {
        "passes": all(checks.values()),
        "checks": checks,
        "used_source_count": int(accounting.get("used_source_count") or 0),
        "used_unique_content_hash_count": int(accounting.get("used_unique_content_hash_count") or 0),
        "train_record_count": int(train.get("record_count") or 0),
        "validation_record_count": int(validation.get("record_count") or 0),
        "train_duplicate_content_ratio": float(train.get("duplicate_content_ratio") or 0.0),
        "validation_duplicate_content_ratio": float(validation.get("duplicate_content_ratio") or 0.0),
        "train_max_record_share_per_source": float(train.get("max_record_share_per_source") or 0.0),
        "validation_max_record_share_per_source": float(validation.get("max_record_share_per_source") or 0.0),
        "validation_record_type_counts": validation_record_type_counts,
        "validation_record_type_minimums": validation_record_type_minimums,
        "validation_max_record_share_per_source_per_record_type": validation_record_type_source_share,
        "minimum_train_records": settings.lora_benchmark_min_train_records,
        "minimum_validation_records": settings.lora_benchmark_min_validation_records,
        "minimum_validation_records_per_record_type": settings.lora_benchmark_min_validation_records_per_category,
        "minimum_unique_sources": settings.lora_benchmark_min_unique_sources,
        "minimum_unique_content_hashes": settings.lora_benchmark_min_unique_content_hashes,
        "maximum_train_record_share_per_source": settings.lora_benchmark_max_train_record_share_per_source,
        "maximum_validation_record_share_per_source": settings.lora_benchmark_max_validation_record_share_per_source,
        "maximum_validation_record_share_per_source_per_record_type": settings.lora_benchmark_max_validation_record_share_per_source_per_category,
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
    with _without_unneeded_transformers_optional_imports():
        from peft import LoraConfig, TaskType, get_peft_model
        from transformers import AutoModelForCausalLM

        base_model_dir = _ensure_test_base_model(Path(str(config["base_model"])).resolve())
        model = AutoModelForCausalLM.from_pretrained(
            str(base_model_dir),
            local_files_only=True,
            trust_remote_code=False,
        )
        adapter = get_peft_model(
            model,
            LoraConfig(
                task_type=TaskType.CAUSAL_LM,
                inference_mode=True,
                r=4,
                lora_alpha=8,
                lora_dropout=0.0,
                target_modules=["c_attn"],
            ),
        )
    adapter.save_pretrained(str(output_dir), safe_serialization=True)


def _ensure_test_base_model(model_dir: Path) -> Path:
    with _without_unneeded_transformers_optional_imports():
        from tokenizers import Tokenizer
        from tokenizers.models import WordLevel
        from tokenizers.pre_tokenizers import Whitespace
        from transformers import GPT2Config, GPT2LMHeadModel, PreTrainedTokenizerFast

        model_dir.mkdir(parents=True, exist_ok=True)
        vocab = {
            "[PAD]": 0,
            "[UNK]": 1,
            "[BOS]": 2,
            "[EOS]": 3,
            ".": 4,
            ",": 5,
            "Reply": 6,
            "with": 7,
            "the": 8,
            "single": 9,
            "word": 10,
            "CML": 11,
            "Using": 12,
            "local": 13,
            "project": 14,
            "context": 15,
            "name": 16,
            "public": 17,
            "V1": 18,
            "release": 19,
            "stance": 20,
            "in": 21,
            "one": 22,
            "short": 23,
            "sentence": 24,
            "According": 25,
            "to": 26,
            "source": 27,
            "retrieval": 28,
            "adapter": 29,
            "training": 30,
            "evidence": 31,
            "strict": 32,
            "evaluation": 33,
            "baseline": 34,
        }
        tokenizer = Tokenizer(WordLevel(vocab=vocab, unk_token="[UNK]"))
        tokenizer.pre_tokenizer = Whitespace()
        fast_tokenizer = PreTrainedTokenizerFast(
            tokenizer_object=tokenizer,
            unk_token="[UNK]",
            pad_token="[PAD]",
            bos_token="[BOS]",
            eos_token="[EOS]",
        )
        fast_tokenizer.save_pretrained(str(model_dir))

        model = GPT2LMHeadModel(
            GPT2Config(
                vocab_size=len(vocab),
                n_positions=128,
                n_ctx=128,
                n_embd=32,
                n_layer=2,
                n_head=4,
                bos_token_id=vocab["[BOS]"],
                eos_token_id=vocab["[EOS]"],
                pad_token_id=vocab["[PAD]"],
            )
        )
        model.save_pretrained(str(model_dir), safe_serialization=True)
    return model_dir


@contextmanager
def _without_unneeded_transformers_optional_imports():
    blocked = {"sklearn", "pandas", "pyarrow"}
    real_find_spec = importlib.util.find_spec

    def find_spec_without_optional_generation_extras(name, *args, **kwargs):
        if str(name).split(".", 1)[0] in blocked:
            return None
        return real_find_spec(name, *args, **kwargs)

    importlib.util.find_spec = find_spec_without_optional_generation_extras
    try:
        yield
    finally:
        importlib.util.find_spec = real_find_spec


def _write_llamafactory_dataset_info(dataset_manifest: dict) -> Path:
    dataset_dir = Path(dataset_manifest["dataset_dir"])
    openai_tags = {
        "role_tag": "role",
        "content_tag": "content",
        "user_tag": "user",
        "assistant_tag": "assistant",
        "observation_tag": "tool",
        "function_tag": "function",
        "system_tag": "system",
    }
    payload = {
        "cml_cluster_train": {
            "file_name": Path(dataset_manifest["train_path"]).name,
            "formatting": "openai",
            "columns": {"messages": "messages"},
            "tags": openai_tags,
        },
        "cml_cluster_validation": {
            "file_name": Path(dataset_manifest["validation_path"]).name,
            "formatting": "openai",
            "columns": {"messages": "messages"},
            "tags": openai_tags,
        },
    }
    path = dataset_dir / "dataset_info.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _package_dataset_artifacts(dataset_manifest: dict, output_dir: Path) -> Path:
    dataset_dir = Path(str(dataset_manifest["dataset_dir"]))
    packaged_dir = output_dir / "dataset"
    packaged_dir.mkdir(parents=True, exist_ok=True)
    for path in dataset_dir.iterdir():
        target = packaged_dir / path.name
        if path.is_dir():
            shutil.copytree(path, target, dirs_exist_ok=True)
            continue
        shutil.copy2(path, target)
    return packaged_dir


def _llamafactory_training_config(dataset_manifest: dict, output_dir: Path, config: dict) -> dict:
    settings = get_settings()
    training_device = str(getattr(settings, "lora_training_device", "auto") or "auto").strip().lower()
    training_dtype = str(getattr(settings, "lora_training_dtype", "auto") or "auto").strip().lower()
    eval_strategy = str(getattr(settings, "lora_training_eval_strategy", "steps") or "steps").strip().lower()
    if eval_strategy not in {"steps", "epoch"}:
        eval_strategy = "steps"
    payload = {
        "model_name_or_path": config["base_model"],
        "stage": "sft",
        "do_train": True,
        "finetuning_type": "lora",
        "lora_target": "all",
        "lora_rank": 8,
        "lora_alpha": 16,
        "lora_dropout": 0.05,
        "dataset_dir": str(dataset_manifest["dataset_dir"]),
        "dataset": "cml_cluster_train",
        "eval_dataset": "cml_cluster_validation",
        "template": config.get("template") or "chatml",
        "cutoff_len": int(config.get("cutoff_len") or 4096),
        "learning_rate": float(config.get("learning_rate") or 0.0002),
        "num_train_epochs": float(config.get("num_train_epochs") or 1),
        "per_device_train_batch_size": int(settings.lora_training_batch_size),
        "gradient_accumulation_steps": int(settings.lora_training_gradient_accumulation_steps),
        "output_dir": str(output_dir),
        "overwrite_output_dir": True,
        "eval_strategy": eval_strategy,
        "save_strategy": eval_strategy,
        "save_total_limit": int(getattr(settings, "lora_training_save_total_limit", 3) or 3),
        "load_best_model_at_end": True,
        "metric_for_best_model": "eval_loss",
        "greater_is_better": False,
        "per_device_eval_batch_size": 1,
        "logging_steps": 1,
        "report_to": "none",
        "use_cpu": training_device == "cpu",
        "fp16": training_dtype == "fp16",
        "bf16": training_dtype == "bf16",
    }
    if eval_strategy == "steps":
        eval_steps = max(1, int(getattr(settings, "lora_training_eval_steps", 200) or 200))
        payload["eval_steps"] = eval_steps
        payload["save_steps"] = eval_steps
    early_stopping_steps = int(getattr(settings, "lora_training_early_stopping_steps", 0) or 0)
    if early_stopping_steps > 0:
        payload["early_stopping_steps"] = early_stopping_steps
    if settings.lora_training_max_steps is not None and int(settings.lora_training_max_steps) > 0:
        payload["max_steps"] = int(settings.lora_training_max_steps)
    return payload


def _trainer_command_argv(
    command_template: str,
    dataset_manifest: dict,
    output_dir: Path,
    config_path: Path,
    *,
    cml_config_path: Path | None = None,
) -> list[str]:
    values = {
        "dataset_dir": str(dataset_manifest["dataset_dir"]),
        "train_path": str(dataset_manifest["train_path"]),
        "validation_path": str(dataset_manifest["validation_path"]),
        "output_dir": str(output_dir),
        "config_path": str(config_path),
        "llamafactory_config_path": str(config_path),
        "cml_config_path": str(cml_config_path or config_path),
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
    if Path(argv[0]).name.lower() in {"llamafactory-cli", "llamafactory-cli.exe", "lmf", "lmf.exe"}:
        resolved = _llamafactory_cli_path()
        if resolved:
            argv[0] = resolved
    return argv


def _looks_like_llamafactory_train_command(command: list[str]) -> bool:
    if len(command) < 2:
        return False
    executable = Path(command[0]).name.lower()
    return executable in {"llamafactory-cli", "llamafactory-cli.exe", "lmf", "lmf.exe"} and command[1] == "train"


def _replace_trainer_placeholders(template: str, values: dict[str, str]) -> str:
    result = template
    for key, value in values.items():
        result = result.replace(f"{{{key}}}", value)
    return result


def _path_with_python_scripts(existing_path: str) -> str:
    scripts_dir = str(sys_executable_dir())
    entries = [item for item in existing_path.split(os.pathsep) if item]
    if scripts_dir.lower() in {item.lower() for item in entries}:
        return existing_path
    return os.pathsep.join([scripts_dir, *entries])


def _trainer_timeout_seconds() -> int:
    raw = os.environ.get("CML_LORA_TRAINER_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return 7200
    try:
        value = int(raw)
    except ValueError:
        return 7200
    return max(300, value)


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
