import argparse
import json
from pathlib import Path

from backend.app.core.external_lora_dataset import (
    SQUAD_CONFIG,
    SQUAD_VALIDATION_SPLIT,
    WIKIPEDIA_CONFIG,
    WIKIPEDIA_SPLIT,
    build_wikipedia_training_dataset,
    export_squad_qa_files,
    write_external_training_dataset,
    write_external_dataset_manifest,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Wikipedia + SQuAD v2 into the LoRA retrain dataset layout.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--dataset-id", default="wiki-squad-hybrid-v1")
    parser.add_argument("--dataset-name", default="Wikipedia + SQuAD Hybrid V1")
    parser.add_argument("--train-sources", type=int, default=700)
    parser.add_argument("--validation-sources", type=int, default=300)
    parser.add_argument("--wikipedia-config", default=WIKIPEDIA_CONFIG)
    parser.add_argument("--wikipedia-split", default=WIKIPEDIA_SPLIT)
    parser.add_argument("--squad-config", default=SQUAD_CONFIG)
    parser.add_argument("--squad-validation-split", default=SQUAD_VALIDATION_SPLIT)
    parser.add_argument("--squad-train-limit", type=int, default=0)
    parser.add_argument("--squad-validation-limit", type=int, default=0)
    parser.add_argument("--minimum-chars", type=int, default=1500)
    parser.add_argument("--maximum-chars", type=int, default=20000)
    parser.add_argument("--max-scan", type=int, default=10000)
    parser.add_argument("--retries", type=int, default=3)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    dataset = build_wikipedia_training_dataset(
        dataset_id=args.dataset_id,
        dataset_name=args.dataset_name,
        train_source_target=int(args.train_sources),
        validation_source_target=int(args.validation_sources),
        config=args.wikipedia_config,
        split=args.wikipedia_split,
        minimum_chars=int(args.minimum_chars),
        maximum_chars=int(args.maximum_chars),
        max_scan=int(args.max_scan),
        retries=int(args.retries),
    )
    source_manifest = write_external_training_dataset(dataset, output_dir)
    qa_manifest = export_squad_qa_files(
        output_dir,
        config=args.squad_config,
        train_limit=int(args.squad_train_limit) or None,
        validation_limit=int(args.squad_validation_limit) or None,
        retries=int(args.retries),
    )

    manifest_path = output_dir / "dataset-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "dataset_label": args.dataset_id,
            "external_corpus_dataset": "wikimedia/wikipedia",
            "external_corpus_config": args.wikipedia_config,
            "external_corpus_split": args.wikipedia_split,
            "external_qa_dataset": "rajpurkar/squad_v2",
            "external_qa_config": args.squad_config,
            "external_qa_validation_split": args.squad_validation_split,
            "train_qa_path": qa_manifest["train_qa_path"],
            "validation_qa_path": qa_manifest["validation_qa_path"],
            "squad_validation_prompts_path": qa_manifest["squad_validation_prompts_path"],
            "squad_train_count": qa_manifest["squad_train_count"],
            "squad_validation_count": qa_manifest["squad_validation_count"],
            "selected_source_ids_sample": [doc["source_id"] for doc in dataset["documents"][:10]],
        }
    )
    write_external_dataset_manifest(manifest_path, manifest)

    print(
        json.dumps(
            {
                "dataset_dir": str(output_dir),
                "manifest_path": str(manifest_path),
                "train_source_count": source_manifest["train_source_count"],
                "validation_source_count": source_manifest["validation_source_count"],
                "squad_train_count": qa_manifest["squad_train_count"],
                "squad_validation_count": qa_manifest["squad_validation_count"],
                "train_corpus_path": source_manifest["train_corpus_path"],
                "validation_corpus_path": source_manifest["validation_corpus_path"],
                "train_qa_path": qa_manifest["train_qa_path"],
                "validation_qa_path": qa_manifest["validation_qa_path"],
                "squad_validation_prompts_path": qa_manifest["squad_validation_prompts_path"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
