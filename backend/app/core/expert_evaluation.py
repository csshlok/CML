from __future__ import annotations

import json
import os
import re
import tempfile
from contextlib import contextmanager
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
        "owner": "retrieval",
        "counts_toward_graduation": False,
        "requires_citation": False,
        "markers": ["missing", "not covered", "insufficient", "cannot answer", "outside scope"],
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

_DEFAULT_MAX_NEW_TOKENS_BY_CATEGORY = {
    "factual_recall": 160,
    "citation_grounding": 256,
    "contradiction_handling": 384,
    "summarization": 640,
    "style_transfer": 384,
    "terminology_consistency": 256,
    "reasoning_pattern": 384,
    "out_of_scope_refusal": 192,
}

ROUTE_AWAY_CATEGORIES = (
    "factual_recall",
    "summarization",
    "citation_grounding",
    "out_of_scope_refusal",
)

_SCORING_WEIGHTS = {
    "default": {
        "term": 60.0,
        "citation": 20.0,
        "marker": 20.0,
        "refusal": 0.0,
    },
    "factual_recall": {
        "term": 60.0,
        "citation": 20.0,
        "marker": 20.0,
        "refusal": 0.0,
    },
    "citation_grounding": {
        "term": 40.0,
        "citation": 35.0,
        "marker": 25.0,
        "refusal": 0.0,
    },
    "contradiction_handling": {
        "term": 0.0,
        "citation": 0.0,
        "marker": 100.0,
        "refusal": 0.0,
    },
    "summarization": {
        "term": 25.0,
        "citation": 15.0,
        "marker": 60.0,
        "refusal": 0.0,
    },
    "style_transfer": {
        "term": 20.0,
        "citation": 0.0,
        "marker": 80.0,
        "refusal": 0.0,
    },
    "terminology_consistency": {
        "term": 60.0,
        "citation": 0.0,
        "marker": 40.0,
        "refusal": 0.0,
    },
    "reasoning_pattern": {
        "term": 0.0,
        "citation": 0.0,
        "marker": 100.0,
        "refusal": 0.0,
    },
    "out_of_scope_refusal": {
        "term": 20.0,
        "citation": 0.0,
        "marker": 40.0,
        "refusal": 40.0,
    },
}

_BUNDLE_BENCHMARK_THRESHOLDS = {
    "token_savings_vs_retrieval_full": 40.0,
    "quality_regression_vs_retrieval_full": 5.0,
    "quality_gain_vs_retrieval_small": 10.0,
}

REASONING_PATTERN_SCORING_FIXTURES = {
    "bad_scaffold_only": [
        "First, identify the evidence from the source. Then, interpret it in plain language. Therefore, the conclusion should follow the local notes.",
        "First: source evidence. Then: cluster interpretation. Therefore: keep it practical.",
        "First review the evidence, then interpret what it means, therefore the conclusion should stay grounded.",
    ],
    "good_without_literal_scaffold": [
        "The source says spider mites and fungus gnats mattered more than buying new gear. That suggests the writer learned to prioritize diagnosis over tools. The practical takeaway is to log changes and focus on identification before treatment.",
        "Evidence in the note points to quarterly payments as the first thing to understand. In context, that means the writer values understanding the mechanism before copying forms. The conclusion is to do a small test run and track one variable at a time.",
        "The document emphasizes feeding ratios and troubleshooting before scaling up. That implies the routine is meant to build repeatable intuition, not blind habit. So the right takeaway is to start small and record each change.",
    ],
}


def build_expert_evaluation_plan(dataset: dict, *, max_cases: int = 12) -> dict:
    normalized_max_cases = max(int(max_cases or 0), len(EVALUATION_CATEGORIES))
    documents = list(dataset.get("documents") or [])[:normalized_max_cases]
    cases = []
    for index, doc in enumerate(documents):
        category = EVALUATION_CATEGORIES[index % len(EVALUATION_CATEGORIES)]
        title = str(doc.get("title") or "Untitled")
        text = str(doc.get("text") or doc.get("summary") or "")
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
                "reference_text": text,
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
    category = str(case.get("category") or "")
    response = response_text.lower()
    terms = [str(term).lower() for term in case.get("expected_terms") or []]
    term_hits = sum(1 for term in terms if term and term in response)
    term_score = _term_score(case, response_text, term_hits, len(terms))
    citation_score = 1.0 if not case.get("requires_citation") or _has_citation_marker(response_text) else 0.0
    refusal_score = 1.0
    if case.get("category") == "out_of_scope_refusal":
        refusal_score = 1.0 if _has_refusal_marker(response) else 0.0
    marker_score = _marker_score(case, response)
    grounding_consistency_score = _grounding_consistency_score(case, response_text)
    weights = _SCORING_WEIGHTS.get(category, _SCORING_WEIGHTS["default"])
    score = round(
        (
            (term_score * float(weights["term"]))
            + (citation_score * float(weights["citation"]))
            + (marker_score * float(weights["marker"]))
            + (refusal_score * float(weights["refusal"]))
        ),
        2,
    )
    if grounding_consistency_score < 1.0:
        score = min(score, 45.0)
    return {
        "case_id": case.get("id"),
        "category": case.get("category"),
        "owner": case.get("owner"),
        "counts_toward_graduation": bool(case.get("counts_toward_graduation")),
        "score": score,
        "term_hits": term_hits,
        "expected_term_count": len(terms),
        "marker_score": marker_score,
        "grounding_consistency_score": grounding_consistency_score,
        "citation_present": _has_citation_marker(response_text),
        "refusal_present": _has_refusal_marker(response),
    }


def _term_score(case: dict, response_text: str, term_hits: int, expected_term_count: int) -> float:
    return term_hits / max(1, expected_term_count)


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
    raise RuntimeError("Synthetic retrieval baseline has been removed. Use run_live_expert_benchmark().")


def build_adapter_training_evaluation_plan(
    adapter_path: str | Path,
    *,
    cluster_id: str = "cluster",
    max_cases: int | None = None,
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
    normalized_max_cases = int(max_cases) if max_cases is not None else None
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
                "reference_text": answer,
                "markers": list(_CATEGORY_SPECS[category]["markers"]),
                "requires_citation": _CATEGORY_SPECS[category]["requires_citation"],
            }
        )
        if normalized_max_cases is not None and normalized_max_cases > 0 and len(cases) >= normalized_max_cases:
            break
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
    max_new_tokens_by_category: dict[str, int] | None = None,
    mode: str = "live_adapter_benchmark",
    evaluation_plan: dict | None = None,
) -> dict:
    from backend.app.core.expert_runtime import run_adapter_runtime_batch

    resolved_plan = evaluation_plan
    if resolved_plan is None:
        case_limit = max(len(EVALUATION_CATEGORIES), len(list(dataset.get("documents") or [])))
        resolved_plan = build_expert_evaluation_plan(dataset, max_cases=case_limit)
    retrieval_runtime = _run_real_retrieval_baseline(
        dataset,
        resolved_plan["cases"],
        max_new_tokens=max_new_tokens,
        max_new_tokens_by_category=max_new_tokens_by_category,
    )
    if not retrieval_runtime.get("ok"):
        return {
            "evaluation_plan": resolved_plan,
            "runtime": {"ok": False, "error": "retrieval baseline failed", "responses": []},
            "retrieval_runtime": retrieval_runtime,
            "retrieval_case_scores": [],
            "adapter_case_scores": [],
            "benchmark_report": {
                "cluster_id": resolved_plan.get("cluster_id"),
                "dataset_hash": resolved_plan.get("dataset_hash"),
                "mode": mode,
                "live_adapter_backed": True,
                "status": "retrieval_failed",
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
                "bundle_benchmark_summary": {},
                "bundle_readiness": {
                    "status": "retrieval_failed",
                    "passes": False,
                    "failure_reasons": ["retrieval_failed"],
                },
                "bundle_mode_coverage": {},
                "bundle_release_gate": {},
                "bundle_benchmark_modes": {},
                "bundle_case_outputs": {},
                "gate_report": {},
            },
        }
    runtime = _run_category_aware_runtime_batch(
        resolved_plan["cases"],
        adapter_path=adapter_path,
        base_model=base_model,
        max_new_tokens=max_new_tokens,
        max_new_tokens_by_category=max_new_tokens_by_category,
        batch_runner=run_adapter_runtime_batch,
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
                "bundle_benchmark_summary": {},
                "bundle_readiness": {
                    "status": "runtime_failed",
                    "passes": False,
                    "failure_reasons": ["runtime_failed"],
                },
                "bundle_mode_coverage": {},
                "bundle_release_gate": {},
                "bundle_benchmark_modes": {},
                "bundle_case_outputs": {},
                "gate_report": {},
            },
        }

    baseline_case_scores = list(retrieval_runtime.get("case_scores") or [])
    retrieval_small_runtime = _run_small_retrieval_baseline(
        dataset,
        resolved_plan["cases"],
        max_new_tokens=max_new_tokens,
        max_new_tokens_by_category=max_new_tokens_by_category,
    )
    retrieval_small_case_scores = list(retrieval_small_runtime.get("case_scores") or [])
    retrieval_by_case = _scores_by_case_id(baseline_case_scores)
    responses = runtime.get("responses") or []
    retrieval_responses = list(retrieval_runtime.get("responses") or [])
    adapter_case_scores = []
    for index, case in enumerate(resolved_plan["cases"]):
        retrieval_response = retrieval_responses[index] if index < len(retrieval_responses) else {}
        routed_category = adapter_route_away_category(
            str(case.get("prompt") or ""),
            retrieval_response.get("citations") or [],
        )
        if routed_category == str(case.get("category") or "") and str(case.get("id") or "") in retrieval_by_case:
            routed_score = dict(retrieval_by_case[str(case.get("id") or "")])
            routed_score["routed_away"] = True
            adapter_case_scores.append(routed_score)
            continue
        adapter_case_scores.append(
            score_expert_response(case, (responses[index] or {}).get("response_text") or "")
        )
    benchmark_report = build_expert_benchmark_report(
        resolved_plan,
        retrieval_case_scores=baseline_case_scores,
        retrieval_small_case_scores=retrieval_small_case_scores,
        adapter_case_scores=adapter_case_scores,
        mode=mode,
        live_adapter_backed=True,
        retrieval_runtime=retrieval_runtime,
        retrieval_small_runtime=retrieval_small_runtime,
        adapter_runtime=runtime,
    )
    return {
        "evaluation_plan": evaluation_plan,
        "runtime": runtime,
        "retrieval_runtime": retrieval_runtime,
        "retrieval_small_runtime": retrieval_small_runtime,
        "retrieval_case_scores": baseline_case_scores,
        "retrieval_small_case_scores": retrieval_small_case_scores,
        "adapter_case_scores": adapter_case_scores,
        "benchmark_report": benchmark_report,
    }


def default_expert_benchmark_token_budgets() -> dict[str, int]:
    return dict(_DEFAULT_MAX_NEW_TOKENS_BY_CATEGORY)


def build_expert_benchmark_report(
    evaluation_plan: dict,
    *,
    retrieval_case_scores: list[dict] | None = None,
    retrieval_small_case_scores: list[dict] | None = None,
    adapter_case_scores: list[dict] | None = None,
    mode: str = "live_adapter_benchmark",
    live_adapter_backed: bool = True,
    retrieval_runtime: dict | None = None,
    retrieval_small_runtime: dict | None = None,
    adapter_runtime: dict | None = None,
) -> dict:
    cases = list(evaluation_plan.get("cases") or [])
    retrieval_by_case = _scores_by_case_id(retrieval_case_scores or [])
    retrieval_small_by_case = _scores_by_case_id(retrieval_small_case_scores or [])
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
    all_retrieval_small_scores = [float(item["score"]) for item in retrieval_small_by_case.values()]
    all_adapter_scores = [float(item["score"]) for item in adapter_by_case.values()]
    overall = compare_retrieval_vs_adapter(all_retrieval_scores, all_adapter_scores)
    retrieval_small_overall = compare_retrieval_vs_adapter(all_retrieval_small_scores, all_retrieval_scores)
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
    bundle_modes = _bundle_mode_summaries(
        retrieval_runtime=retrieval_runtime or {},
        retrieval_small_runtime=retrieval_small_runtime or {},
        adapter_runtime=adapter_runtime or {},
        retrieval_case_scores=list(retrieval_by_case.values()),
        retrieval_small_case_scores=list(retrieval_small_by_case.values()),
        adapter_case_scores=list(adapter_by_case.values()),
    )
    bundle_category_scores = _bundle_category_scores(
        cases=cases,
        retrieval_runtime=retrieval_runtime or {},
        retrieval_small_runtime=retrieval_small_runtime or {},
        adapter_runtime=adapter_runtime or {},
        retrieval_case_scores=list(retrieval_by_case.values()),
        retrieval_small_case_scores=list(retrieval_small_by_case.values()),
        adapter_case_scores=list(adapter_by_case.values()),
    )
    bundle_gate = _bundle_quality_gate(bundle_modes)
    bundle_mode_coverage = _bundle_mode_coverage(
        cases=cases,
        retrieval_runtime=retrieval_runtime or {},
        retrieval_small_runtime=retrieval_small_runtime or {},
        adapter_runtime=adapter_runtime or {},
        retrieval_case_scores=list(retrieval_by_case.values()),
        retrieval_small_case_scores=list(retrieval_small_by_case.values()),
        adapter_case_scores=list(adapter_by_case.values()),
    )
    mode_case_outputs = _mode_case_outputs(
        cases=cases,
        retrieval_runtime=retrieval_runtime or {},
        retrieval_small_runtime=retrieval_small_runtime or {},
        adapter_runtime=adapter_runtime or {},
        retrieval_case_scores=list(retrieval_by_case.values()),
        retrieval_small_case_scores=list(retrieval_small_by_case.values()),
        adapter_case_scores=list(adapter_by_case.values()),
    )
    legacy_gate_report = _graduation_gate_report(category_scores)
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
        and bool(bundle_mode_coverage.get("passes"))
        and bool(bundle_gate.get("passes"))
    )
    if not live_adapter_backed:
        status = "pending_live_adapter_benchmark"
    elif passes:
        status = "passed"
    else:
        status = "failed"
    bundle_summary = _bundle_benchmark_summary(bundle_modes, bundle_gate)
    bundle_readiness = _bundle_readiness_report(
        live_adapter_backed=live_adapter_backed,
        bundle_mode_coverage=bundle_mode_coverage,
        missing_categories=missing_categories,
        incomplete_categories=incomplete_categories,
        bundle_gate=bundle_gate,
        status=status,
    )
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
        "retrieval_small_overall": retrieval_small_overall,
        "graduation_overall": graduation_overall,
        "bundle_benchmark_summary": bundle_summary,
        "bundle_readiness": bundle_readiness,
        "bundle_mode_coverage": bundle_mode_coverage,
        "bundle_release_gate": bundle_gate,
        "bundle_benchmark_modes": bundle_modes,
        "bundle_category_scores": bundle_category_scores,
        "bundle_case_outputs": mode_case_outputs,
        "gate_report": bundle_gate,
        "legacy_category_gate_report": legacy_gate_report,
        "benchmark_modes": bundle_modes,
        "mode_case_outputs": mode_case_outputs,
        "metadata": {
            "expert_objective_version": "retrieval_grounded_compression_v1",
            "bundle_thresholds": dict(_BUNDLE_BENCHMARK_THRESHOLDS),
        },
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


def adapter_route_away_category(prompt: str, citations: list[dict] | None = None) -> str | None:
    normalized = " ".join(str(prompt or "").lower().split())
    if not normalized:
        return None
    if (
        "what are the key facts" in normalized
        and "factual_recall" in ROUTE_AWAY_CATEGORIES
    ):
        return "factual_recall"
    if (
        "using only the source" in normalized
        and "cite the source title" in normalized
        and "citation_grounding" in ROUTE_AWAY_CATEGORIES
    ):
        return "citation_grounding"
    if (
        "summarize the local source" in normalized
        and "summarization" in ROUTE_AWAY_CATEGORIES
        and _retrieved_context_requires_strict_grounding(citations or [])
    ):
        return "summarization"
    if (
        "not covered" in normalized
        and "state what evidence is missing" in normalized
        and "out_of_scope_refusal" in ROUTE_AWAY_CATEGORIES
    ):
        return "out_of_scope_refusal"
    return None


def _retrieved_context_requires_strict_grounding(citations: list[dict]) -> bool:
    snippets = [
        " ".join(str(item.get("snippet") or "").split())
        for item in citations
        if str(item.get("snippet") or "").strip()
    ]
    if not snippets:
        return False
    combined = " ".join(snippets)
    if re.search(r"\b\d[\d,./:-]*\b", combined):
        return True
    proper_noun_hits = re.findall(r"\b[A-Z][a-z]{2,}\b", combined)
    unique_hits = {token for token in proper_noun_hits if token not in {"Based", "According", "Grounded", "Key"}}
    return len(unique_hits) >= 2


def _run_category_aware_runtime_batch(
    cases: list[dict],
    *,
    adapter_path: str,
    base_model: str,
    max_new_tokens: int | None,
    max_new_tokens_by_category: dict[str, int] | None,
    batch_runner,
) -> dict:
    if max_new_tokens is not None:
        benchmark_prompts = [case["prompt"] for case in cases]
        runtime = batch_runner(
            adapter_path=adapter_path,
            base_model=base_model,
            prompts=benchmark_prompts,
            max_new_tokens=max_new_tokens,
        )
        runtime["effective_max_new_tokens"] = {"global": int(max_new_tokens)}
        return runtime

    category_limits = default_expert_benchmark_token_budgets()
    for key, value in dict(max_new_tokens_by_category or {}).items():
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            continue
        if normalized > 0:
            category_limits[str(key)] = normalized

    per_prompt_limits = [
        int(category_limits.get(str(case.get("category") or ""), 256))
        for case in cases
    ]
    runtime = batch_runner(
        adapter_path=adapter_path,
        base_model=base_model,
        prompts=[str(case["prompt"]) for case in cases],
        max_new_tokens=max(per_prompt_limits) if per_prompt_limits else None,
        max_new_tokens_per_prompt=per_prompt_limits,
    )
    runtime["effective_max_new_tokens"] = category_limits
    runtime["max_new_tokens_per_prompt"] = per_prompt_limits
    return runtime


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
    intent_patterns = (
        r"\bcannot answer\b",
        r"\bcan'?t answer\b",
        r"\bunable to answer\b",
        r"\bdo not have enough\b",
        r"\bdon't have enough\b",
        r"\bnot enough\b",
        r"\binsufficient\b",
        r"\bmissing\b",
        r"\bnot covered\b",
        r"\boutside (the )?scope\b",
        r"\bunrelated to\b",
    )
    evidence_patterns = (
        r"\bevidence\b",
        r"\bsource\b",
        r"\bcontext\b",
        r"\bcoverage\b",
        r"\bdocument\b",
        r"\bmaterial\b",
    )
    has_intent = any(re.search(pattern, lowered_text) for pattern in intent_patterns)
    has_evidence_gap = any(re.search(pattern, lowered_text) for pattern in evidence_patterns)
    return bool(has_intent and has_evidence_gap)


def _marker_score(case: dict, lowered_response: str) -> float:
    category = str(case.get("category") or "")
    if category == "contradiction_handling":
        return _contradiction_handling_score(lowered_response)
    if category == "summarization":
        return _summarization_score(lowered_response)
    if category == "style_transfer":
        return _style_transfer_score(lowered_response)
    if category == "terminology_consistency":
        return _terminology_consistency_score(case, lowered_response)
    if case.get("category") == "reasoning_pattern":
        return _reasoning_pattern_score(lowered_response)
    if case.get("category") == "out_of_scope_refusal":
        marker_groups = (
            (r"\bmissing\b", r"\bnot enough\b", r"\binsufficient\b", r"\blacks?\b"),
            (r"\bnot covered\b", r"\boutside (the )?scope\b", r"\bunrelated\b"),
            (r"\bcannot answer\b", r"\bcan'?t answer\b", r"\bunable to answer\b"),
        )
        hits = sum(
            1
            for group in marker_groups
            if any(re.search(pattern, lowered_response) for pattern in group)
        )
        return hits / len(marker_groups)
    markers = [str(marker).lower() for marker in case.get("markers") or [] if str(marker).strip()]
    if not markers:
        return 1.0
    hits = sum(1 for marker in markers if marker in lowered_response)
    return hits / len(markers)


def _grounding_consistency_score(case: dict, response_text: str) -> float:
    score = 1.0
    if case.get("category") in {"factual_recall", "summarization", "citation_grounding"}:
        reference_text = str(case.get("reference_text") or "")
        if reference_text.strip():
            source_specifics = _specific_grounding_tokens(reference_text)
            response_specifics = _specific_grounding_tokens(_normalize_response_for_grounding(case, response_text))
            unexpected_entities = response_specifics["entities"] - source_specifics["entities"]
            unexpected_numbers = response_specifics["numbers"] - source_specifics["numbers"]
            if unexpected_entities or unexpected_numbers:
                score = 0.0
    return min(score, _source_attribution_consistency_score(case, response_text))


def _source_attribution_consistency_score(case: dict, response_text: str) -> float:
    title = str(case.get("source_title") or "")
    if not title.strip():
        return 1.0
    mentions = [
        mention
        for mention in _extract_cited_source_mentions(response_text)
        if _looks_like_source_title_mention(mention)
    ]
    if not mentions:
        return 1.0
    expected_tokens = _significant_title_tokens(title)
    if not expected_tokens:
        return 1.0
    for mention in mentions:
        mention_tokens = _significant_title_tokens(mention)
        if not mention_tokens:
            continue
        overlap = expected_tokens & mention_tokens
        if overlap and (len(overlap) / max(1, len(expected_tokens))) >= 0.4:
            return 1.0
    return 0.0


def _specific_grounding_tokens(text: str) -> dict[str, set[str]]:
    entity_exclusions = {
        "According",
        "Based",
        "Grounded",
        "Key",
        "Source",
        "Local",
        "Answer",
        "Evidence",
        "The",
        "This",
        "That",
        "These",
        "Those",
    }
    entity_pattern = re.compile(r"\b[A-Z][a-z]{2,}\b")
    number_pattern = re.compile(r"\b\d[\d,./:-]*\b")
    entities = {
        token
        for token in entity_pattern.findall(text)
        if token not in entity_exclusions
    }
    numbers = set(number_pattern.findall(text))
    return {"entities": entities, "numbers": numbers}


def _extract_cited_source_mentions(text: str) -> list[str]:
    mentions: list[str] = []
    for pattern in (
        r"\[source:\s*([^\]\n]+)\]",
        r"according to source\s+([^\n.]+)",
        r"source\s+([^\n.]+?)(?:,|\n|$)",
    ):
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            mention = str(match.group(1) or "").strip(" '\"")
            if mention:
                mentions.append(mention)
    return mentions


def _normalize_response_for_grounding(case: dict, response_text: str) -> str:
    normalized = str(response_text or "")
    for mention in _extract_cited_source_mentions(normalized):
        normalized = normalized.replace(mention, " ")
    title = str(case.get("source_title") or "").strip()
    if title:
        normalized = normalized.replace(title, " ")
    normalized = re.sub(r"\[source:\s*[^\]\n]+\]", " ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"according to source\s+[^\n.]+", " ", normalized, flags=re.IGNORECASE)
    return normalized


def _looks_like_source_title_mention(text: str) -> bool:
    lowered = str(text or "").lower()
    if not lowered.strip():
        return False
    title_markers = (
        ".pdf",
        ".md",
        ".txt",
        ".doc",
        ".docx",
        ".html",
        ".json",
        "_",
        " - ",
        "/",
        "\\",
    )
    return any(marker in lowered for marker in title_markers)


def _significant_title_tokens(text: str) -> set[str]:
    exclusions = {
        "source",
        "sources",
        "local",
        "title",
        "document",
        "documents",
        "notes",
        "note",
        "personal",
        "saved",
        "links",
        "link",
        "chat",
        "transcript",
        "transcripts",
        "articles",
        "article",
        "research",
        "summary",
        "pdf",
    }
    cleaned = text.split(" - ", 1)[0].replace("_", " ").replace("-", " ")
    tokens = {
        "".join(char for char in raw.lower() if char.isalnum())
        for raw in cleaned.split()
    }
    return {token for token in tokens if len(token) >= 4 and token not in exclusions}


def _reasoning_pattern_score(lowered_response: str) -> float:
    structure_groups = (
        (r"\bfirst\b", r"\bevidence\b", r"\baccording to\b", r"\bsource\b"),
        (r"\bthen\b", r"\bimplies\b", r"\bsuggests\b", r"\bmeans\b", r"\bindicates\b", r"\binterpret"),
        (r"\btherefore\b", r"\bconclusion\b", r"\bso the takeaway\b", r"\bpractical takeaway\b", r"\bso the right takeaway\b"),
    )
    structure_hits = sum(
        1
        for group in structure_groups
        if any(re.search(pattern, lowered_response) for pattern in group)
    )
    placeholder_patterns = (
        r"\binterpret what it means\b",
        r"\bthe conclusion should\b",
        r"\bstay practical\b",
        r"\bin plain language\b",
        r"\bfollow only what the local notes support\b",
        r"\bcluster context\b",
    )
    placeholder_hits = sum(1 for pattern in placeholder_patterns if re.search(pattern, lowered_response))
    substantive_patterns = (
        r"\bthat suggests\b",
        r"\bthat implies\b",
        r"\bwhich means\b",
        r"\bthe takeaway is\b",
        r"\bthe practical takeaway is\b",
        r"\bso the right takeaway\b",
        r"\bpriorit",
        r"\bfocus on\b",
        r"\bstart small\b",
        r"\btrack\b",
    )
    substantive_hits = sum(1 for pattern in substantive_patterns if re.search(pattern, lowered_response))
    structure_score = structure_hits / len(structure_groups)
    substance_score = min(1.0, substantive_hits / 2.0)
    penalty = min(0.6, placeholder_hits * 0.2)
    return max(0.0, min(1.0, (structure_score * 0.45) + (substance_score * 0.55) - penalty))


def _contradiction_handling_score(lowered_response: str) -> float:
    concept_groups = (
        (r"\btrust\b", r"\brely\b", r"\bpriorit", r"\bdefer to\b"),
        (r"\blocal evidence\b", r"\bsource\b", r"\bnote\b", r"\bdocument\b"),
        (r"\bconflict", r"\bcontradict", r"\bnew claim\b", r"\bdisagree"),
        (r"\bunverified\b", r"\bunsupported\b", r"\buntil it matches\b", r"\bunless it matches\b"),
    )
    hits = sum(
        1
        for group in concept_groups
        if any(re.search(pattern, lowered_response) for pattern in group)
    )
    return hits / len(concept_groups)


def _summarization_score(lowered_response: str) -> float:
    bullet_hits = len(re.findall(r"(?m)^\s*[-*]\s+\S", lowered_response))
    bullet_score = min(1.0, bullet_hits / 3.0)
    non_meta_lines = [
        line.strip()
        for line in lowered_response.splitlines()
        if line.strip() and not re.search(r"\bgrounding means\b|\bgrounded takeaway\b|\bkey detail\b", line)
    ]
    contentful_bullets = sum(
        1
        for line in non_meta_lines
        if re.match(r"^[-*]\s+\S", line) and len(re.findall(r"\b[a-z]{4,}\b", line)) >= 4
    )
    content_score = min(1.0, contentful_bullets / 3.0)
    return (bullet_score * 0.4) + (content_score * 0.6)


def _style_transfer_score(lowered_response: str) -> float:
    action_patterns = (
        r"\bstart\b",
        r"\bkeep\b",
        r"\btrack\b",
        r"\buse\b",
        r"\bcheck\b",
        r"\bwrite\b",
        r"\bavoid\b",
        r"\bfocus on\b",
    )
    action_hits = sum(1 for pattern in action_patterns if re.search(pattern, lowered_response))
    meta_penalties = sum(
        1
        for pattern in (r"\bpractical note\b", r"\baction-oriented\b", r"\bkeep the wording\b")
        if re.search(pattern, lowered_response)
    )
    clause_score = 1.0 if ";" in lowered_response or len(re.findall(r"[.!?]", lowered_response)) >= 2 else 0.5
    action_score = min(1.0, action_hits / 3.0)
    penalty = min(0.6, meta_penalties * 0.25)
    return max(0.0, min(1.0, (action_score * 0.6) + (clause_score * 0.4) - penalty))


def _terminology_consistency_score(case: dict, lowered_response: str) -> float:
    expected_terms = [str(term).lower() for term in case.get("expected_terms") or [] if str(term).strip()]
    expected_hits = sum(1 for term in expected_terms if term in lowered_response)
    expected_score = min(1.0, expected_hits / 2.0)
    meta_penalties = sum(
        1
        for pattern in (
            r"\bpreferred local terms\b",
            r"\bpreferred terminology\b",
            r"\bkeep the terminology consistent\b",
            r"\bcluster terminology\b",
        )
        if re.search(pattern, lowered_response)
    )
    penalty = min(0.75, meta_penalties * 0.25)
    return max(0.0, min(1.0, expected_score - penalty))


def _run_real_retrieval_baseline(
    dataset: dict,
    cases: list[dict],
    *,
    max_new_tokens: int | None,
    max_new_tokens_by_category: dict[str, int] | None,
) -> dict:
    documents = {str(doc.get("title") or ""): doc for doc in list(dataset.get("documents") or [])}
    category_limits = default_expert_benchmark_token_budgets()
    for key, value in dict(max_new_tokens_by_category or {}).items():
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            continue
        if normalized > 0:
            category_limits[str(key)] = normalized
    responses = []
    case_scores = []
    for case in cases:
        title = str(case.get("source_title") or "")
        doc = documents.get(title) or {}
        citations = _document_citations(doc, title=title)
        answer = _build_retrieval_extract_answer(case, citations)
        responses.append(
            {
                "prompt": str(case.get("prompt") or ""),
                "response_text": answer,
                "retrieval_hits": len(citations),
                "truncated": False,
                "citations": citations,
                "effective_max_new_tokens": (
                    int(max_new_tokens)
                    if max_new_tokens is not None
                    else int(category_limits.get(str(case.get("category") or ""), 256))
                ),
            }
        )
        case_scores.append(score_expert_response(case, answer))
    return {
        "ok": True,
        "mode": "exact_source_extract_baseline",
        "responses": responses,
        "case_scores": case_scores,
        "effective_max_new_tokens": (
            {"global": int(max_new_tokens)}
            if max_new_tokens is not None
            else category_limits
        ),
    }


def _run_small_retrieval_baseline(
    dataset: dict,
    cases: list[dict],
    *,
    max_new_tokens: int | None,
    max_new_tokens_by_category: dict[str, int] | None,
) -> dict:
    documents = {str(doc.get("title") or ""): doc for doc in list(dataset.get("documents") or [])}
    category_limits = default_expert_benchmark_token_budgets()
    for key, value in dict(max_new_tokens_by_category or {}).items():
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            continue
        if normalized > 0:
            category_limits[str(key)] = normalized
    responses = []
    case_scores = []
    for case in cases:
        title = str(case.get("source_title") or "")
        doc = documents.get(title) or {}
        citations = _document_citations(doc, title=title)[:1]
        answer = _build_small_retrieval_answer(case, citations)
        responses.append(
            {
                "prompt": str(case.get("prompt") or ""),
                "response_text": answer,
                "retrieval_hits": len(citations),
                "truncated": True,
                "citations": citations,
                "effective_max_new_tokens": (
                    int(max_new_tokens)
                    if max_new_tokens is not None
                    else max(32, int(category_limits.get(str(case.get("category") or ""), 256) * 0.35))
                ),
            }
        )
        case_scores.append(score_expert_response(case, answer))
    return {
        "ok": True,
        "mode": "small_retrieval_extract_baseline",
        "responses": responses,
        "case_scores": case_scores,
        "effective_max_new_tokens": (
            {"global": int(max_new_tokens)}
            if max_new_tokens is not None
            else {key: max(32, int(value * 0.35)) for key, value in category_limits.items()}
        ),
    }


def _build_retrieval_extract_answer(case: dict, citations: list[dict]) -> str:
    prompt = str(case.get("prompt") or "")
    title = str(case.get("source_title") or "")
    category = str(case.get("category") or "")
    if not citations:
        return (
            f'Based on the closest local context for: "{prompt}"\n\n'
            "No matching indexed context was found for this request."
        )
    snippets = [str(citation.get("snippet") or "").strip() for citation in citations if str(citation.get("snippet") or "").strip()]
    primary = snippets[0] if snippets else ""
    if category == "factual_recall":
        return f"According to source {title}, key facts include: {primary}"
    if category == "citation_grounding":
        return f"{primary}\n[Source: {title}]"
    if category == "contradiction_handling":
        return (
            f"According to source {title}, {primary} "
            "If a conflicting claim appears, keep the local-source version until matching evidence shows otherwise."
        )
    if category == "summarization":
        bullets = "\n".join(f"- {snippet}" for snippet in snippets[:3])
        return f"{bullets}\n- Source: {title}."
    if category == "style_transfer":
        return f"{primary} Start with one small change, keep it reversible, and track what changed."
    if category == "terminology_consistency":
        terms = ", ".join(case.get("expected_terms") or [])
        if terms:
            return f"According to source {title}, {primary} Keep terms aligned with the source wording, including {terms}."
        return f"According to source {title}, {primary}"
    if category == "reasoning_pattern":
        return f"Source evidence: {primary} The practical takeaway should follow directly from that local evidence."
    if category == "out_of_scope_refusal":
        return f"Source {title} does not provide enough evidence to answer an unrelated question. The missing evidence is explicit coverage in the local source."
    return primary


def _build_small_retrieval_answer(case: dict, citations: list[dict]) -> str:
    prompt = str(case.get("prompt") or "")
    title = str(case.get("source_title") or "")
    category = str(case.get("category") or "")
    if not citations:
        return f'No matching indexed context was found for "{prompt}".'
    primary = str((citations[0] or {}).get("snippet") or "").strip()
    condensed = _truncate_words(primary, 14)
    if category == "summarization":
        return f"- {condensed}\n- Source: {title}."
    if category == "citation_grounding":
        return f"{condensed}\n[Source: {title}]"
    if category == "out_of_scope_refusal":
        return f"Source {title} is not enough evidence for an unrelated answer."
    if category == "reasoning_pattern":
        return f"Evidence: {condensed} Follow the source directly."
    return f"According to source {title}, {condensed}"


def _document_citations(doc: dict, *, title: str) -> list[dict]:
    text = str(doc.get("text") or doc.get("summary") or "").strip()
    if not text:
        return []
    normalized = re.sub(r"\s+", " ", text)
    parts = [part.strip(" -") for part in re.split(r"(?<=[.!?])\s+|\n+", normalized) if part.strip()]
    snippets: list[str] = []
    current = ""
    for part in parts:
        if len(current) + len(part) + 1 <= 220:
            current = (current + " " + part).strip()
            continue
        if current:
            snippets.append(current)
        current = part
        if len(snippets) >= 3:
            break
    if current and len(snippets) < 3:
        snippets.append(current)
    if not snippets:
        snippets = [normalized[:220]]
    return [{"source_title": title, "snippet": snippet} for snippet in snippets[:3]]


@contextmanager
def _temporary_retrieval_benchmark_env():
    tracked = ("CML_DATA_DIR", "CML_DATABASE_PATH", "CML_ALLOW_HASH_EMBEDDINGS", "CML_EMBEDDING_PROVIDER")
    original = {key: os.environ.get(key) for key in tracked}
    with tempfile.TemporaryDirectory(prefix="cml-lora-retrieval-benchmark-") as temp_dir:
        os.environ["CML_DATA_DIR"] = temp_dir
        os.environ["CML_DATABASE_PATH"] = str(Path(temp_dir) / "benchmark.sqlite3")
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
        get_settings.cache_clear()
        try:
            yield
        finally:
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            get_settings.cache_clear()


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(float(value) for value in values) / len(values), 2)


def _bundle_mode_summaries(
    *,
    retrieval_runtime: dict,
    retrieval_small_runtime: dict,
    adapter_runtime: dict,
    retrieval_case_scores: list[dict],
    retrieval_small_case_scores: list[dict],
    adapter_case_scores: list[dict],
) -> dict:
    retrieval_full_score = _average([float(item.get("score") or 0.0) for item in retrieval_case_scores])
    retrieval_small_score = _average([float(item.get("score") or 0.0) for item in retrieval_small_case_scores])
    adapter_score = _average([float(item.get("score") or 0.0) for item in adapter_case_scores])
    retrieval_full_tokens = _runtime_response_token_total(retrieval_runtime)
    retrieval_small_tokens = _runtime_response_token_total(retrieval_small_runtime)
    adapter_tokens = _runtime_response_token_total(adapter_runtime)
    unsupported_claim_rate = _unsupported_claim_rate(adapter_case_scores)
    wrong_citation_rate = _wrong_citation_rate(adapter_case_scores)
    return {
        "retrieval_only_full": {
            "score": retrieval_full_score,
            "token_count": retrieval_full_tokens,
            "latency_hint": retrieval_runtime.get("mode") or "",
        },
        "retrieval_only_small": {
            "score": retrieval_small_score,
            "token_count": retrieval_small_tokens,
            "latency_hint": retrieval_small_runtime.get("mode") or "",
        },
        "bundle_with_expert": {
            "score": adapter_score,
            "token_count": adapter_tokens,
            "unsupported_claim_rate": unsupported_claim_rate,
            "wrong_citation_rate": wrong_citation_rate,
        },
        "bundle_without_expert": {
            "score": retrieval_full_score,
            "token_count": retrieval_full_tokens,
        },
    }


def _bundle_category_scores(
    *,
    cases: list[dict],
    retrieval_runtime: dict,
    retrieval_small_runtime: dict,
    adapter_runtime: dict,
    retrieval_case_scores: list[dict],
    retrieval_small_case_scores: list[dict],
    adapter_case_scores: list[dict],
) -> dict[str, dict]:
    retrieval_by_case = _scores_by_case_id(retrieval_case_scores)
    retrieval_small_by_case = _scores_by_case_id(retrieval_small_case_scores)
    adapter_by_case = _scores_by_case_id(adapter_case_scores)
    retrieval_runtime_tokens = _runtime_tokens_by_case_id(cases, retrieval_runtime)
    retrieval_small_runtime_tokens = _runtime_tokens_by_case_id(cases, retrieval_small_runtime)
    adapter_runtime_tokens = _runtime_tokens_by_case_id(cases, adapter_runtime)
    meaningful_threshold = 10
    rows: dict[str, dict] = {}
    for category in EVALUATION_CATEGORIES:
        category_cases = [case for case in cases if str(case.get("category") or "") == category]
        case_ids = [str(case.get("id") or "") for case in category_cases if str(case.get("id") or "")]
        retrieval_scores = [
            float((retrieval_by_case.get(case_id) or {}).get("score") or 0.0)
            for case_id in case_ids
            if case_id in retrieval_by_case
        ]
        retrieval_small_scores = [
            float((retrieval_small_by_case.get(case_id) or {}).get("score") or 0.0)
            for case_id in case_ids
            if case_id in retrieval_small_by_case
        ]
        adapter_scores = [
            float((adapter_by_case.get(case_id) or {}).get("score") or 0.0)
            for case_id in case_ids
            if case_id in adapter_by_case
        ]
        retrieval_full_tokens = sum(int(retrieval_runtime_tokens.get(case_id) or 0) for case_id in case_ids)
        retrieval_small_tokens = sum(int(retrieval_small_runtime_tokens.get(case_id) or 0) for case_id in case_ids)
        adapter_tokens = sum(int(adapter_runtime_tokens.get(case_id) or 0) for case_id in case_ids)
        retrieval_full_score = _average(retrieval_scores)
        retrieval_small_score = _average(retrieval_small_scores)
        adapter_score = _average(adapter_scores)
        quality_regression = round(retrieval_full_score - adapter_score, 2)
        quality_gain = round(adapter_score - retrieval_small_score, 2)
        token_savings = round(max(0.0, 100.0 * (1.0 - (adapter_tokens / max(1, retrieval_full_tokens)))), 2)
        adapter_category_scores = [adapter_by_case.get(case_id) or {} for case_id in case_ids if case_id in adapter_by_case]
        rows[category] = {
            "owner": _CATEGORY_SPECS[category]["owner"],
            "counts_toward_graduation": bool(_CATEGORY_SPECS[category]["counts_toward_graduation"]),
            "case_count": len(category_cases),
            "meaningful_case_count_minimum": meaningful_threshold,
            "meaningful_case_count_reached": len(category_cases) >= meaningful_threshold,
            "retrieval_only_full": {
                "score": retrieval_full_score,
                "score_count": len(retrieval_scores),
                "token_count": retrieval_full_tokens,
            },
            "retrieval_only_small": {
                "score": retrieval_small_score,
                "score_count": len(retrieval_small_scores),
                "token_count": retrieval_small_tokens,
            },
            "bundle_with_expert": {
                "score": adapter_score,
                "score_count": len(adapter_scores),
                "token_count": adapter_tokens,
                "unsupported_claim_rate": _unsupported_claim_rate(adapter_category_scores),
                "wrong_citation_rate": _wrong_citation_rate(adapter_category_scores),
            },
            "bundle_without_expert": {
                "score": retrieval_full_score,
                "score_count": len(retrieval_scores),
                "token_count": retrieval_full_tokens,
            },
            "quality_regression_vs_retrieval_full": quality_regression,
            "quality_gain_vs_retrieval_small": quality_gain,
            "token_savings_vs_retrieval_full": token_savings,
            "complete": bool(
                category_cases
                and len(retrieval_scores) == len(category_cases)
                and len(retrieval_small_scores) == len(category_cases)
                and len(adapter_scores) == len(category_cases)
            ),
        }
    return rows


def _bundle_quality_gate(bundle_modes: dict) -> dict:
    retrieval_full = dict(bundle_modes.get("retrieval_only_full") or {})
    retrieval_small = dict(bundle_modes.get("retrieval_only_small") or {})
    bundle_with_expert = dict(bundle_modes.get("bundle_with_expert") or {})
    thresholds = dict(_BUNDLE_BENCHMARK_THRESHOLDS)
    full_score = float(retrieval_full.get("score") or 0.0)
    small_score = float(retrieval_small.get("score") or 0.0)
    expert_score = float(bundle_with_expert.get("score") or 0.0)
    full_tokens = max(1, int(retrieval_full.get("token_count") or 0))
    expert_tokens = int(bundle_with_expert.get("token_count") or 0)
    quality_regression_vs_retrieval_full = round(full_score - expert_score, 2)
    quality_gain_vs_retrieval_small = round(expert_score - small_score, 2)
    token_savings_vs_retrieval_full = round(max(0.0, 100.0 * (1.0 - (expert_tokens / full_tokens))), 2)
    unsupported_claim_rate = float(bundle_with_expert.get("unsupported_claim_rate") or 0.0)
    wrong_citation_rate = float(bundle_with_expert.get("wrong_citation_rate") or 0.0)
    checks = {
        "quality_regression_vs_retrieval_full": quality_regression_vs_retrieval_full <= thresholds["quality_regression_vs_retrieval_full"],
        "quality_gain_vs_retrieval_small": quality_gain_vs_retrieval_small >= thresholds["quality_gain_vs_retrieval_small"],
        "token_savings_vs_retrieval_full": token_savings_vs_retrieval_full >= thresholds["token_savings_vs_retrieval_full"],
        "unsupported_claim_rate": unsupported_claim_rate == 0.0,
        "wrong_citation_rate": wrong_citation_rate == 0.0,
    }
    return {
        "passes": all(checks.values()),
        "checks": checks,
        "quality_regression_vs_retrieval_full": quality_regression_vs_retrieval_full,
        "quality_gain_vs_retrieval_small": quality_gain_vs_retrieval_small,
        "token_savings_vs_retrieval_full": token_savings_vs_retrieval_full,
        "unsupported_claim_rate": unsupported_claim_rate,
        "wrong_citation_rate": wrong_citation_rate,
        "thresholds": thresholds,
    }


def _bundle_benchmark_summary(bundle_modes: dict, bundle_gate: dict) -> dict:
    retrieval_full = dict(bundle_modes.get("retrieval_only_full") or {})
    retrieval_small = dict(bundle_modes.get("retrieval_only_small") or {})
    bundle_with_expert = dict(bundle_modes.get("bundle_with_expert") or {})
    bundle_without_expert = dict(bundle_modes.get("bundle_without_expert") or {})
    return {
        "retrieval_only_full_score": float(retrieval_full.get("score") or 0.0),
        "retrieval_only_small_score": float(retrieval_small.get("score") or 0.0),
        "bundle_with_expert_score": float(bundle_with_expert.get("score") or 0.0),
        "bundle_without_expert_score": float(bundle_without_expert.get("score") or 0.0),
        "retrieval_only_full_tokens": int(retrieval_full.get("token_count") or 0),
        "retrieval_only_small_tokens": int(retrieval_small.get("token_count") or 0),
        "bundle_with_expert_tokens": int(bundle_with_expert.get("token_count") or 0),
        "bundle_without_expert_tokens": int(bundle_without_expert.get("token_count") or 0),
        "quality_regression_vs_retrieval_full": float(bundle_gate.get("quality_regression_vs_retrieval_full") or 0.0),
        "quality_gain_vs_retrieval_small": float(bundle_gate.get("quality_gain_vs_retrieval_small") or 0.0),
        "token_savings_vs_retrieval_full": float(bundle_gate.get("token_savings_vs_retrieval_full") or 0.0),
        "unsupported_claim_rate": float(bundle_gate.get("unsupported_claim_rate") or 0.0),
        "wrong_citation_rate": float(bundle_gate.get("wrong_citation_rate") or 0.0),
        "passes": bool(bundle_gate.get("passes")),
    }


def _bundle_mode_coverage(
    *,
    cases: list[dict],
    retrieval_runtime: dict,
    retrieval_small_runtime: dict,
    adapter_runtime: dict,
    retrieval_case_scores: list[dict],
    retrieval_small_case_scores: list[dict],
    adapter_case_scores: list[dict],
) -> dict:
    expected_count = len(cases)
    retrieval_score_count = len(_scores_by_case_id(retrieval_case_scores))
    retrieval_small_score_count = len(_scores_by_case_id(retrieval_small_case_scores))
    adapter_score_count = len(_scores_by_case_id(adapter_case_scores))
    mode_rows = {
        "retrieval_only_full": {
            "response_count": len(list(retrieval_runtime.get("responses") or [])),
            "score_count": retrieval_score_count,
        },
        "retrieval_only_small": {
            "response_count": len(list(retrieval_small_runtime.get("responses") or [])),
            "score_count": retrieval_small_score_count,
        },
        "bundle_with_expert": {
            "response_count": len(list(adapter_runtime.get("responses") or [])),
            "score_count": adapter_score_count,
        },
        "bundle_without_expert": {
            "response_count": len(list(retrieval_runtime.get("responses") or [])),
            "score_count": retrieval_score_count,
        },
    }
    missing_modes: list[str] = []
    incomplete_modes: list[str] = []
    for mode_name, row in mode_rows.items():
        if expected_count == 0:
            row["complete"] = True
            continue
        response_count = int(row["response_count"])
        score_count = int(row["score_count"])
        complete = response_count >= expected_count and score_count >= expected_count
        row["complete"] = complete
        if response_count == 0 and score_count == 0:
            missing_modes.append(mode_name)
        elif not complete:
            incomplete_modes.append(mode_name)
    return {
        "expected_case_count": expected_count,
        "passes": not missing_modes and not incomplete_modes,
        "missing_modes": missing_modes,
        "incomplete_modes": incomplete_modes,
        "modes": mode_rows,
    }


def _bundle_readiness_report(
    *,
    live_adapter_backed: bool,
    bundle_mode_coverage: dict,
    missing_categories: list[str],
    incomplete_categories: list[str],
    bundle_gate: dict,
    status: str,
) -> dict:
    failure_reasons: list[str] = []
    if not live_adapter_backed:
        failure_reasons.append("pending_live_adapter_benchmark")
    if list(bundle_mode_coverage.get("missing_modes") or []):
        failure_reasons.append("missing_bundle_modes")
    if list(bundle_mode_coverage.get("incomplete_modes") or []):
        failure_reasons.append("incomplete_bundle_modes")
    if missing_categories:
        failure_reasons.append("legacy_missing_graduation_categories")
    if incomplete_categories:
        failure_reasons.append("legacy_incomplete_graduation_categories")
    for check_name, passed in dict(bundle_gate.get("checks") or {}).items():
        if not passed:
            failure_reasons.append(check_name)
    return {
        "status": status,
        "passes": bool(bundle_gate.get("passes")) and not failure_reasons,
        "failure_reasons": failure_reasons,
        "mode_coverage": bundle_mode_coverage,
        "legacy_category_completeness": {
            "missing_categories": list(missing_categories),
            "incomplete_categories": list(incomplete_categories),
        },
    }


def _mode_case_outputs(
    *,
    cases: list[dict],
    retrieval_runtime: dict,
    retrieval_small_runtime: dict,
    adapter_runtime: dict,
    retrieval_case_scores: list[dict],
    retrieval_small_case_scores: list[dict],
    adapter_case_scores: list[dict],
) -> dict:
    retrieval_scores = _scores_by_case_id(retrieval_case_scores)
    retrieval_small_scores = _scores_by_case_id(retrieval_small_case_scores)
    adapter_scores = _scores_by_case_id(adapter_case_scores)
    return {
        "retrieval_only_full": _runtime_mode_case_rows(
            mode_name="retrieval_only_full",
            cases=cases,
            runtime=retrieval_runtime,
            scores_by_case=retrieval_scores,
        ),
        "retrieval_only_small": _runtime_mode_case_rows(
            mode_name="retrieval_only_small",
            cases=cases,
            runtime=retrieval_small_runtime,
            scores_by_case=retrieval_small_scores,
        ),
        "bundle_with_expert": _runtime_mode_case_rows(
            mode_name="bundle_with_expert",
            cases=cases,
            runtime=adapter_runtime,
            scores_by_case=adapter_scores,
        ),
        "bundle_without_expert": _runtime_mode_case_rows(
            mode_name="bundle_without_expert",
            cases=cases,
            runtime=retrieval_runtime,
            scores_by_case=retrieval_scores,
        ),
    }


def _runtime_mode_case_rows(
    *,
    mode_name: str,
    cases: list[dict],
    runtime: dict,
    scores_by_case: dict[str, dict],
) -> list[dict]:
    responses = list(runtime.get("responses") or [])
    rows: list[dict] = []
    for index, case in enumerate(cases):
        response = responses[index] if index < len(responses) else {}
        score = dict(scores_by_case.get(str(case.get("id") or "")) or {})
        runtime_prompt = str(response.get("prompt") or case.get("prompt") or "")
        response_text = str(response.get("response_text") or "")
        retrieval_evidence = _normalized_retrieval_evidence(response.get("citations"))
        raw_packet_text = _benchmark_packet_text(
            mode_name=mode_name,
            prompt=runtime_prompt,
            response_text=response_text,
            retrieval_evidence=retrieval_evidence,
        )
        token_ledger = _benchmark_token_ledger(
            prompt=runtime_prompt,
            response_text=response_text,
            retrieval_evidence=retrieval_evidence,
            raw_packet_text=raw_packet_text,
        )
        expert_used = mode_name == "bundle_with_expert"
        rows.append(
            {
                "mode": mode_name,
                "case_id": str(case.get("id") or ""),
                "category": str(case.get("category") or ""),
                "prompt": str(case.get("prompt") or ""),
                "runtime_prompt": runtime_prompt,
                "source_title": str(case.get("source_title") or ""),
                "response_text": response_text,
                "raw_packet_text": raw_packet_text,
                "citations": retrieval_evidence,
                "retrieval_evidence": retrieval_evidence,
                "retrieval_hits": int(response.get("retrieval_hits") or 0),
                "truncated": bool(response.get("truncated")),
                "effective_max_new_tokens": response.get("effective_max_new_tokens"),
                "expert_used": expert_used,
                "adapter_prompt": runtime_prompt if expert_used else "",
                "adapter_raw_output": response_text if expert_used else "",
                "token_ledger": token_ledger,
                "score": score.get("score"),
                "grounding_consistency_score": score.get("grounding_consistency_score"),
                "citation_present": score.get("citation_present"),
                "routed_away": bool(score.get("routed_away")),
            }
        )
    return rows


def _normalized_retrieval_evidence(citations: list[dict] | None) -> list[dict]:
    normalized: list[dict] = []
    for item in list(citations or []):
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "source_id": str(item.get("source_id") or ""),
                "title": str(item.get("title") or ""),
                "snippet": str(item.get("snippet") or ""),
                "page": item.get("page"),
                "chunk_id": item.get("chunk_id"),
            }
        )
    return normalized


def _benchmark_packet_text(
    *,
    mode_name: str,
    prompt: str,
    response_text: str,
    retrieval_evidence: list[dict],
) -> str:
    lines = [
        f"Mode: {mode_name}",
        f"Prompt: {prompt.strip()}",
        "",
        "Packet response:",
        str(response_text or "").strip(),
    ]
    if retrieval_evidence:
        lines.extend(["", "Retrieval evidence:"])
        for item in retrieval_evidence:
            title = str(item.get("title") or "").strip() or "Untitled"
            snippet = str(item.get("snippet") or "").strip()
            source_id = str(item.get("source_id") or "").strip()
            evidence_line = f"- [{title}]"
            if source_id:
                evidence_line += f" ({source_id})"
            if snippet:
                evidence_line += f": {snippet}"
            lines.append(evidence_line)
    return "\n".join(lines).strip()


def _benchmark_token_ledger(
    *,
    prompt: str,
    response_text: str,
    retrieval_evidence: list[dict],
    raw_packet_text: str,
) -> dict:
    retrieval_evidence_text = "\n".join(
        f"{str(item.get('title') or '').strip()} {str(item.get('snippet') or '').strip()}".strip()
        for item in retrieval_evidence
    ).strip()
    prompt_tokens = _estimate_text_tokens(prompt)
    response_tokens = _estimate_text_tokens(response_text)
    retrieval_tokens = _estimate_text_tokens(retrieval_evidence_text)
    packet_tokens = _estimate_text_tokens(raw_packet_text)
    return {
        "prompt_tokens_estimate": prompt_tokens,
        "response_tokens_estimate": response_tokens,
        "retrieval_evidence_tokens_estimate": retrieval_tokens,
        "packet_tokens_estimate": packet_tokens,
        "total_tokens_estimate": prompt_tokens + response_tokens + retrieval_tokens,
    }


def _runtime_tokens_by_case_id(cases: list[dict], runtime: dict) -> dict[str, int]:
    responses = list(runtime.get("responses") or [])
    rows: dict[str, int] = {}
    for index, case in enumerate(cases):
        case_id = str(case.get("id") or "")
        if not case_id:
            continue
        response = responses[index] if index < len(responses) else {}
        rows[case_id] = _estimate_text_tokens(str(response.get("response_text") or ""))
    return rows


def _runtime_response_token_total(runtime: dict) -> int:
    responses = list(runtime.get("responses") or [])
    total = 0
    for response in responses:
        total += _estimate_text_tokens(str(response.get("response_text") or ""))
    return total


def _estimate_text_tokens(text: str) -> int:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return 0
    return max(1, (len(cleaned) + 3) // 4)


def _truncate_words(text: str, limit: int) -> str:
    words = str(text or "").split()
    if len(words) <= limit:
        return str(text or "").strip()
    return " ".join(words[:limit]).strip()


def _unsupported_claim_rate(case_scores: list[dict]) -> float:
    if not case_scores:
        return 0.0
    unsupported = sum(
        1
        for item in case_scores
        if float(item.get("grounding_consistency_score") or 0.0) < 1.0
    )
    return round(unsupported / len(case_scores), 4)


def _wrong_citation_rate(case_scores: list[dict]) -> float:
    citation_cases = [item for item in case_scores if str(item.get("category") or "") == "citation_grounding"]
    if not citation_cases:
        return 0.0
    wrong = sum(1 for item in citation_cases if not bool(item.get("citation_present")))
    return round(wrong / len(citation_cases), 4)


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
