from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


STOP_WORDS = {
    "and", "are", "does", "flask", "for", "how", "implement", "implements", "in",
    "is", "it", "primary", "the", "them", "to", "what", "where", "which", "with",
    "zustand",
}


@dataclass(frozen=True)
class Case:
    name: str
    odin_db: Path
    graphify_graph: Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure how a local third-party model interprets bounded Odin and Graphify graph slices."
    )
    parser.add_argument(
        "--case",
        action="append",
        required=True,
        metavar="NAME,ODIN_DB,GRAPHIFY_GRAPH",
    )
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--model", required=True, help="Local model path or cached Hugging Face model id.")
    parser.add_argument("--odin-python", type=Path, required=True, help="Python executable for the Odin backend environment.")
    parser.add_argument("--graphify", type=Path, required=True, help="Graphify CLI executable.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--context-chars", type=int, default=16_000)
    parser.add_argument("--max-new-tokens", type=int, default=320)
    args = parser.parse_args()

    cases = [_parse_case(value) for value in args.case]
    questions = json.loads(args.questions.read_text(encoding="utf-8"))
    tokenizer, model, device = _load_model(args.model)
    result: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": args.model,
        "device": device,
        "context_char_budget": args.context_chars,
        "max_new_tokens": args.max_new_tokens,
        "cases": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _write_checkpoint(args.output, result)

    for case in cases:
        case_questions = questions.get(case.name)
        if not case_questions:
            raise ValueError(f"No questions configured for {case.name}")
        case_result: dict[str, Any] = {"name": case.name, "evaluations": []}
        result["cases"].append(case_result)
        for question in case_questions:
            contexts = {
                "none": "No repository graph context was provided.",
                "odin": _odin_context(
                    args.odin_python, case.odin_db, question["question"], args.context_chars
                ),
                "graphify": _graphify_context(
                    args.graphify, case.graphify_graph, question["question"], args.context_chars
                ),
            }
            for tool, context in contexts.items():
                prompt = _prompt(case.name, question["question"], context)
                started = time.perf_counter()
                answer = _generate(
                    tokenizer,
                    model,
                    prompt,
                    max_new_tokens=args.max_new_tokens,
                )
                elapsed = time.perf_counter() - started
                score, matched = _score(answer, question["required_fact_groups"])
                context_score, context_matched = _score(context, question["required_fact_groups"])
                supported_groups = sum(
                    bool(answer_group["matched"]) and bool(context_group["matched"])
                    for answer_group, context_group in zip(matched, context_matched, strict=True)
                )
                unsupported_groups = sum(
                    bool(answer_group["matched"]) and not bool(context_group["matched"])
                    for answer_group, context_group in zip(matched, context_matched, strict=True)
                )
                case_result["evaluations"].append(
                    {
                        "question_id": question["id"],
                        "category": question.get("category", "unspecified"),
                        "question": question["question"],
                        "tool": tool,
                        "context_chars": len(context),
                        "context_lines": len(context.splitlines()),
                        "answer": answer,
                        "matched_fact_groups": matched,
                        "context_matched_fact_groups": context_matched,
                        "fact_group_count": len(question["required_fact_groups"]),
                        "score": score,
                        "context_score": context_score,
                        "supported_score": round(
                            supported_groups / max(1, len(question["required_fact_groups"])), 3
                        ),
                        "unsupported_matched_fact_groups": unsupported_groups,
                        "wall_seconds": round(elapsed, 3),
                    }
                )
                case_result["summary"] = _summary(case_result["evaluations"])
                _write_checkpoint(args.output, result)
                print(
                    f"{case.name}/{question['id']}/{tool}: score={score:.2f} wall={elapsed:.2f}s",
                    flush=True,
                )
        case_result["summary"] = _summary(case_result["evaluations"])

    result["summary"] = _summary(
        [evaluation for case in result["cases"] for evaluation in case["evaluations"]]
    )
    _write_checkpoint(args.output, result)
    print(json.dumps(result["summary"], separators=(",", ":")))
    return 0


def _write_checkpoint(output: Path, result: dict[str, Any]) -> None:
    """Keep completed evaluations usable when a long local-model run is interrupted."""
    evaluations = [
        evaluation
        for case in result["cases"]
        for evaluation in case.get("evaluations", [])
    ]
    result["summary"] = _summary(evaluations) if evaluations else {}
    temporary = output.with_suffix(f"{output.suffix}.tmp")
    temporary.write_text(json.dumps(result, indent=2), encoding="utf-8")
    temporary.replace(output)


def _parse_case(value: str) -> Case:
    parts = [part.strip() for part in value.split(",", 2)]
    if len(parts) != 3 or not all(parts):
        raise ValueError(f"Invalid --case value: {value!r}")
    return Case(parts[0], Path(parts[1]).resolve(strict=True), Path(parts[2]).resolve(strict=True))


def _keywords(question: str) -> set[str]:
    words = {word.casefold() for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]+", question)}
    return {word for word in words if len(word) >= 3 and word not in STOP_WORDS}


def _rank(text: str, keywords: set[str]) -> int:
    lowered = text.casefold()
    return sum(4 if word in lowered else 0 for word in keywords)


def _odin_context(python: Path, database: Path, question: str, budget: int) -> str:
    completed = subprocess.run(
        [
            str(python.resolve(strict=True)),
            "-m", "scripts.backend.export_odin_graph_context",
            "--database", str(database),
            "--question", question,
            "--budget", str(budget),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Odin graph export failed: {completed.stderr[-2000:]}")
    return completed.stdout


def _graphify_context(executable: Path, graph_path: Path, question: str, budget: int) -> str:
    completed = subprocess.run(
        [
            str(executable.resolve(strict=True)), "query", question,
            "--budget", str(max(256, budget // 4)),
            "--graph", str(graph_path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Graphify query failed: {completed.stderr[-2000:]}")
    return _bounded(completed.stdout.splitlines(), budget)


def _bounded(lines: list[str], budget: int) -> str:
    selected: list[str] = []
    used = 0
    for line in lines:
        addition = len(line) + 1
        if selected and used + addition > budget:
            break
        selected.append(line)
        used += addition
    return "\n".join(selected)


def _prompt(repository: str, question: str, context: str) -> str:
    return f"""You are reviewing the {repository} codebase using only the supplied graph context.
Answer the question in at most 120 words. Name exact symbols and source paths when the context supports them.
If the graph does not contain enough evidence, say what is missing. Do not rely on prior knowledge.

QUESTION
{question}

GRAPH CONTEXT
{context}
"""


def _load_model(model_name: str):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        local_files_only=True,
        dtype=dtype,
    )
    model.to(device)
    model.eval()
    return tokenizer, model, device


def _generate(tokenizer, model, prompt: str, *, max_new_tokens: int) -> str:
    import torch

    messages = [{"role": "user", "content": prompt}]
    rendered = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(rendered, return_tensors="pt").to(model.device)
    with torch.inference_mode():
        output = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            repetition_penalty=1.05,
            pad_token_id=tokenizer.eos_token_id,
        )
    generated = output[0, inputs["input_ids"].shape[1]:]
    return tokenizer.decode(generated, skip_special_tokens=True).strip()


def _score(answer: str, groups: list[list[str]]) -> tuple[float, list[dict[str, Any]]]:
    normalized = answer.casefold().replace("\\", "/")
    matched = []
    for alternatives in groups:
        hits = [value for value in alternatives if value.casefold() in normalized]
        matched.append({"alternatives": alternatives, "matched": hits})
    score = sum(bool(item["matched"]) for item in matched) / max(1, len(groups))
    return round(score, 3), matched


def _summary(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    by_tool: dict[str, list[dict[str, Any]]] = {}
    for evaluation in evaluations:
        by_tool.setdefault(evaluation["tool"], []).append(evaluation)
    return {
        tool: {
            "questions": len(items),
            "mean_score": round(sum(float(item["score"]) for item in items) / len(items), 3),
            "mean_context_score": round(
                sum(float(item["context_score"]) for item in items) / len(items), 3
            ),
            "mean_supported_score": round(
                sum(float(item["supported_score"]) for item in items) / len(items), 3
            ),
            "unsupported_matched_fact_groups": sum(
                int(item["unsupported_matched_fact_groups"]) for item in items
            ),
            "fully_answered": sum(float(item["score"]) == 1.0 for item in items),
            "median_wall_seconds": round(
                statistics.median(float(item["wall_seconds"]) for item in items), 3
            ),
        }
        for tool, items in sorted(by_tool.items())
    }


if __name__ == "__main__":
    raise SystemExit(main())
