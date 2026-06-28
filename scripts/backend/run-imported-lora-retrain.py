import argparse
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from backend.app.core.lora_training import run_lora_training_process


def main() -> None:
    parser = argparse.ArgumentParser(description="Run LoRA retraining from an imported dataset directory.")
    parser.add_argument("--dataset-dir", required=True)
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--adapter-name", default="")
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--cutoff-len", type=int, default=2048)
    parser.add_argument("--learning-rate", type=float, default=0.0002)
    parser.add_argument("--template", default="chatml")
    parser.add_argument("--eval-steps", type=int, default=1000)
    parser.add_argument("--early-stopping-steps", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=4)
    parser.add_argument("--save-total-limit", type=int, default=3)
    parser.add_argument("--trainer-validation-max-per-record-type", type=int, default=20)
    args = parser.parse_args()

    dataset_dir = Path(args.dataset_dir).resolve()
    work_dir = Path(args.work_dir).resolve()
    experts_root = work_dir / "experts" / "cluster-smoke"
    experts_root.mkdir(parents=True, exist_ok=True)
    adapter_name = args.adapter_name.strip() or f"adapter-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    output_dir = experts_root / adapter_name
    output_dir.mkdir(parents=True, exist_ok=True)
    prepared_dataset_dir = prepare_training_dataset(
        source_dataset_dir=dataset_dir,
        prepared_dataset_dir=work_dir / "datasets" / adapter_name,
        validation_max_per_record_type=int(args.trainer_validation_max_per_record_type),
    )

    dataset_manifest = load_dataset_manifest(prepared_dataset_dir)
    config = {
        "base_model": str(Path(args.base_model).resolve()),
        "num_train_epochs": float(args.epochs),
        "cutoff_len": int(args.cutoff_len),
        "learning_rate": float(args.learning_rate),
        "template": str(args.template),
        "dataset_hash": str(dataset_manifest.get("dataset_hash") or ""),
        "expert_objective_version": str(dataset_manifest.get("expert_objective_version") or ""),
    }
    os.environ["CML_LORA_TRAINING_EVAL_STEPS"] = str(int(args.eval_steps))
    os.environ["CML_LORA_TRAINING_EARLY_STOPPING_STEPS"] = str(int(args.early_stopping_steps))
    os.environ["CML_LORA_TRAINING_BATCH_SIZE"] = str(max(1, int(args.batch_size)))
    os.environ["CML_LORA_TRAINING_GRADIENT_ACCUMULATION_STEPS"] = str(
        max(1, int(args.gradient_accumulation_steps))
    )
    os.environ["CML_LORA_TRAINING_SAVE_TOTAL_LIMIT"] = str(max(1, int(args.save_total_limit)))
    result = run_lora_training_process(
        dataset_manifest=dataset_manifest,
        output_dir=output_dir,
        config=config,
    )
    payload = {
        "work_dir": str(work_dir),
        "adapter_dir": str(output_dir),
        **result,
    }
    print(json.dumps(payload, indent=2))


def load_dataset_manifest(dataset_dir: Path) -> dict:
    manifest_path = dataset_dir / "dataset-manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    payload["dataset_dir"] = str(dataset_dir)
    payload["train_path"] = str(dataset_dir / "train.jsonl")
    payload["validation_path"] = str(dataset_dir / "validation.jsonl")
    return payload


def prepare_training_dataset(
    *,
    source_dataset_dir: Path,
    prepared_dataset_dir: Path,
    validation_max_per_record_type: int,
) -> Path:
    if prepared_dataset_dir.exists():
        shutil.rmtree(prepared_dataset_dir)
    shutil.copytree(source_dataset_dir, prepared_dataset_dir)
    if validation_max_per_record_type > 0:
        validation_path = prepared_dataset_dir / "validation.jsonl"
        rows = [
            json.loads(line)
            for line in validation_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        kept = []
        per_type_counts: dict[str, int] = {}
        for row in rows:
            record_type = str(row.get("record_type") or "")
            if per_type_counts.get(record_type, 0) >= validation_max_per_record_type:
                continue
            kept.append(row)
            per_type_counts[record_type] = per_type_counts.get(record_type, 0) + 1
        validation_path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=True) for row in kept) + ("\n" if kept else ""),
            encoding="utf-8",
        )
        manifest_path = prepared_dataset_dir / "dataset-manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["validation_count"] = len(kept)
            accounting = dict(manifest.get("benchmark_record_accounting") or {})
            validation = dict(accounting.get("validation") or {})
            validation["count"] = len(kept)
            validation["record_type_counts"] = dict(per_type_counts)
            validation["minimum_validation_records_per_category"] = min(per_type_counts.values(), default=0)
            accounting["validation"] = validation
            manifest["benchmark_record_accounting"] = accounting
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return prepared_dataset_dir


if __name__ == "__main__":
    main()
