import json
from pathlib import Path

from backend.app.core.config import get_settings


def create_expert_profile(dataset: dict) -> str:
    settings = get_settings()

    experts_dir = settings.data_dir / "experts"
    experts_dir.mkdir(parents=True, exist_ok=True)

    profile_path = experts_dir / f"{dataset['cluster_id']}.json"

    profile = {
        "cluster_id": dataset["cluster_id"],
        "cluster_name": dataset["cluster_name"],
        "source_count": dataset["source_count"],
        "document_titles": [
            doc["title"]
            for doc in dataset["documents"]
        ],
    }

    profile_path.write_text(
        json.dumps(profile, indent=2),
        encoding="utf-8",
    )

    return str(profile_path)