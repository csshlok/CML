import argparse
import json
from pathlib import Path

from backend.app.core.training_dataset import build_path_text_dataset, write_cluster_training_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a LoRA dataset from real text files on disk.")
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--dataset-name", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--train-sources", type=int, required=True)
    parser.add_argument("--validation-sources", type=int, required=True)
    parser.add_argument("--source-path", action="append", required=True, dest="source_paths")
    parser.add_argument("--minimum-chars", type=int, default=400)
    args = parser.parse_args()

    dataset = build_path_text_dataset(
        dataset_id=args.dataset_id,
        dataset_name=args.dataset_name,
        source_paths=[Path(item) for item in args.source_paths],
        minimum_chars=int(args.minimum_chars),
    )
    dataset["train_source_target"] = int(args.train_sources)
    dataset["validation_source_target"] = int(args.validation_sources)
    manifest = write_cluster_training_dataset(dataset, Path(args.output_dir))
    print(
        json.dumps(
            {
                "dataset_hash": manifest["dataset_hash"],
                "source_count": manifest["source_count"],
                "train_source_count": manifest["train_source_count"],
                "validation_source_count": manifest["validation_source_count"],
                "train_sources_path": manifest["train_sources_path"],
                "validation_sources_path": manifest["validation_sources_path"],
                "train_corpus_path": manifest["train_corpus_path"],
                "validation_corpus_path": manifest["validation_corpus_path"],
                "train_qa_path": manifest["train_qa_path"],
                "validation_qa_path": manifest["validation_qa_path"],
                "manifest_path": manifest["manifest_path"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
