from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.claim_evidence_packing import SessionEnvelope, pack_claim_evidence
from backend.app.core.config import get_settings
from backend.app.core.context_memory import get_context_memory
from backend.app.core.database import connect, init_db
from backend.app.core.temporal_facts import sync_chat_session_temporal_facts
from backend.app.core.typed_evidence_runtime import contract_memory_item, evaluate_runtime_evidence
from scripts.backend.evaluate_vault_longmemeval_api import (
    _chat,
    _finish_reason,
    _provider,
    _provider_cost,
    _usage,
)


PROTOCOL = "vault-evolving-memory-paired-reader-v3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare legacy claim packing with Vault's production temporal memory.")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--reader-token-budget", type=int, default=1200)
    parser.add_argument("--reader-model", default="kimi-k2.6")
    parser.add_argument("--judge-model", default="gpt-5.4-2026-03-05")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=3)
    return parser.parse_args()


def _answer(response: dict) -> str:
    choices = response.get("choices") or []
    message = (choices[0] if choices else {}).get("message") or {}
    content = message.get("content") or ""
    if isinstance(content, list):
        content = "".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
    return str(content).strip()


def _reader_prompt(question: str, context: str) -> str:
    return (
        "Answer the question using only the evidence below. Resolve current or latest facts by date, "
        "preserve earlier values when history is requested, and use an exact date when the evidence provides one. "
        "Be concise. If the answer is absent, say you do not know.\n\n"
        f"Evidence:\n{context}\n\nQuestion: {question}\nAnswer:"
    )


def _judge_prompt(case: dict, answer: str) -> str:
    return (
        "Judge whether the candidate answer correctly answers the question according to the reference. "
        "Paraphrases are acceptable. Do not require the candidate to repeat the subject already named in the "
        "question. Accurate dates or explanatory detail beyond the reference are allowed and are not contradictions. "
        "Return NO only when a required answer fact is missing or a material contradiction is present. "
        "Reply with exactly YES or NO.\n\n"
        f"Question: {case['question']}\nReference: {case['reference_answer']}\nCandidate: {answer}\nVerdict:"
    )


def _deterministic(case: dict, answer: str) -> bool:
    normalized = " ".join(re.sub(r"[^a-z0-9]+", " ", answer.casefold()).split())
    for alternatives in case["required_groups"]:
        if not any(" ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split()) in normalized for value in alternatives):
            return False
    return True


def _baseline_context(case: dict, budget: int) -> tuple[str, dict]:
    sessions = [
        SessionEnvelope(
            session_id=item["session_id"],
            date=item["date"],
            turns=item["turns"],
            retrieval_rank=rank,
        )
        for rank, item in enumerate(case["sessions"])
    ]
    return pack_claim_evidence(
        question=case["question"], sessions=sessions, token_budget=budget, consolidate=False
    )


def _candidate_context(case: dict, root: Path) -> tuple[str, dict]:
    old_database = os.environ.get("CML_DATABASE_PATH")
    old_data = os.environ.get("CML_DATA_DIR")
    database_path = root / f"{case['id']}.sqlite3"
    os.environ["CML_DATABASE_PATH"] = str(database_path)
    os.environ["CML_DATA_DIR"] = str(root)
    get_settings.cache_clear()
    try:
        init_db()
        vault_id = f"vault-{case['id']}"
        with connect() as conn:
            first_date = min(item["date"] for item in case["sessions"])
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (vault_id, "Benchmark", str(root), first_date, first_date),
            )
            for item in case["sessions"]:
                conn.execute(
                    "INSERT INTO chat_sessions (id, vault_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (item["session_id"], vault_id, item["session_id"], item["date"], item["date"]),
                )
                for turn_index, turn in enumerate(item["turns"]):
                    conn.execute(
                        """INSERT INTO chat_messages
                        (id, session_id, role, content, clusters_used, citations, warnings, created_at)
                        VALUES (?, ?, ?, ?, '[]', '[]', '[]', ?)""",
                        (f"msg-{item['session_id']}-{turn_index}", item["session_id"], turn["role"], turn["content"], item["date"]),
                    )
                messages = conn.execute(
                    "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at, rowid",
                    (item["session_id"],),
                ).fetchall()
                sync_chat_session_temporal_facts(conn, vault_id=vault_id, session_id=item["session_id"], messages=messages)

            memory_items, _working = get_context_memory(
                conn, vault_id=vault_id, cluster_id=None, query=case["question"], limit=16
            )
            decision = evaluate_runtime_evidence(
                conn, vault_id=vault_id, cluster_id=None, question=case["question"]
            )
            contract = contract_memory_item(decision)
            if contract:
                memory_items = [contract, *memory_items]
            rows = conn.execute(
                "SELECT id, status, assertion_kind FROM temporal_facts WHERE vault_id = ?",
                (vault_id,),
            ).fetchall()
            rendered = []
            seen: set[str] = set()
            for item in memory_items:
                text = str(item.get("detail_text") or item.get("summary") or "").strip()
                if text and text not in seen:
                    seen.add(text)
                    rendered.append(text)
            diagnostics = {
                "temporal_fact_count": len(rows),
                "current_fact_count": sum(row["status"] == "current" for row in rows),
                "history_fact_count": sum(row["status"] == "superseded" for row in rows),
                "runtime_intent": decision["plan"].intent,
                "runtime_status": decision["result"].status,
                "contract_injected": contract is not None,
                "memory_item_count": len(memory_items),
            }
            return "\n\n".join(rendered), diagnostics
    finally:
        get_settings.cache_clear()
        if old_database is None:
            os.environ.pop("CML_DATABASE_PATH", None)
        else:
            os.environ["CML_DATABASE_PATH"] = old_database
        if old_data is None:
            os.environ.pop("CML_DATA_DIR", None)
        else:
            os.environ["CML_DATA_DIR"] = old_data


def _checkpoint(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    temp.replace(path)


def _load_checkpoint(path: Path) -> dict[tuple[str, str], dict]:
    if not path.exists():
        return {}
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {(row["case_id"], row["arm"]): row for row in rows}


def _summary(rows: list[dict], reader, judge) -> dict:
    arms = {}
    for arm in ("baseline", "candidate"):
        selected = [row for row in rows if row["arm"] == arm]
        categories = defaultdict(list)
        for row in selected:
            categories[row["category"]].append(row)
        arms[arm] = {
            "count": len(selected),
            "judge_accuracy": sum(row["judge_correct"] for row in selected) / len(selected),
            "deterministic_accuracy": sum(row["deterministic_correct"] for row in selected) / len(selected),
            "mean_reader_prompt_tokens": statistics.mean(row["reader_usage"]["prompt_tokens"] for row in selected),
            "p95_reader_prompt_tokens": sorted(row["reader_usage"]["prompt_tokens"] for row in selected)[max(0, int(len(selected) * .95) - 1)],
            "categories": {
                key: {
                    "count": len(values),
                    "judge_accuracy": sum(row["judge_correct"] for row in values) / len(values),
                    "deterministic_accuracy": sum(row["deterministic_correct"] for row in values) / len(values),
                }
                for key, values in sorted(categories.items())
            },
        }
    by_case = defaultdict(dict)
    for row in rows:
        by_case[row["case_id"]][row["arm"]] = row
    paired = [value for value in by_case.values() if len(value) == 2]
    return {
        "protocol": PROTOCOL,
        "arms": arms,
        "paired_candidate_wins": sum(v["candidate"]["judge_correct"] and not v["baseline"]["judge_correct"] for v in paired),
        "paired_baseline_wins": sum(v["baseline"]["judge_correct"] and not v["candidate"]["judge_correct"] for v in paired),
        "reader_cost": _provider_cost(reader, [row["reader_usage"] for row in rows]),
        "judge_cost": _provider_cost(judge, [row["judge_usage"] for row in rows]),
    }


def main() -> None:
    args = parse_args()
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    cases = dataset["cases"][: args.limit or None]
    reader = _provider("kimi", args.reader_model)
    judge = _provider("openai", args.judge_model)
    checkpoint = args.output.with_suffix(".jsonl")
    existing = _load_checkpoint(checkpoint)
    rows = list(existing.values())
    with tempfile.TemporaryDirectory(prefix="vault-evolving-") as temp_dir:
        root = Path(temp_dir)
        for case_index, case in enumerate(cases, 1):
            for arm in ("baseline", "candidate"):
                key = (case["id"], arm)
                if key in existing:
                    continue
                context, diagnostics = (
                    _baseline_context(case, args.reader_token_budget)
                    if arm == "baseline"
                    else _candidate_context(case, root)
                )
                started = time.perf_counter()
                reader_response = _chat(reader, _reader_prompt(case["question"], context), max_tokens=160, timeout=args.timeout, retries=args.retries)
                answer = _answer(reader_response)
                reader_seconds = time.perf_counter() - started
                started = time.perf_counter()
                judge_response = _chat(judge, _judge_prompt(case, answer), max_tokens=16, timeout=args.timeout, retries=args.retries)
                verdict = _answer(judge_response).strip().casefold()
                row = {
                    "case_id": case["id"], "category": case["category"], "arm": arm,
                    "question": case["question"], "reference_answer": case["reference_answer"],
                    "answer": answer, "judge_verdict": verdict,
                    "judge_correct": verdict == "yes", "deterministic_correct": _deterministic(case, answer),
                    "reader_usage": _usage(reader_response), "judge_usage": _usage(judge_response),
                    "reader_finish_reason": _finish_reason(reader_response),
                    "judge_finish_reason": _finish_reason(judge_response),
                    "reader_wall_seconds": round(reader_seconds, 4),
                    "judge_wall_seconds": round(time.perf_counter() - started, 4),
                    "context_chars": len(context), "diagnostics": diagnostics,
                }
                existing[key] = row
                rows = list(existing.values())
                _checkpoint(checkpoint, rows)
                print(f"{case_index}/{len(cases)} {case['id']} {arm}: {verdict}", flush=True)
    ordered = [existing[(case["id"], arm)] for case in cases for arm in ("baseline", "candidate")]
    report = _summary(ordered, reader, judge)
    report["dataset_protocol"] = dataset["protocol"]
    report["case_count"] = len(cases)
    report["reader_token_budget"] = args.reader_token_budget
    report["rows_path"] = str(checkpoint)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
