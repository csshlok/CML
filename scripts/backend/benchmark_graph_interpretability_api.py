from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

from scripts.backend.benchmark_graph_interpretability import (
    Case,
    _graphify_context,
    _odin_context,
    _parse_case,
    _prompt,
    _score,
    _summary,
)
from scripts.backend.evaluate_vault_longmemeval_api import (
    Provider,
    _chat,
    _provider,
    _provider_cost,
    _usage,
)


TOOLS = ("none", "odin", "graphify")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Measure Kimi K2.6 interpretation of bounded Odin and Graphify graph "
            "contexts with Kimi and GPT-5.4 rubric judges."
        )
    )
    parser.add_argument("--case", action="append", required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--odin-python", type=Path, required=True)
    parser.add_argument("--graphify", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--context-chars", type=int, default=6_000)
    parser.add_argument("--max-answer-tokens", type=int, default=160)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--limit-per-case", type=int, default=0)
    parser.add_argument("--reader-model", default="kimi-k2.6")
    parser.add_argument("--primary-judge-model", default="kimi-k2.6")
    parser.add_argument("--independent-judge-model", default="gpt-5.4-2026-03-05")
    return parser.parse_args()


def _key(case: str, question_id: str, tool: str) -> str:
    return f"{case}/{question_id}/{tool}"


def _load_checkpoint(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    return {
        _key(row["case"], row["question_id"], row["tool"]): row
        for row in document.get("evaluations", [])
    }


def _write_checkpoint(path: Path, evaluations: dict[str, dict], metadata: dict) -> None:
    ordered = [evaluations[key] for key in sorted(evaluations)]
    document = {
        **metadata,
        "evaluations": ordered,
        "lexical_fact_summary": _summary(ordered) if ordered else {},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, indent=2), encoding="utf-8")
    temporary.replace(path)


def _context(
    args: argparse.Namespace,
    case: Case,
    question: str,
    tool: str,
) -> str:
    if tool == "none":
        return "No repository graph context was provided."
    if tool == "odin":
        return _odin_context(
            args.odin_python, case.odin_db, question, args.context_chars
        )
    return _graphify_context(
        args.graphify, case.graphify_graph, question, args.context_chars
    )


def _judge_prompt(question: dict, answer: str) -> str:
    groups = "\n".join(
        f"- Fact group {position}: " + " OR ".join(str(value) for value in alternatives)
        for position, alternatives in enumerate(question["required_fact_groups"], start=1)
    )
    return f"""Act as a strict codebase-answer evaluator.
Answer yes only when the model response correctly answers the question's core mechanism and
contains no material factual error. Each fact group lists interchangeable acceptable evidence;
the response does not need to use the exact spelling when it is semantically equivalent.
Answer no when the response guesses, contradicts the rubric, or omits the central mechanism.

QUESTION
{question['question']}

EXPECTED FACT GROUPS
{groups}

MODEL RESPONSE
{answer}

VERDICT (yes or no only)
"""


def _judge(
    args: argparse.Namespace,
    provider: Provider,
    question: dict,
    answer: str,
) -> dict:
    started = time.perf_counter()
    response = _chat(
        provider,
        _judge_prompt(question, answer),
        max_tokens=10,
        timeout=args.timeout,
        retries=args.retries,
    )
    raw = response["choices"][0]["message"]["content"].strip()
    return {
        "provider": provider.name,
        "model": provider.model,
        "label": raw.casefold().strip(" .!\n\t").startswith("yes"),
        "raw": raw,
        "usage": _usage(response),
        "wall_seconds": round(time.perf_counter() - started, 4),
    }


def _aggregate(evaluations: list[dict], providers: dict[str, Provider]) -> dict:
    by_tool: dict[str, list[dict]] = {tool: [] for tool in TOOLS}
    for row in evaluations:
        by_tool[row["tool"]].append(row)
    tool_metrics = {}
    for tool, rows in by_tool.items():
        agreements = [
            row["primary_judge"]["label"] == row["independent_judge"]["label"]
            for row in rows
        ]
        tool_metrics[tool] = {
            "questions": len(rows),
            "mean_lexical_fact_mention_recall": round(
                statistics.fmean(float(row["score"]) for row in rows), 4
            )
            if rows
            else None,
            "mean_context_fact_mention_recall": round(
                statistics.fmean(float(row["context_score"]) for row in rows), 4
            )
            if rows
            else None,
            "mean_context_backed_fact_mention_recall": round(
                statistics.fmean(float(row["supported_score"]) for row in rows), 4
            )
            if rows
            else None,
            "unsupported_answer_fact_mentions": sum(
                int(row["unsupported_matched_fact_groups"]) for row in rows
            ),
            "kimi_judge_accuracy": round(
                statistics.fmean(bool(row["primary_judge"]["label"]) for row in rows), 4
            )
            if rows
            else None,
            "openai_judge_accuracy": round(
                statistics.fmean(bool(row["independent_judge"]["label"]) for row in rows), 4
            )
            if rows
            else None,
            "judge_agreement": round(statistics.fmean(agreements), 4) if rows else None,
            "median_reader_seconds": round(
                statistics.median(float(row["reader_wall_seconds"]) for row in rows), 4
            )
            if rows
            else None,
        }
    reader_usage = [row["reader_usage"] for row in evaluations]
    primary_usage = [row["primary_judge"]["usage"] for row in evaluations]
    independent_usage = [row["independent_judge"]["usage"] for row in evaluations]
    costs = {
        "kimi_reader": _provider_cost(providers["reader"], reader_usage),
        "kimi_primary_judge": _provider_cost(providers["primary"], primary_usage),
        "openai_independent_judge": _provider_cost(
            providers["independent"], independent_usage
        ),
    }
    costs["total_estimated_usd"] = round(
        sum(item["estimated_usd_at_uncached_rate"] for item in costs.values()), 6
    )
    return {"by_tool": tool_metrics, "usage_and_estimated_cost": costs}


def main() -> int:
    args = parse_args()
    cases = [_parse_case(value) for value in args.case]
    questions = json.loads(args.questions.read_text(encoding="utf-8"))
    providers = {
        "reader": _provider("kimi", args.reader_model),
        "primary": _provider("kimi", args.primary_judge_model),
        "independent": _provider("openai", args.independent_judge_model),
    }
    evaluations = _load_checkpoint(args.output)
    metadata: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "reader_model": providers["reader"].model,
        "primary_judge_model": providers["primary"].model,
        "independent_judge_model": providers["independent"].model,
        "context_char_budget": args.context_chars,
        "max_answer_tokens": args.max_answer_tokens,
    }

    for case in cases:
        configured = questions.get(case.name) or []
        configured = configured[: args.limit_per_case or None]
        for question in configured:
            for tool in TOOLS:
                evaluation_key = _key(case.name, question["id"], tool)
                existing = evaluations.get(evaluation_key)
                if (
                    existing
                    and existing.get("reader_model") == providers["reader"].model
                    and int(existing.get("context_char_budget", args.context_chars))
                    == args.context_chars
                    and int(existing.get("max_answer_tokens", args.max_answer_tokens))
                    == args.max_answer_tokens
                    and (existing.get("primary_judge") or {}).get("model")
                    == providers["primary"].model
                    and (existing.get("independent_judge") or {}).get("model")
                    == providers["independent"].model
                ):
                    continue
                context = _context(args, case, question["question"], tool)
                started = time.perf_counter()
                response = _chat(
                    providers["reader"],
                    _prompt(case.name, question["question"], context),
                    max_tokens=args.max_answer_tokens,
                    timeout=args.timeout,
                    retries=args.retries,
                )
                answer = response["choices"][0]["message"]["content"].strip()
                score, matched = _score(answer, question["required_fact_groups"])
                context_score, context_matched = _score(
                    context, question["required_fact_groups"]
                )
                supported_groups = sum(
                    bool(answer_group["matched"]) and bool(context_group["matched"])
                    for answer_group, context_group in zip(
                        matched, context_matched, strict=True
                    )
                )
                unsupported_groups = sum(
                    bool(answer_group["matched"]) and not bool(context_group["matched"])
                    for answer_group, context_group in zip(
                        matched, context_matched, strict=True
                    )
                )
                row = {
                    "case": case.name,
                    "question_id": question["id"],
                    "category": question.get("category", "unspecified"),
                    "question": question["question"],
                    "tool": tool,
                    "context_chars": len(context),
                    "context_lines": len(context.splitlines()),
                    "answer": answer,
                    "reader_model": providers["reader"].model,
                    "context_char_budget": args.context_chars,
                    "max_answer_tokens": args.max_answer_tokens,
                    "reader_usage": _usage(response),
                    "reader_wall_seconds": round(time.perf_counter() - started, 4),
                    "wall_seconds": round(time.perf_counter() - started, 4),
                    "matched_fact_groups": matched,
                    "context_matched_fact_groups": context_matched,
                    "fact_group_count": len(question["required_fact_groups"]),
                    "score": score,
                    "context_score": context_score,
                    "supported_score": round(
                        supported_groups / max(1, len(question["required_fact_groups"])), 3
                    ),
                    "unsupported_matched_fact_groups": unsupported_groups,
                    "primary_judge": _judge(
                        args, providers["primary"], question, answer
                    ),
                    "independent_judge": _judge(
                        args, providers["independent"], question, answer
                    ),
                }
                evaluations[evaluation_key] = row
                metadata["summary"] = _aggregate(
                    list(evaluations.values()), providers
                )
                _write_checkpoint(args.output, evaluations, metadata)
                print(
                    f"{evaluation_key}: exact={score:.3f} "
                    f"kimi={row['primary_judge']['raw']} "
                    f"openai={row['independent_judge']['raw']}",
                    flush=True,
                )

    metadata["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    metadata["summary"] = _aggregate(list(evaluations.values()), providers)
    _write_checkpoint(args.output, evaluations, metadata)
    print(json.dumps(metadata["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
