from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = "atomic-extractor-qwen3-4b-qlora-v1"
REQUIRED_PACKAGES = (
    "torch",
    "transformers",
    "peft",
    "trl",
    "datasets",
    "bitsandbytes",
    "accelerate",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="GPU-only QLoRA training for the two-pass Atomic Memory extractor."
    )
    parser.add_argument("--model", required=True, help="Local Qwen3 4B model directory.")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--learning-rate", type=float, default=1.0e-4)
    parser.add_argument("--max-length", type=int, default=1536)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=16)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument("--save-steps", type=int, default=100)
    parser.add_argument("--eval-steps", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260723)
    parser.add_argument("--resume-from-checkpoint")
    parser.add_argument(
        "--allow-network-model-download",
        action="store_true",
        help="Disabled by default so training cannot silently fetch another checkpoint.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate frozen data, CUDA, packages, and configuration without loading a model.",
    )
    return parser.parse_args()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _package_versions() -> dict[str, str]:
    return {name: importlib.metadata.version(name) for name in REQUIRED_PACKAGES}


def _git_state() -> dict:
    def run(*args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    return {
        "commit": run("rev-parse", "HEAD"),
        "dirty": bool(run("status", "--porcelain")),
    }


def validate_inputs(args: argparse.Namespace) -> dict:
    train_path = args.data_dir / "train.jsonl"
    validation_path = args.data_dir / "validation.jsonl"
    data_manifest_path = args.data_dir / "training-data-manifest.json"
    for path in (train_path, validation_path, data_manifest_path):
        if not path.exists():
            raise ValueError(f"missing_training_artifact:{path}")
    manifest = json.loads(data_manifest_path.read_text(encoding="utf-8"))
    if manifest.get("protocol") != "atomic-extractor-independent-training-corpus-v1":
        raise ValueError("unexpected_training_data_protocol")
    if manifest.get("evaluation_role") != "training":
        raise ValueError("training_data_must_have_training_role")
    if not manifest.get("training_ready"):
        raise ValueError("training_data_manifest_is_not_training_ready")
    expected = manifest.get("output_sha256") or {}
    actual = {"train": _sha256(train_path), "validation": _sha256(validation_path)}
    if expected != actual:
        raise ValueError("training_data_hash_mismatch")
    if args.max_length < 512:
        raise ValueError("max_length_below_safe_extraction_minimum")
    if args.batch_size != 1:
        raise ValueError("universal_6gb_recipe_requires_batch_size_one")
    if args.lora_r <= 0 or args.lora_alpha <= 0:
        raise ValueError("invalid_lora_configuration")
    return {
        "data_manifest_sha256": _sha256(data_manifest_path),
        "data_sha256": actual,
        "record_count": int(manifest["record_count"]),
        "sft_example_count": int(manifest["sft_example_count"]),
    }


def cuda_preflight() -> dict:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("cuda_required_cpu_fallback_forbidden")
    device = torch.cuda.get_device_properties(0)
    return {
        "cuda_device": torch.cuda.get_device_name(0),
        "cuda_capability": list(torch.cuda.get_device_capability(0)),
        "total_vram_bytes": int(device.total_memory),
        "torch_cuda_version": torch.version.cuda,
        "bf16_supported": bool(torch.cuda.is_bf16_supported()),
    }


def _training_configuration(args: argparse.Namespace) -> dict:
    return {
        "epochs": args.epochs,
        "learning_rate": args.learning_rate,
        "max_length": args.max_length,
        "batch_size": args.batch_size,
        "gradient_accumulation_steps": args.gradient_accumulation_steps,
        "lora_r": args.lora_r,
        "lora_alpha": args.lora_alpha,
        "lora_dropout": args.lora_dropout,
        "save_steps": args.save_steps,
        "eval_steps": args.eval_steps,
        "seed": args.seed,
        "quantization": "bitsandbytes-nf4-double-quant",
        "target_modules": [
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
        "cpu_fallback": False,
    }


def run_training(args: argparse.Namespace, preflight: dict) -> dict:
    import torch
    from datasets import load_dataset
    from peft import LoraConfig, prepare_model_for_kbit_training
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        set_seed,
    )
    from trl import SFTConfig, SFTTrainer

    set_seed(args.seed)
    dtype = torch.bfloat16 if preflight["bf16_supported"] else torch.float16
    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=dtype,
    )
    local_only = not args.allow_network_model_download
    tokenizer = AutoTokenizer.from_pretrained(
        args.model,
        trust_remote_code=False,
        local_files_only=local_only,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        quantization_config=quantization,
        torch_dtype=dtype,
        device_map={"": 0},
        trust_remote_code=False,
        local_files_only=local_only,
    )
    if any(parameter.device.type == "cpu" for parameter in model.parameters()):
        raise RuntimeError("model_cpu_offload_detected_cpu_fallback_forbidden")
    model = prepare_model_for_kbit_training(
        model, use_gradient_checkpointing=True
    )
    peft_config = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=_training_configuration(args)["target_modules"],
    )
    dataset = load_dataset(
        "json",
        data_files={
            "train": str(args.data_dir / "train.jsonl"),
            "validation": str(args.data_dir / "validation.jsonl"),
        },
    )
    training_args = SFTConfig(
        output_dir=str(args.output_dir / "checkpoints"),
        num_train_epochs=args.epochs,
        learning_rate=args.learning_rate,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        max_length=args.max_length,
        gradient_checkpointing=True,
        optim="paged_adamw_8bit",
        bf16=preflight["bf16_supported"],
        fp16=not preflight["bf16_supported"],
        tf32=True,
        eval_strategy="steps",
        eval_steps=args.eval_steps,
        save_strategy="steps",
        save_steps=args.save_steps,
        save_total_limit=3,
        logging_steps=10,
        completion_only_loss=True,
        report_to="none",
        seed=args.seed,
        data_seed=args.seed,
        use_cpu=False,
    )
    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset["train"],
        eval_dataset=dataset["validation"],
        processing_class=tokenizer,
        peft_config=peft_config,
    )
    started = time.time()
    result = trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)
    adapter_dir = args.output_dir / "adapter"
    trainer.save_model(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    evaluation = trainer.evaluate()
    peak = int(torch.cuda.max_memory_allocated(0))
    return {
        "train_metrics": result.metrics,
        "validation_metrics": evaluation,
        "wall_seconds": round(time.time() - started, 3),
        "peak_cuda_memory_bytes": peak,
        "adapter_dir": str(adapter_dir),
    }


def main() -> int:
    args = parse_args()
    try:
        inputs = validate_inputs(args)
        packages = _package_versions()
        preflight = cuda_preflight()
    except (ImportError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "protocol": PROTOCOL,
        "status": "preflight_passed" if args.dry_run else "training",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": args.model,
        "model_path_exists": Path(args.model).exists(),
        "network_model_download_allowed": args.allow_network_model_download,
        "inputs": inputs,
        "packages": packages,
        "cuda": preflight,
        "configuration": _training_configuration(args),
        "git": _git_state(),
        "environment": {
            "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        },
    }
    manifest_path = args.output_dir / "training-run-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if args.dry_run:
        print(json.dumps(manifest, indent=2))
        return 0
    try:
        result = run_training(args, preflight)
    except (OSError, RuntimeError, ValueError) as exc:
        manifest["status"] = "failed"
        manifest["error"] = f"{type(exc).__name__}:{str(exc)[:1000]}"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        raise
    manifest["status"] = "completed"
    manifest["result"] = result
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
