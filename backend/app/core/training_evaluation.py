from __future__ import annotations


def cluster_dataset_structural_readiness_score(dataset: dict) -> float:
    score = 0.0

    source_count = int(dataset.get("source_count", 0) or 0)
    documents = list(dataset.get("documents") or [])

    if source_count >= 20:
        score += 40
    elif source_count >= 10:
        score += 30
    elif source_count >= 5:
        score += 20

    total_text = sum(len(str(doc.get("text", "") or "")) for doc in documents)

    if total_text >= 50000:
        score += 40
    elif total_text >= 20000:
        score += 30
    elif total_text >= 5000:
        score += 20

    summaries_present = sum(
        1
        for doc in documents
        if len(str(doc.get("summary", "") or "").strip()) > 20
    )

    if summaries_present >= source_count and source_count > 0:
        score += 20
    elif summaries_present >= max(1, source_count // 2):
        score += 10

    return min(score, 100.0)


def adapter_artifact_structural_readiness(
    *,
    dataset_structural_score: float,
    adapter_dir_exists: bool,
    adapter_valid: bool = False,
    validation_count: int,
) -> dict:
    adapter_bonus = 25.0 if adapter_dir_exists and adapter_valid else 0.0
    validation_bonus = 15.0 if validation_count > 0 else 0.0
    artifact_structural_score = min(100.0, (dataset_structural_score * 0.6) + adapter_bonus + validation_bonus)
    return {
        "structural_readiness_only": True,
        "detail": (
            "Legacy structural readiness heuristic only. "
            "This is not a bundle-quality gate and must not be used as activation or release proof."
        ),
        "dataset_structural_score": round(dataset_structural_score, 2),
        "artifact_structural_score": round(artifact_structural_score, 2),
        "structural_delta": round(artifact_structural_score - dataset_structural_score, 2),
        "validation_count": int(validation_count),
        "adapter_dir_exists": bool(adapter_dir_exists),
        "adapter_valid": bool(adapter_valid),
    }


def evaluate_cluster_dataset(dataset: dict) -> float:
    return cluster_dataset_structural_readiness_score(dataset)


def evaluate_adapter_quality(
    *,
    dataset_score: float,
    adapter_dir_exists: bool,
    adapter_valid: bool = False,
    validation_count: int,
) -> dict:
    report = adapter_artifact_structural_readiness(
        dataset_structural_score=dataset_score,
        adapter_dir_exists=adapter_dir_exists,
        adapter_valid=adapter_valid,
        validation_count=validation_count,
    )
    return {
        **report,
        "retrieval_only_score": report["dataset_structural_score"],
        "adapter_score": report["artifact_structural_score"],
        "quality_delta": report["structural_delta"],
    }
