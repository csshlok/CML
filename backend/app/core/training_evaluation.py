def evaluate_cluster_dataset(dataset: dict) -> float:
    score = 0.0

    source_count = dataset.get("source_count", 0)
    documents = dataset.get("documents", [])

    if source_count >= 20:
        score += 40
    elif source_count >= 10:
        score += 30
    elif source_count >= 5:
        score += 20

    total_text = sum(len(doc.get("text", "")) for doc in documents)

    if total_text >= 50000:
        score += 40
    elif total_text >= 20000:
        score += 30
    elif total_text >= 5000:
        score += 20

    summaries_present = sum(
        1
        for doc in documents
        if len(doc.get("summary", "").strip()) > 20
    )

    if summaries_present >= source_count and source_count > 0:
        score += 20
    elif summaries_present >= max(1, source_count // 2):
        score += 10

    return min(score, 100.0)


def evaluate_adapter_quality(*, dataset_score: float, adapter_dir_exists: bool, validation_count: int) -> dict:
    adapter_bonus = 25.0 if adapter_dir_exists else 0.0
    validation_bonus = 15.0 if validation_count > 0 else 0.0
    score = min(100.0, (dataset_score * 0.6) + adapter_bonus + validation_bonus)
    return {
        "retrieval_only_score": round(dataset_score, 2),
        "adapter_score": round(score, 2),
        "quality_delta": round(score - dataset_score, 2),
        "validation_count": validation_count,
        "adapter_dir_exists": adapter_dir_exists,
    }
