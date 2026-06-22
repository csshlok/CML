from __future__ import annotations

import json
import re
from pathlib import Path

from backend.app.core.config import get_settings


_CATEGORY_SPECS = {
    "factual_recall": {
        "owner": "retrieval",
        "counts_toward_graduation": False,
        "requires_citation": True,
        "markers": [],
    },
    "citation_grounding": {
        "owner": "retrieval",
        "counts_toward_graduation": False,
        "requires_citation": True,
        "markers": [],
    },
    "contradiction_handling": {
        "owner": "retrieval",
        "counts_toward_graduation": False,
        "requires_citation": False,
        "markers": ["trust", "evidence", "unverified"],
    },
    "summarization": {
        "owner": "shared",
        "counts_toward_graduation": True,
        "requires_citation": True,
        "markers": ["-", "grounded"],
    },
    "style_transfer": {
        "owner": "adapter",
        "counts_toward_graduation": True,
        "requires_citation": False,
        "markers": ["practical", "note", "actionable"],
    },
    "terminology_consistency": {
        "owner": "adapter",
        "counts_toward_graduation": True,
        "requires_citation": False,
        "markers": ["preferred", "local terms", "terminology"],
    },
    "reasoning_pattern": {
        "owner": "adapter",
        "counts_toward_graduation": True,
        "requires_citation": False,
        "markers": ["first", "then", "therefore"],
    },
    "out_of_scope_refusal": {
        "owner": "shared",
        "counts_toward_graduation": True,
        "requires_citation": False,
        "markers": ["missing", "not covered", "insufficient"],
    },
}

EVALUATION_CATEGORIES = tuple(_CATEGORY_SPECS)
GRADUATION_CATEGORIES = tuple(
    category for category, spec in _CATEGORY_SPECS.items() if spec["counts_toward_graduation"]
)
DIAGNOSTIC_ONLY_CATEGORIES = tuple(
    category for category, spec in _CATEGORY_SPECS.items() if not spec["counts_toward_graduation"]
)
ADAPTER_OWNED_CATEGORIES = tuple(
    category for category, spec in _CATEGORY_SPECS.items() if spec["owner"] == "adapter"
)
SHARED_CATEGORIES = tuple(
    category for category, spec in _CATEGORY_SPECS.items() if spec["owner"] == "shared"
)
RETRIEVAL_OWNED_CATEGORIES = tuple(
    category for category, spec in _CATEGORY_SPECS.items() if spec["owner"] == "retrieval"
)


def build_expert_evaluation_plan(dataset: dict, *, max_cases: int = 12) -> dict:
    normalized_max_cases = max(int(max_cases or 0), len(EVALUATION_CATEGORIES))
    documents = list(dataset.get("documents") or [])[:normalized_max_cases]
    cases = []
    for index, doc in enumerate(documents):
        category = EVALUATION_CATEGORIES[index % len(EVALUATION_CATEGORIES)]
        title = str(doc.get("title") or "Untitled")
        text = str(doc.get("summary") or doc.get("text") or "")
        expected_terms = _expected_terms(title, text)
        cases.append(
            {
                "id": f"{dataset.get('cluster_id', 'cluster')}-{index + 1}",
                "category": category,
                "owner": _CATEGORY_SPECS[category]["owner"],
                "counts_toward_graduation": _CATEGORY_SPECS[category]["counts_toward_graduation"],
                "source_id": doc.get("source_id"),
                "source_title": title,
                "prompt": prompt_for_category(category, title),
                "expected_terms": expected_terms,
                "markers": list(_CATEGORY_SPECS[category]["markers"]),
                "requires_citation": _CATEGORY_SPECS[category]["requires_citation"],
            }
        )
    return {
        "cluster_id": dataset.get("cluster_id"),
        "dataset_hash": dataset.get("dataset_hash"),
        "case_count": len(cases),
        "categories": list(EVALUATION_CATEGORIES),
        "graduation_categories": list(GRADUATION_CATEGORIES),
        "diagnostic_only_categories": list(DIAGNOSTIC_ONLY_CATEGORIES),
        "cases": cases,
    }


def score_expert_response(case: dict, response_text: str) -> dict:
    response = response_text.lower()
    terms = [str(term).lower() for term in case.get("expected_terms") or []]
    term_hits = sum(1 for term in terms if term and term in response)
    term_score = term_hits / max(1, len(terms))
    citation_score = 1.0 if not case.get("requires_citation") or _has_citation_marker(response_text) else 0.0
    refusal_score = 1.0
    if case.get("category") == "out_of_scope_refusal":
        refusal_score = 1.0 if _has_refusal_marker(response) else 0.0
    marker_score = _marker_score(case, response)
    score = round(((term_score * 55.0) + (citation_score * 15.0) + (marker_score * 20.0) + (refusal_score * 10.0)), 2)
    return {
        "case_id": case.get("id"),
        "category": case.get("category"),
        "owner": case.get("owner"),
        "counts_toward_graduation": bool(case.get("counts_toward_graduation")),
        "score": score,
        "term_hits": term_hits,
        "expected_term_count": len(terms),
        "marker_score": marker_score,
        "citation_present": _has_citation_marker(response_text),
        "refusal_present": _has_refusal_marker(response),
    }


def compare_retrieval_vs_adapter(retrieval_scores: list[float], adapter_scores: list[float]) -> dict:
    retrieval_average = _average(retrieval_scores)
    adapter_average = _average(adapter_scores)
    delta = round(adapter_average - retrieval_average, 2)
    return {
        "retrieval_only_score": retrieval_average,
        "adapter_score": adapter_average,
        "quality_delta": delta,
        "minimum_quality_delta": get_settings().lora_min_quality_delta,
        "passes": delta >= get_settings().lora_min_quality_delta,
    }


def retrieval_case_scores(cases: list[dict]) -> list[dict]:
    return [
        score_expert_response(
            case,
            "According to source "
            + str(case.get("source_title") or "")
            + ", "
            + " ".join(str(term) for term in case.get("expected_terms") or []),
        )
        for case in cases
    ]


def build_adapter_training_evaluation_plan(
    adapter_path: str | Path,
    *,
    cluster_id: str = "cluster",
) -> dict | None:
    adapter_dir = Path(adapter_path)
    validation_path = adapter_dir / "dataset" / "validation.jsonl"
    if not validation_path.exists():
        return None
    rows = []
    for line in validation_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    if not rows:
        return None
    cases = []
    for index, row in enumerate(rows):
        messages = list(row.get("messages") or [])
        prompt = str(((messages[0] if messages else {}) or {}).get("content") or "")
        answer = str(((messages[1] if len(messages) > 1 else {}) or {}).get("content") or "")
        category = str(row.get("category") or "")
        if category not in _CATEGORY_SPECS:
            continue
        title = _title_from_prompt(prompt) or "Untitled"
        cases.append(
            {
                "id": f"{cluster_id}-{index + 1}",
                "category": category,
                "owner": _CATEGORY_SPECS[category]["owner"],
                "counts_toward_graduation": _CATEGORY_SPECS[category]["counts_toward_graduation"],
                "source_id": row.get("source_id"),
                "source_title": title,
                "prompt": prompt,
                "expected_terms": _expected_terms(title, answer),
                "markers": list(_CATEGORY_SPECS[category]["markers"]),
                "requires_citation": _CATEGORY_SPECS[category]["requires_citation"],
            }
        )
    return {
        "cluster_id": cluster_id,
        "dataset_hash": _adapter_dataset_hash(adapter_dir),
        "case_count": len(cases),
        "categories": list(EVALUATION_CATEGORIES),
        "graduation_categories": list(GRADUATION_CATEGORIES),
        "diagnostic_only_categories": list(DIAGNOSTIC_ONLY_CATEGORIES),
        "cases": cases,
    }


def run_live_expert_benchmark(
    dataset: dict,
    *,
    adapter_path: str,
    base_model: str,
    max_new_tokens: int | None = None,
    mode: str = "live_adapter_benchmark",
    evaluation_plan: dict | None = None,
) -> dict:
    from backend.app.core.expert_runtime import run_adapter_runtime_batch

    resolved_plan = evaluation_plan
    if resolved_plan is None:
        case_limit = max(len(EVALUATION_CATEGORIES), len(list(dataset.get("documents") or [])))
        resolved_plan = build_expert_evaluation_plan(dataset, max_cases=case_limit)
    benchmark_prompts = [case["prompt"] for case in resolved_plan["cases"]]
    runtime = run_adapter_runtime_batch(
        adapter_path=adapter_path,
        base_model=base_model,
        prompts=benchmark_prompts,
        max_new_tokens=max_new_tokens,
    )
    if not runtime.get("ok"):
        return {
            "evaluation_plan": resolved_plan,
            "runtime": runtime,
            "retrieval_case_scores": [],
            "adapter_case_scores": [],
            "benchmark_report": {
                "cluster_id": resolved_plan.get("cluster_id"),
                "dataset_hash": resolved_plan.get("dataset_hash"),
                "mode": mode,
                "live_adapter_backed": True,
                "status": "runtime_failed",
                "passes": False,
                "case_count": resolved_plan.get("case_count", 0),
                "scored_case_count": 0,
                "categories": list(EVALUATION_CATEGORIES),
                "graduation_categories": list(GRADUATION_CATEGORIES),
                "diagnostic_only_categories": list(DIAGNOSTIC_ONLY_CATEGORIES),
                "adapter_owned_categories": list(ADAPTER_OWNED_CATEGORIES),
                "shared_categories": list(SHARED_CATEGORIES),
                "retrieval_owned_categories": list(RETRIEVAL_OWNED_CATEGORIES),
                "missing_categories": list(GRADUATION_CATEGORIES),
                "incomplete_categories": [],
                "category_scores": {},
                "overall": compare_retrieval_vs_adapter([], []),
                "graduation_overall": compare_retrieval_vs_adapter([], []),
                "gate_report": {},
            },
        }

    responses = runtime.get("responses") or []
    adapter_case_scores = [
        score_expert_response(case, (responses[index] or {}).get("response_text") or "")
        for index, case in enumerate(resolved_plan["cases"])
    ]
    baseline_case_scores = retrieval_case_scores(resolved_plan["cases"])
    benchmark_report = build_expert_benchmark_report(
        resolved_plan,
        retrieval_case_scores=baseline_case_scores,
        adapter_case_scores=adapter_case_scores,
        mode=mode,
        live_adapter_backed=True,
    )
    return {
        "evaluation_plan": evaluation_plan,
        "runtime": runtime,
        "retrieval_case_scores": baseline_case_scores,
        "adapter_case_scores": adapter_case_scores,
        "benchmark_report": benchmark_report,
    }


def build_expert_benchmark_report(
    evaluation_plan: dict,
    *,
    retrieval_case_scores: list[dict] | None = None,
    adapter_case_scores: list[dict] | None = None,
    mode: str = "live_adapter_benchmark",
    live_adapter_backed: bool = True,
) -> dict:
    cases = list(evaluation_plan.get("cases") or [])
    retrieval_by_case = _scores_by_case_id(retrieval_case_scores or [])
    adapter_by_case = _scores_by_case_id(adapter_case_scores or [])
    category_scores = {}
    for category in EVALUATION_CATEGORIES:
        category_cases = [case for case in cases if case.get("category") == category]
        category_spec = _CATEGORY_SPECS[category]
        retrieval_scores = [
            float(retrieval_by_case[case["id"]]["score"])
            for case in category_cases
            if case.get("id") in retrieval_by_case
        ]
        adapter_scores = [
            float(adapter_by_case[case["id"]]["score"])
            for case in category_cases
            if case.get("id") in adapter_by_case
        ]
        comparison = compare_retrieval_vs_adapter(retrieval_scores, adapter_scores)
        category_complete = bool(
            category_cases
            and len(retrieval_scores) == len(category_cases)
            and len(adapter_scores) == len(category_cases)
        )
        category_passes = bool(category_complete and comparison["passes"])
        category_scores[category] = {
            "owner": category_spec["owner"],
            "counts_toward_graduation": bool(category_spec["counts_toward_graduation"]),
            "case_count": len(category_cases),
            "retrieval_scored_count": len(retrieval_scores),
            "adapter_scored_count": len(adapter_scores),
            "retrieval_only_score": comparison["retrieval_only_score"],
            "adapter_score": comparison["adapter_score"],
            "quality_delta": comparison["quality_delta"],
            "minimum_quality_delta": comparison["minimum_quality_delta"],
            "passes": category_passes,
        }

    all_retrieval_scores = [float(item["score"]) for item in retrieval_by_case.values()]
    all_adapter_scores = [float(item["score"]) for item in adapter_by_case.values()]
    overall = compare_retrieval_vs_adapter(all_retrieval_scores, all_adapter_scores)
    graduation_case_ids = {
        case["id"]
        for case in cases
        if case.get("counts_toward_graduation")
    }
    graduation_retrieval_scores = [
        float(retrieval_by_case[case_id]["score"])
        for case_id in graduation_case_ids
        if case_id in retrieval_by_case
    ]
    graduation_adapter_scores = [
        float(adapter_by_case[case_id]["score"])
        for case_id in graduation_case_ids
        if case_id in adapter_by_case
    ]
    graduation_overall = compare_retrieval_vs_adapter(graduation_retrieval_scores, graduation_adapter_scores)
    gate_report = _graduation_gate_report(category_scores)
    missing_categories = [
        category
        for category, report in category_scores.items()
        if report["counts_toward_graduation"] and report["case_count"] == 0
    ]
    incomplete_categories = [
        category
        for category, report in category_scores.items()
        if report["counts_toward_graduation"]
        and report["case_count"] > 0
        and (
            report["retrieval_scored_count"] < report["case_count"]
            or report["adapter_scored_count"] < report["case_count"]
        )
    ]
    scored_case_count = len({*retrieval_by_case.keys(), *adapter_by_case.keys()})
    passes = bool(
        live_adapter_backed
        and not missing_categories
        and not incomplete_categories
        and bool(gate_report.get("passes"))
    )
    if not live_adapter_backed:
        status = "pending_live_adapter_benchmark"
    elif passes:
        status = "passed"
    else:
        status = "failed"
    return {
        "cluster_id": evaluation_plan.get("cluster_id"),
        "dataset_hash": evaluation_plan.get("dataset_hash"),
        "mode": mode,
        "live_adapter_backed": live_adapter_backed,
        "status": status,
        "passes": passes,
        "case_count": len(cases),
        "scored_case_count": scored_case_count,
        "categories": list(EVALUATION_CATEGORIES),
        "graduation_categories": list(GRADUATION_CATEGORIES),
        "diagnostic_only_categories": list(DIAGNOSTIC_ONLY_CATEGORIES),
        "adapter_owned_categories": list(ADAPTER_OWNED_CATEGORIES),
        "shared_categories": list(SHARED_CATEGORIES),
        "retrieval_owned_categories": list(RETRIEVAL_OWNED_CATEGORIES),
        "missing_categories": missing_categories,
        "incomplete_categories": incomplete_categories,
        "category_scores": category_scores,
        "overall": overall,
        "graduation_overall": graduation_overall,
        "gate_report": gate_report,
    }


def prompt_for_category(category: str, title: str) -> str:
    if category == "style_transfer":
        return f"Explain the main idea of '{title}' in the same practical style as the local notes."
    if category == "terminology_consistency":
        return f"Explain '{title}' using the cluster's preferred terminology and local phrasing."
    if category == "reasoning_pattern":
        return f"Answer about '{title}' using the cluster's usual reasoning pattern: first evidence, then interpretation, then conclusion."
    if category == "summarization":
        return f"Summarize the local source titled '{title}' in three grounded bullets."
    if category == "citation_grounding":
        return f"Answer using only the source '{title}' and cite the source title."
    if category == "contradiction_handling":
        return f"If a new claim conflicts with '{title}', explain what local evidence should be trusted."
    if category == "out_of_scope_refusal":
        return f"Answer a question not covered by '{title}' and state what evidence is missing."
    return f"What are the key facts from the local source titled '{title}'?"


_prompt_for_category = prompt_for_category


def _expected_terms(title: str, text: str) -> list[str]:
    words = []
    for raw in f"{title} {text}".replace("_", " ").replace("-", " ").split():
        word = "".join(char for char in raw.lower() if char.isalnum())
        if len(word) >= 5 and word not in words:
            words.append(word)
        if len(words) >= 5:
            break
    return words


def _adapter_dataset_hash(adapter_dir: Path) -> str:
    for path in (
        adapter_dir / "dataset" / "dataset-manifest.json",
        adapter_dir / "training-config.json",
    ):
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            dataset_hash = str(payload.get("dataset_hash") or "")
            if dataset_hash:
                return dataset_hash
    return ""


def _title_from_prompt(prompt: str) -> str:
    for pattern in (r"'([^']+)'", r'"([^"]+)"'):
        match = re.search(pattern, prompt)
        if match:
            return match.group(1).strip()
    return ""


def _has_citation_marker(text: str) -> bool:
    lowered = text.lower()
    return "[" in text or "source" in lowered or "according to" in lowered


def _has_refusal_marker(lowered_text: str) -> bool:
    return any(marker in lowered_text for marker in ("insufficient", "not enough", "missing", "not covered"))


def _marker_score(case: dict, lowered_response: str) -> float:
    markers = [str(marker).lower() for marker in case.get("markers") or [] if str(marker).strip()]
    if not markers:
        return 1.0
    hits = sum(1 for marker in markers if marker in lowered_response)
    return hits / len(markers)


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(float(value) for value in values) / len(values), 2)


def _scores_by_case_id(scores: list[dict]) -> dict[str, dict]:
    normalized = {}
    for item in scores:
        if not isinstance(item, dict):
            continue
        case_id = str(item.get("case_id") or item.get("id") or "")
        if not case_id:
            continue
        try:
            score = float(item.get("score"))
        except (TypeError, ValueError):
            continue
        normalized[case_id] = {**item, "case_id": case_id, "score": score}
    return normalized


def _graduation_gate_report(category_scores: dict[str, dict]) -> dict:
    settings = get_settings()

    def _group_report(categories: tuple[str, ...], *, min_delta: float | None = None, max_regression: float | None = None) -> dict:
        failing = []
        for category in categories:
            row = dict(category_scores.get(category) or {})
            if not row:
                failing.append(category)
                continue
            delta = float(row.get("quality_delta") or 0.0)
            if min_delta is not None and delta < min_delta:
                failing.append(category)
                continue
            if max_regression is not None and delta < (-1.0 * max_regression):
                failing.append(category)
        return {
            "categories": list(categories),
            "passes": not failing,
            "failing_categories": failing,
        }

    adapter_owned = _group_report(
        ADAPTER_OWNED_CATEGORIES,
        min_delta=float(settings.lora_adapter_owned_min_quality_delta),
    )
    shared = _group_report(
        SHARED_CATEGORIES,
        max_regression=float(settings.lora_shared_max_quality_regression),
    )
    retrieval_owned = _group_report(
        RETRIEVAL_OWNED_CATEGORIES,
        max_regression=float(settings.lora_retrieval_owned_max_quality_regression),
    )
    return {
        "passes": bool(adapter_owned["passes"] and shared["passes"] and retrieval_owned["passes"]),
        "adapter_owned": {
            **adapter_owned,
            "minimum_quality_delta": float(settings.lora_adapter_owned_min_quality_delta),
        },
        "shared": {
            **shared,
            "maximum_quality_regression": float(settings.lora_shared_max_quality_regression),
        },
        "retrieval_owned": {
            **retrieval_owned,
            "maximum_quality_regression": float(settings.lora_retrieval_owned_max_quality_regression),
        },
    }
