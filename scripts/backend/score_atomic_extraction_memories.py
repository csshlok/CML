from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_GATES = (
    REPO_ROOT / "backend/tests/fixtures/atomic_memory_v2_semantic_gates.json"
)
SCORER_PROTOCOL = "atomic-memory-semantic-scorer-v2-critical-field-aware"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Score extracted natural-language memories against independent references "
            "with a local GPU sentence encoder."
        )
    )
    parser.add_argument("--matrix-report", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path.home() / ".cache" / "huggingface",
    )
    parser.add_argument("--similarity-threshold", type=float, default=0.70)
    parser.add_argument(
        "--memory-layer",
        choices=("production_evidence", "propositions"),
        default="production_evidence",
        help="Score the compiler-accepted production representation by default.",
    )
    parser.add_argument("--gates", type=Path, default=DEFAULT_GATES)
    parser.add_argument(
        "--allow-model-download",
        action="store_true",
        help="Allow a one-time encoder download when it is not already cached.",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--allow-holdout-details",
        action="store_true",
        help="Include per-fixture holdout results. Aggregate-only is the safe default.",
    )
    return parser.parse_args()


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _modality(value: str) -> str:
    text = value.casefold()
    patterns = (
        ("negated", r"\b(?:no|not|never|didn't|doesn't|don't|cannot|can't)\b"),
        ("uncertain", r"\b(?:might|may|perhaps|possibly|uncertain|not decided)\b"),
        ("hypothetical", r"\b(?:if|would|could have|might have)\b"),
        (
            "recommended",
            r"\b(?:recommend(?:s|ed|ing)?|should|suggest(?:s|ed|ing)?)\b",
        ),
        ("planned", r"\b(?:plan|plans|planned|intend|intends|will|going to)\b"),
        ("ongoing", r"\b(?:currently|ongoing|still)\b"),
    )
    for name, pattern in patterns:
        if re.search(pattern, text):
            return name
    return "asserted_or_completed"


def _critical_slots(value: str) -> dict[str, set[str]]:
    """Extract fields whose disagreement must never be hidden by embeddings."""
    normalized = " ".join(value.split())
    numbers = {
        match.replace(",", "").casefold()
        for match in re.findall(
            r"(?<![\w.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?",
            normalized,
        )
    }
    dates = {
        match.casefold().replace(",", "")
        for match in re.findall(
            r"\b(?:20\d{2}-\d{1,2}-\d{1,2}|"
            r"(?:January|February|March|April|May|June|July|August|"
            r"September|October|November|December)\s+\d{1,2}(?:,\s*20\d{2})?)\b",
            normalized,
            flags=re.IGNORECASE,
        )
    }
    speakers = {
        token
        for token in ("user", "assistant", "tool")
        if re.search(rf"\b{token}\b", normalized, flags=re.IGNORECASE)
    }
    named_entities = {
        " ".join(match.casefold().replace(".", "").split())
        for match in re.findall(
            r"\b(?:Dr|Prof|Mr|Mrs|Ms)\.?\s+[A-Z][A-Za-z'-]*\b|"
            r"\b[A-Z][A-Za-z'-]+(?:\s+[A-Z][A-Za-z'-]+)+\b",
            normalized,
        )
    }
    return {
        "numbers": numbers,
        "dates": dates,
        "speakers": speakers,
        "named_entities": named_entities,
    }


def _compatible(reference: str, prediction: str) -> bool:
    reference_modality = _modality(reference)
    prediction_modality = _modality(prediction)
    protected = {
        "negated",
        "uncertain",
        "hypothetical",
        "recommended",
        "planned",
        "ongoing",
    }
    if not (
        reference_modality == prediction_modality
        if reference_modality in protected or prediction_modality in protected
        else True
    ):
        return False
    reference_slots = _critical_slots(reference)
    prediction_slots = _critical_slots(prediction)
    return all(
        reference_slots[name] == prediction_slots[name]
        for name in reference_slots
        if reference_slots[name] or prediction_slots[name]
    )


def score_fixture_vectors(
    references: list[str],
    predictions: list[str],
    similarities: np.ndarray,
    *,
    threshold: float,
) -> dict:
    if similarities.shape != (len(references), len(predictions)):
        raise ValueError("semantic_similarity_shape_mismatch")
    above_threshold_pairs = [
        (float(similarities[left, right]), left, right)
        for left in range(len(references))
        for right in range(len(predictions))
        if float(similarities[left, right]) >= threshold
    ]
    protected_field_mismatch_pair_count = sum(
        not _compatible(references[left], predictions[right])
        for _, left, right in above_threshold_pairs
    )
    candidates = sorted(
        (
            (similarity, left, right)
            for similarity, left, right in above_threshold_pairs
            if _compatible(references[left], predictions[right])
        ),
        reverse=True,
    )
    matched_references: set[int] = set()
    matched_predictions: set[int] = set()
    matches: list[dict] = []
    for similarity, reference_index, prediction_index in candidates:
        if (
            reference_index in matched_references
            or prediction_index in matched_predictions
        ):
            continue
        matched_references.add(reference_index)
        matched_predictions.add(prediction_index)
        matches.append(
            {
                "reference_index": reference_index,
                "prediction_index": prediction_index,
                "similarity": round(similarity, 6),
            }
        )
    match_count = len(matches)
    recall = match_count / len(references) if references else float(not predictions)
    precision = match_count / len(predictions) if predictions else float(not references)
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return {
        "reference_count": len(references),
        "prediction_count": len(predictions),
        "match_count": match_count,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "matches": matches,
        "protected_field_mismatch_pair_count": (
            protected_field_mismatch_pair_count
        ),
        "unmatched_reference_indices": sorted(
            set(range(len(references))) - matched_references
        ),
        "unmatched_prediction_indices": sorted(
            set(range(len(predictions))) - matched_predictions
        ),
    }


def evaluate_semantic_gates(metrics: dict, gate_manifest: dict) -> dict:
    checks: dict[str, bool] = {}
    for name, threshold in gate_manifest["thresholds"].items():
        if name.endswith("_min"):
            metric = name.removesuffix("_min")
            checks[name] = float(metrics.get(metric, 0.0)) >= float(threshold)
        elif name.endswith("_max"):
            metric = name.removesuffix("_max")
            checks[name] = float(metrics.get(metric, float("inf"))) <= float(
                threshold
            )
        else:
            raise ValueError(f"gate threshold must end in _min or _max: {name}")
    return {
        "gate_version": gate_manifest["gate_version"],
        "passed": all(checks.values()),
        "checks": checks,
        "failed_checks": sorted(name for name, passed in checks.items() if not passed),
    }


def _encode(
    texts: list[str],
    *,
    model_name: str,
    cache_dir: Path,
    allow_model_download: bool,
) -> np.ndarray:
    import torch
    from sentence_transformers import SentenceTransformer

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required; CPU semantic scoring fallback is disabled")
    model = SentenceTransformer(
        model_name,
        cache_folder=str(cache_dir),
        local_files_only=not allow_model_download,
        device="cuda",
    )
    vectors = model.encode(
        texts,
        batch_size=64,
        normalize_embeddings=True,
        show_progress_bar=False,
        device="cuda",
    )
    return np.asarray(vectors, dtype=np.float32)


def _candidate_report(
    candidate: dict,
    fixtures_by_id: dict[str, dict],
    *,
    model_name: str,
    cache_dir: Path,
    threshold: float,
    include_details: bool,
    allow_model_download: bool,
    memory_layer: str,
) -> dict:
    rows: list[tuple[dict, list[str], list[str]]] = []
    all_texts: list[str] = []
    for result in candidate["fixtures"]:
        fixture = fixtures_by_id[str(result["fixture_id"])]
        references = [str(item) for item in fixture.get("reference_memories") or []]
        semantic_memories = (
            result.get("accepted_evidence_memories") or []
            if memory_layer == "production_evidence"
            else result.get("proposition_memories") or []
        )
        predictions = [
            str(item["memory_text"])
            for item in semantic_memories
            if str(item.get("memory_text") or "").strip()
        ]
        rows.append((result, references, predictions))
        all_texts.extend(references)
        all_texts.extend(predictions)

    vectors = _encode(
        all_texts,
        model_name=model_name,
        cache_dir=cache_dir,
        allow_model_download=allow_model_download,
    )
    cursor = 0
    scored: list[dict] = []
    for result, references, predictions in rows:
        reference_vectors = vectors[cursor : cursor + len(references)]
        cursor += len(references)
        prediction_vectors = vectors[cursor : cursor + len(predictions)]
        cursor += len(predictions)
        similarities = (
            reference_vectors @ prediction_vectors.T
            if references and predictions
            else np.zeros((len(references), len(predictions)), dtype=np.float32)
        )
        score = score_fixture_vectors(
            references,
            predictions,
            similarities,
            threshold=threshold,
        )
        score["fixture_id"] = result["fixture_id"]
        if include_details:
            score["references"] = references
            score["predictions"] = predictions
        scored.append(score)

    reference_count = sum(row["reference_count"] for row in scored)
    prediction_count = sum(row["prediction_count"] for row in scored)
    match_count = sum(row["match_count"] for row in scored)
    micro_precision = match_count / prediction_count if prediction_count else 0.0
    micro_recall = match_count / reference_count if reference_count else 0.0
    micro_f1 = (
        2 * micro_precision * micro_recall / (micro_precision + micro_recall)
        if micro_precision + micro_recall
        else 0.0
    )
    structural_metrics = dict(candidate.get("metrics") or {})
    output = {
        "candidate": candidate["candidate"],
        "fixture_count": len(scored),
        "reference_count": reference_count,
        "prediction_count": prediction_count,
        "match_count": match_count,
        "micro_precision": micro_precision,
        "micro_recall": micro_recall,
        "micro_f1": micro_f1,
        "macro_precision": (
            sum(row["precision"] for row in scored) / len(scored) if scored else 0.0
        ),
        "macro_recall": (
            sum(row["recall"] for row in scored) / len(scored) if scored else 0.0
        ),
        "macro_f1": sum(row["f1"] for row in scored) / len(scored) if scored else 0.0,
        "empty_fixture_false_positive_count": sum(
            bool(not row["reference_count"] and row["prediction_count"]) for row in scored
        ),
        "protected_field_mismatch_pair_count": sum(
            row["protected_field_mismatch_pair_count"] for row in scored
        ),
        "structural_metrics": structural_metrics,
    }
    if include_details:
        output["fixtures"] = scored
    return output


def main() -> int:
    args = parse_args()
    if not 0.0 < args.similarity_threshold <= 1.0:
        raise ValueError("similarity_threshold_must_be_in_0_1")
    matrix = json.loads(args.matrix_report.read_text(encoding="utf-8"))
    fixture_bundle = json.loads(args.fixtures.read_text(encoding="utf-8"))
    gate_manifest = json.loads(args.gates.read_text(encoding="utf-8"))
    fixtures = fixture_bundle.get("fixtures") or []
    fixtures_by_id = {str(item["id"]): item for item in fixtures}
    if any(not isinstance(item.get("reference_memories"), list) for item in fixtures):
        raise ValueError("every_semantic_fixture_requires_reference_memories")
    role = str(fixture_bundle.get("evaluation_role") or "development")
    include_details = role != "holdout" or args.allow_holdout_details
    reports = [
        _candidate_report(
            candidate,
            fixtures_by_id,
            model_name=args.model,
            cache_dir=args.cache_dir,
            threshold=args.similarity_threshold,
            include_details=include_details,
            allow_model_download=args.allow_model_download,
            memory_layer=args.memory_layer,
        )
        for candidate in matrix["reports"]
    ]
    for report in reports:
        gate_metrics = {
            **report["structural_metrics"],
            **{
                key: value
                for key, value in report.items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            },
        }
        report["gate"] = evaluate_semantic_gates(gate_metrics, gate_manifest)
    payload = {
        "protocol": SCORER_PROTOCOL,
        "source_matrix_protocol": matrix.get("protocol"),
        "fixture_version": fixture_bundle.get("fixture_version"),
        "fixture_canonical_sha256": _fingerprint(fixture_bundle),
        "fixture_file_sha256": hashlib.sha256(args.fixtures.read_bytes()).hexdigest(),
        "evaluation_role": role,
        "holdout_details_redacted": role == "holdout" and not include_details,
        "encoder": args.model,
        "device": "cuda",
        "cpu_fallback_allowed": False,
        "model_download_allowed_for_this_run": args.allow_model_download,
        "similarity_threshold": args.similarity_threshold,
        "memory_layer": args.memory_layer,
        "gate_version": gate_manifest["gate_version"],
        "reports": reports,
    }
    output = args.output or args.matrix_report.with_name("semantic-score-report.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"wrote {output}")
    return 0 if all(report["gate"]["passed"] for report in reports) else 2


if __name__ == "__main__":
    raise SystemExit(main())
