from __future__ import annotations

from backend.app.core.config import get_settings


EVALUATION_CATEGORIES = (
    "factual_recall",
    "summarization",
    "citation_grounding",
    "contradiction_handling",
    "style_transfer",
    "out_of_scope_refusal",
)


def build_expert_evaluation_plan(dataset: dict, *, max_cases: int = 12) -> dict:
    documents = list(dataset.get("documents") or [])[:max_cases]
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
                "source_id": doc.get("source_id"),
                "source_title": title,
                "prompt": prompt_for_category(category, title),
                "expected_terms": expected_terms,
                "requires_citation": category in {"factual_recall", "citation_grounding", "summarization"},
            }
        )
    return {
        "cluster_id": dataset.get("cluster_id"),
        "dataset_hash": dataset.get("dataset_hash"),
        "case_count": len(cases),
        "categories": list(EVALUATION_CATEGORIES),
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
    score = round(((term_score * 70.0) + (citation_score * 20.0) + (refusal_score * 10.0)), 2)
    return {
        "case_id": case.get("id"),
        "category": case.get("category"),
        "score": score,
        "term_hits": term_hits,
        "expected_term_count": len(terms),
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
        category_scores[category] = {
            "case_count": len(category_cases),
            "retrieval_scored_count": len(retrieval_scores),
            "adapter_scored_count": len(adapter_scores),
            "retrieval_only_score": comparison["retrieval_only_score"],
            "adapter_score": comparison["adapter_score"],
            "quality_delta": comparison["quality_delta"],
            "minimum_quality_delta": comparison["minimum_quality_delta"],
            "passes": bool(
                category_cases
                and len(retrieval_scores) == len(category_cases)
                and len(adapter_scores) == len(category_cases)
                and comparison["passes"]
            ),
        }

    all_retrieval_scores = [float(item["score"]) for item in retrieval_by_case.values()]
    all_adapter_scores = [float(item["score"]) for item in adapter_by_case.values()]
    overall = compare_retrieval_vs_adapter(all_retrieval_scores, all_adapter_scores)
    missing_categories = [
        category
        for category, report in category_scores.items()
        if report["case_count"] == 0
    ]
    incomplete_categories = [
        category
        for category, report in category_scores.items()
        if report["case_count"] > 0
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
        and overall["passes"]
        and all(report["passes"] for report in category_scores.values())
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
        "missing_categories": missing_categories,
        "incomplete_categories": incomplete_categories,
        "category_scores": category_scores,
        "overall": overall,
    }


def prompt_for_category(category: str, title: str) -> str:
    if category == "summarization":
        return f"Summarize the local source titled '{title}' in three grounded bullets."
    if category == "citation_grounding":
        return f"Answer using only the source '{title}' and cite the source title."
    if category == "contradiction_handling":
        return f"If a new claim conflicts with '{title}', explain what local evidence should be trusted."
    if category == "style_transfer":
        return f"Explain the main idea of '{title}' in the same practical style as the local notes."
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


def _has_citation_marker(text: str) -> bool:
    lowered = text.lower()
    return "[" in text or "source" in lowered or "according to" in lowered


def _has_refusal_marker(lowered_text: str) -> bool:
    return any(marker in lowered_text for marker in ("insufficient", "not enough", "missing", "not covered"))


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
