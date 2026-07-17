from __future__ import annotations

import argparse
import json
import re
import sqlite3
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
                "odin": _odin_context(case.odin_db, question["question"], args.context_chars),
                "graphify": _graphify_context(
                    case.graphify_graph, question["question"], args.context_chars
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
                case_result["evaluations"].append(
                    {
                        "question_id": question["id"],
                        "question": question["question"],
                        "tool": tool,
                        "context_chars": len(context),
                        "context_lines": len(context.splitlines()),
                        "answer": answer,
                        "matched_fact_groups": matched,
                        "fact_group_count": len(question["required_fact_groups"]),
                        "score": score,
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


def _odin_context(database: Path, question: str, budget: int) -> str:
    keywords = _keywords(question)
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    try:
        snapshot = conn.execute(
            "SELECT active_structure_snapshot_id FROM projects ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if snapshot is None or not snapshot["active_structure_snapshot_id"]:
            raise RuntimeError(f"No active Odin structure snapshot in {database}")
        snapshot_id = snapshot["active_structure_snapshot_id"]
        nodes = [dict(row) for row in conn.execute(
            "SELECT id, kind, display_label AS label, relative_path, start_line, signature FROM code_nodes WHERE snapshot_id = ?",
            (snapshot_id,),
        )]
        node_by_id = {str(node["id"]): node for node in nodes}
        ranked = sorted(
            nodes,
            key=lambda node: (
                -_rank(
                    " ".join(str(node.get(key) or "") for key in ("label", "relative_path", "kind", "signature")),
                    keywords,
                ),
                str(node.get("relative_path") or ""),
                str(node.get("label") or ""),
            ),
        )
        seeds = [node for node in ranked if _rank(json.dumps(node), keywords) > 0][:28]
        if not seeds:
            seeds = ranked[:12]
        seed_ids = {str(node["id"]) for node in seeds}
        edges = [dict(row) for row in conn.execute(
            "SELECT source_node_id, target_node_id, edge_type, source_line FROM code_edges WHERE snapshot_id = ?",
            (snapshot_id,),
        ) if str(row["source_node_id"]) in seed_ids or str(row["target_node_id"]) in seed_ids]
    finally:
        conn.close()
    lines = ["ODIN GRAPH SLICE", "NODES"]
    for node in seeds:
        lines.append(
            f"- {node['kind']} {node['label']} | {node['relative_path']}:{node['start_line']} | {node.get('signature') or ''}"
        )
    lines.append("RELATIONSHIPS")
    for edge in edges[:140]:
        source = node_by_id.get(str(edge["source_node_id"]), {})
        target = node_by_id.get(str(edge["target_node_id"]), {})
        evidence_path = source.get("relative_path") or target.get("relative_path") or ""
        lines.append(
            f"- {source.get('label', edge['source_node_id'])} -[{edge['edge_type']}]-> "
            f"{target.get('label', edge['target_node_id'])} | {evidence_path}:{edge.get('source_line') or ''}"
        )
    return _bounded(lines, budget)


def _graphify_context(graph_path: Path, question: str, budget: int) -> str:
    keywords = _keywords(question)
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    nodes = list(graph.get("nodes") or [])
    node_by_id = {str(node.get("id")): node for node in nodes}
    ranked = sorted(
        nodes,
        key=lambda node: (
            -_rank(
                " ".join(
                    str(node.get(key) or "")
                    for key in ("label", "source_file", "source_location", "file_type")
                ),
                keywords,
            ),
            str(node.get("source_file") or ""),
            str(node.get("label") or ""),
        ),
    )
    seeds = [node for node in ranked if _rank(json.dumps(node), keywords) > 0][:28]
    if not seeds:
        seeds = ranked[:12]
    seed_ids = {str(node.get("id")) for node in seeds}
    links = [
        link
        for link in (graph.get("links") or graph.get("edges") or [])
        if str(link.get("source")) in seed_ids or str(link.get("target")) in seed_ids
    ]
    lines = ["GRAPHIFY GRAPH SLICE", "NODES"]
    for node in seeds:
        lines.append(
            f"- {node.get('label')} | {node.get('source_file', '')}:{node.get('source_location', '')}"
        )
    lines.append("RELATIONSHIPS")
    for link in links[:140]:
        source = node_by_id.get(str(link.get("source")), {})
        target = node_by_id.get(str(link.get("target")), {})
        lines.append(
            f"- {source.get('label', link.get('source'))} -[{link.get('relation', link.get('type', 'related'))}]-> "
            f"{target.get('label', link.get('target'))} | {link.get('source_file', '')}:{link.get('source_location', '')}"
        )
    return _bounded(lines, budget)


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
    by_tool: dict[str, list[float]] = {}
    for evaluation in evaluations:
        by_tool.setdefault(evaluation["tool"], []).append(float(evaluation["score"]))
    return {
        tool: {
            "questions": len(scores),
            "mean_score": round(sum(scores) / len(scores), 3),
            "fully_answered": sum(score == 1.0 for score in scores),
        }
        for tool, scores in sorted(by_tool.items())
    }


if __name__ == "__main__":
    raise SystemExit(main())
