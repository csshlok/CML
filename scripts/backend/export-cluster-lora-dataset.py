import argparse
import json
from pathlib import Path

from backend.app.core.training_dataset import build_cluster_dataset, write_cluster_training_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a source-level LoRA dataset for a cluster expert.")
    parser.add_argument("--cluster-id", required=True, help="Cluster ID to export from the local database")
    parser.add_argument("--output-dir", required=True, help="Output directory for dataset artifacts")
    parser.add_argument("--train-sources", type=int, default=0, help="Exact number of training sources to export")
    parser.add_argument("--validation-sources", type=int, default=0, help="Exact number of validation sources to export")
    args = parser.parse_args()

    dataset = build_cluster_dataset(args.cluster_id)
    if args.train_sources > 0 or args.validation_sources > 0:
        dataset["train_source_target"] = int(args.train_sources)
        dataset["validation_source_target"] = int(args.validation_sources)

    manifest = write_cluster_training_dataset(dataset, Path(args.output_dir))
    print(
        json.dumps(
            {
                "cluster_id": manifest["cluster_id"],
                "dataset_hash": manifest["dataset_hash"],
                "source_count": manifest["source_count"],
                "train_source_count": manifest.get("train_source_count"),
                "validation_source_count": manifest.get("validation_source_count"),
                "train_path": manifest["train_path"],
                "validation_path": manifest["validation_path"],
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
