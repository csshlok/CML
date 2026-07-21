from __future__ import annotations

import argparse
import os
import json
import re
import statistics
import string
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.backend.evaluate_vault_longmemeval_api import (
    SCHEMA_VERSION,
    Provider,
    _chat,
    _cohen_kappa,
    _ensure_manifest,
    _file_sha256,
    _fingerprint,
    _finish_reason,
    _parse_binary_verdict,
    _provider,
    _provider_cost,
    _usage,
    _usage_attempts,
    _wilson_interval,
)
from scripts.backend.evaluate_vault_longmemeval_local import _load_jsonl, _write_jsonl
from backend.app.core.config import get_settings
from backend.app.core.context_memory import get_context_memory, rebuild_chat_session_memory
from backend.app.core.database import connect, init_db
from backend.app.core.typed_evidence_runtime import (
    RUNTIME_ADAPTER_VERSION,
    contract_memory_item,
    evaluate_runtime_evidence,
)


READER_PROTOCOL = "locomo-official-dialog-rag-short-answer-v1"
PRODUCTION_TEMPORAL_PROTOCOL = "locomo-production-temporal-routing-v2"
JUDGE_PROTOCOL = "locomo-gold-answer-strict-binary-v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate saved Vault LOCOMO retrieval using the official short-answer "
            "reader prompt, official token-F1, and two diagnostic LLM judges."
        )
    )
    parser.add_argument("--retrieval", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--question-id",
        action="append",
        default=[],
        help="Evaluate only the named question ID; may be repeated.",
    )
    parser.add_argument("--max-answer-tokens", type=int, default=96)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--reader-model", default="kimi-k2.6")
    parser.add_argument("--primary-judge-model", default="kimi-k2.6")
    parser.add_argument("--independent-judge-model", default="gpt-5.4-2026-03-05")
    parser.add_argument(
        "--context-mode",
        choices=("retrieval-only", "production-temporal"),
        default="retrieval-only",
        help="Optionally augment retrieved turns through Vault's production memory path.",
    )
    parser.add_argument(
        "--temporal-db",
        type=Path,
        help="Persistent benchmark ledger used by --context-mode production-temporal.",
    )
    return parser.parse_args()


def _session_timestamp(value: object) -> datetime:
    return datetime.strptime(str(value), "%I:%M %p on %d %B, %Y").replace(tzinfo=UTC)


class ProductionTemporalContext:
    """Adapter from imported LoCoMo dialogue to Vault's product memory pipeline."""

    def __init__(self, *, dataset: list[dict], dataset_sha256: str, database_path: Path):
        self.database_path = database_path.resolve()
        self.manifest_path = self.database_path.with_suffix(".manifest.json")
        self.old_database = os.environ.get("CML_DATABASE_PATH")
        self.old_data = os.environ.get("CML_DATA_DIR")
        os.environ["CML_DATABASE_PATH"] = str(self.database_path)
        os.environ["CML_DATA_DIR"] = str(self.database_path.parent)
        get_settings.cache_clear()
        expected = {
            "protocol": PRODUCTION_TEMPORAL_PROTOCOL,
            "runtime_adapter_version": RUNTIME_ADAPTER_VERSION,
            "dataset_sha256": dataset_sha256,
        }
        if self.manifest_path.exists():
            if json.loads(self.manifest_path.read_text(encoding="utf-8")) != expected:
                raise RuntimeError(
                    f"Temporal ledger manifest mismatch at {self.manifest_path}; use a new --temporal-db path."
                )
            init_db()
        else:
            if self.database_path.exists():
                raise RuntimeError(
                    f"Unrecognized temporal ledger at {self.database_path}; use a new --temporal-db path."
                )
            init_db()
            self._ingest(dataset)
            self.manifest_path.write_text(json.dumps(expected, indent=2), encoding="utf-8")

    def close(self) -> None:
        get_settings.cache_clear()
        if self.old_database is None:
            os.environ.pop("CML_DATABASE_PATH", None)
        else:
            os.environ["CML_DATABASE_PATH"] = self.old_database
        if self.old_data is None:
            os.environ.pop("CML_DATA_DIR", None)
        else:
            os.environ["CML_DATA_DIR"] = self.old_data

    def _ingest(self, dataset: list[dict]) -> None:
        with connect() as conn:
            for sample in dataset:
                sample_id = str(sample["sample_id"])
                vault_id = f"locomo-{sample_id}"
                session_dates = [
                    _session_timestamp(value)
                    for key, value in sample["conversation"].items()
                    if key.endswith("_date_time")
                ]
                created_at = min(session_dates).isoformat()
                updated_at = max(session_dates).isoformat()
                conn.execute(
                    "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (vault_id, sample_id, str(self.database_path.parent), created_at, updated_at),
                )
                conversation = sample["conversation"]
                for key, turns in conversation.items():
                    if not key.startswith("session_") or key.endswith("_date_time") or not isinstance(turns, list):
                        continue
                    session_id = f"{sample_id}-{key}"
                    base_time = _session_timestamp(conversation[f"{key}_date_time"])
                    conn.execute(
                        "INSERT INTO chat_sessions (id, vault_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                        (session_id, vault_id, key, base_time.isoformat(), base_time.isoformat()),
                    )
                    for index, turn in enumerate(turns):
                        speaker = str(turn.get("speaker") or "Speaker").strip()
                        text = " ".join(str(turn.get("text") or "").split())
                        content = f'{speaker} said, "{text}"'
                        message_time = (base_time + timedelta(seconds=index)).isoformat()
                        conn.execute(
                            """INSERT INTO chat_messages
                            (id, session_id, role, content, clusters_used, citations, warnings, created_at)
                            VALUES (?, ?, 'user', ?, '[]', '[]', '[]', ?)""",
                            (f"locomo-{sample_id}-{turn['dia_id']}", session_id, content, message_time),
                        )
                    rebuild_chat_session_memory(conn, vault_id=vault_id, session_id=session_id)
            conn.commit()

    def context(self, *, sample_id: str, question: str, retrieved_context: str) -> tuple[str, dict]:
        vault_id = f"locomo-{sample_id}"
        with connect() as conn:
            memory_items, _working = get_context_memory(
                conn, vault_id=vault_id, cluster_id=None, query=question, limit=12
            )
            decision = evaluate_runtime_evidence(
                conn, vault_id=vault_id, cluster_id=None, question=question
            )
            contract = contract_memory_item(decision)
            if contract is not None:
                memory_items = [
                    contract,
                    *(item for item in memory_items if item.get("id") != contract["id"]),
                ]
            temporal_items = [
                item
                for item in memory_items
                if str(item.get("kind") or "").startswith("temporal_")
                or item.get("kind") == "typed_evidence_contract"
            ]
            fact_count = int(
                conn.execute(
                    "SELECT COUNT(*) AS count FROM temporal_facts WHERE vault_id = ? AND status != 'retracted'",
                    (vault_id,),
                ).fetchone()["count"]
            )
        # Match the app's temporal-memory packet semantics while leaving unrelated
        # non-temporal distilled-memory experiments outside this benchmark.
        additions: list[str] = []
        for item in temporal_items:
            text = str(item.get("detail_text") or item.get("summary") or "").strip()
            if text and text not in retrieved_context:
                additions.append(text)
        augmented = retrieved_context
        if additions:
            augmented += "\n\nVault structured memory:\n" + "\n\n".join(additions)
        return augmented, {
            "protocol": PRODUCTION_TEMPORAL_PROTOCOL,
            "runtime_adapter_version": RUNTIME_ADAPTER_VERSION,
            "runtime_intent": decision["plan"].intent,
            "runtime_status": decision["result"].status,
            "contract_injected": contract is not None,
            "deterministic_answer": (
                decision["result"].answer
                if decision["result"].status == "resolved"
                else None
            ),
            "temporal_fact_count": fact_count,
            "memory_item_count": len(temporal_items),
            "added_context_chars": len(augmented) - len(retrieved_context),
        }


def _conversation_turns(dataset: list[dict]) -> dict[str, dict[str, str]]:
    turns_by_sample: dict[str, dict[str, str]] = {}
    for sample in dataset:
        sample_id = str(sample["sample_id"])
        turns: dict[str, str] = {}
        conversation = sample["conversation"]
        for key, session_turns in conversation.items():
            if (
                not key.startswith("session_")
                or key.endswith("_date_time")
                or not isinstance(session_turns, list)
            ):
                continue
            date = str(conversation.get(f"{key}_date_time") or "")
            for turn in session_turns:
                content = f'{turn.get("speaker", "")} said, "{turn.get("text", "")}"'
                caption = str(turn.get("blip_caption") or "").strip()
                if caption:
                    content += f" and shared {caption}"
                turns[str(turn["dia_id"])] = f"{date}: {content}"
        turns_by_sample[sample_id] = turns
    return turns_by_sample


def _context(row: dict, turns_by_sample: dict[str, dict[str, str]]) -> tuple[str, list[str]]:
    sample_id = str(row["sample_id"])
    sample_turns = turns_by_sample[sample_id]
    blocks: list[str] = []
    included: list[str] = []
    for hit in row["retrieved"]:
        if str(hit.get("sample_id")) != sample_id:
            raise RuntimeError(
                f"Cross-conversation retrieval hit for {row['question_id']}: {hit}"
            )
        evidence_id = str(hit["evidence_id"])
        if evidence_id not in sample_turns:
            raise RuntimeError(
                f"Unknown retrieved dialog ID {evidence_id} for {row['question_id']}"
            )
        blocks.append(sample_turns[evidence_id])
        included.append(evidence_id)
    return "\n".join(blocks), included


def _answer_prompt(row: dict, context: str) -> str:
    question = str(row["question"])
    if int(row["category"]) == 2:
        question += " Use DATE of CONVERSATION to answer with an approximate date."
    return f"""{context}

Based on the above context, write an answer in the form of a short phrase for the following question. Answer with exact words from the context whenever possible.

Question: {question} Short answer:
"""


def _judge_prompt(row: dict, hypothesis: str) -> str:
    return f"""I will give you a question, a correct answer, and a response from a model. Answer yes only if the model response contains the correct answer or an equivalent answer. Answer no if it contradicts the correct answer, omits required parts, or is unsupported. Return yes or no only.

Question: {row['question']}

Correct Answer: {row['answer']}

Model Response: {hypothesis}

Is the model response correct?"""


def _stemmer():
    try:
        from nltk.stem import PorterStemmer
    except ImportError as exc:
        raise RuntimeError(
            "The official LOCOMO token-F1 requires nltk. Install it in the benchmark "
            "environment with: python -m pip install nltk"
        ) from exc
    return PorterStemmer()


def _normalize_answer(value: object) -> str:
    text = str(value).replace(",", "").lower()
    text = "".join(character for character in text if character not in string.punctuation)
    text = re.sub(r"\b(a|an|the|and)\b", " ", text)
    return " ".join(text.split())


def _official_f1_score(prediction: str, answer: str, stemmer) -> float:
    predicted = [stemmer.stem(word) for word in _normalize_answer(prediction).split()]
    gold = [stemmer.stem(word) for word in _normalize_answer(answer).split()]
    common = Counter(predicted) & Counter(gold)
    overlap = sum(common.values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(predicted)
    recall = overlap / len(gold)
    return 2 * precision * recall / (precision + recall)


def _official_locomo_score(row: dict, prediction: str, stemmer) -> float:
    category = int(row["category"])
    answer = str(row["answer"])
    if category == 3:
        answer = answer.split(";")[0].strip()
    if category == 1:
        predictions = [value.strip() for value in prediction.split(",")]
        answers = [value.strip() for value in answer.split(",")]
        return statistics.fmean(
            max(_official_f1_score(candidate, gold, stemmer) for candidate in predictions)
            for gold in answers
        )
    if category in {2, 3, 4}:
        return _official_f1_score(prediction, answer, stemmer)
    raise RuntimeError(
        "Category 5 is a separate adversarial abstention task and cannot be mixed "
        "into the standard LOCOMO QA score"
    )


def _checkpoint(path: Path, rows: dict[str, dict], selected_ids: list[str]) -> None:
    _write_jsonl(path, [rows[question_id] for question_id in selected_ids if question_id in rows])


def _generate(
    args: argparse.Namespace,
    provider: Provider,
    selected: list[dict],
    turns_by_sample: dict[str, dict[str, str]],
    path: Path,
    run_fingerprint: str,
    temporal_context: ProductionTemporalContext | None = None,
) -> list[dict]:
    selected_ids = [str(row["question_id"]) for row in selected]
    existing = {
        str(row["question_id"]): row
        for row in _load_jsonl(path)
        if row.get("run_fingerprint") == run_fingerprint
    }
    for position, item in enumerate(selected, start=1):
        question_id = str(item["question_id"])
        previous = existing.get(question_id)
        if previous and previous.get("reader_finish_reason") != "length":
            continue
        context, included = _context(item, turns_by_sample)
        temporal_diagnostics = None
        if temporal_context is not None:
            context, temporal_diagnostics = temporal_context.context(
                sample_id=str(item["sample_id"]),
                question=str(item["question"]),
                retrieved_context=context,
            )
        started = time.perf_counter()
        token_budget = (
            max(256, args.max_answer_tokens * 2)
            if previous and previous.get("reader_finish_reason") == "length"
            else args.max_answer_tokens
        )
        attempt_history = list((previous or {}).get("reader_attempt_history") or [])
        deterministic_answer = str(
            (temporal_diagnostics or {}).get("deterministic_answer") or ""
        ).strip()
        if deterministic_answer:
            hypothesis = deterministic_answer
            reader_usage = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cached_tokens": 0,
                "total_tokens": 0,
            }
            finish_reason = "deterministic"
        else:
            while True:
                response = _chat(
                    provider,
                    _answer_prompt(item, context),
                    max_tokens=token_budget,
                    timeout=args.timeout,
                    retries=args.retries,
                )
                reader_usage = _usage(response)
                finish_reason = _finish_reason(response)
                hypothesis = response["choices"][0]["message"]["content"].strip()
                attempt_history.append(
                    {
                        "max_answer_tokens": token_budget,
                        "finish_reason": finish_reason,
                        "usage": reader_usage,
                    }
                )
                if finish_reason != "length":
                    break
                if token_budget >= 768:
                    raise RuntimeError(
                        f"Reader remained length-limited at 768 tokens for {question_id}; "
                        "the benchmark report was not generated."
                    )
                token_budget = min(768, max(256, token_budget * 2))
        row = {
            "question_id": question_id,
            "sample_id": item["sample_id"],
            "category": item["category"],
            "question": item["question"],
            "answer": item["answer"],
            "hypothesis": hypothesis,
            "retrieved_evidence_ids": included,
            "context_chars": len(context),
            "reader_provider": provider.name,
            "reader_model": provider.model,
            "reader_protocol": (
                f"{READER_PROTOCOL}+{PRODUCTION_TEMPORAL_PROTOCOL}"
                if temporal_context is not None
                else READER_PROTOCOL
            ),
            "temporal_memory": temporal_diagnostics,
            "run_fingerprint": run_fingerprint,
            "max_answer_tokens": token_budget,
            "reader_attempt_count": len(attempt_history),
            "reader_attempt_history": attempt_history,
            "reader_wall_seconds": round(time.perf_counter() - started, 4),
            "reader_usage": reader_usage,
            "reader_finish_reason": finish_reason,
        }
        existing[question_id] = row
        _checkpoint(path, existing, selected_ids)
        print(f"reader {position}/{len(selected)} {question_id}", flush=True)
    completed = [existing[question_id] for question_id in selected_ids]
    length_limited = [
        row["question_id"]
        for row in completed
        if row.get("reader_finish_reason") == "length"
    ]
    if length_limited:
        raise RuntimeError(
            f"Length-limited reader outputs block report generation: {length_limited}"
        )
    return completed


def _judge(
    args: argparse.Namespace,
    provider: Provider,
    hypotheses: list[dict],
    path: Path,
    run_fingerprint: str,
) -> list[dict]:
    selected_ids = [str(row["question_id"]) for row in hypotheses]
    protocol = f"{JUDGE_PROTOCOL}-{provider.name}-{provider.model}"
    hypothesis_by_id = {str(row["question_id"]): row for row in hypotheses}
    existing = {
        str(row["question_id"]): row
        for row in _load_jsonl(path)
        if (row.get("autoeval_label") or {}).get("protocol") == protocol
        and str(row["question_id"]) in hypothesis_by_id
        and row.get("hypothesis")
        == hypothesis_by_id[str(row["question_id"])].get("hypothesis")
    }
    for position, hypothesis in enumerate(hypotheses, start=1):
        question_id = str(hypothesis["question_id"])
        if question_id in existing:
            continue
        started = time.perf_counter()
        judge_attempt_history: list[dict] = []
        for verdict_attempt in range(2):
            response = _chat(
                provider,
                _judge_prompt(hypothesis, hypothesis["hypothesis"]),
                max_tokens=10,
                timeout=args.timeout,
                retries=args.retries,
            )
            verdict = response["choices"][0]["message"]["content"].strip()
            judge_attempt_history.append(
                {
                    "raw": verdict,
                    "finish_reason": _finish_reason(response),
                    "usage": _usage(response),
                }
            )
            try:
                label = _parse_binary_verdict(verdict)
                break
            except RuntimeError:
                if verdict_attempt == 1:
                    raise
        row = {
            **hypothesis,
            "judge_run_fingerprint": run_fingerprint,
            "judge_input_fingerprint": _fingerprint(
                [protocol, question_id, hypothesis["hypothesis"]]
            ),
            "autoeval_label": {
                "provider": provider.name,
                "model": provider.model,
                "label": label,
                "raw": verdict,
                "protocol": protocol,
            },
            "judge_wall_seconds": round(time.perf_counter() - started, 4),
            "judge_usage": _usage(response),
            "judge_finish_reason": _finish_reason(response),
            "judge_attempt_count": len(judge_attempt_history),
            "judge_attempt_history": judge_attempt_history,
        }
        existing[question_id] = row
        _checkpoint(path, existing, selected_ids)
        print(f"{provider.name} judge {position}/{len(hypotheses)} {question_id}: {verdict}", flush=True)
    return [existing[question_id] for question_id in selected_ids]


def _judge_metrics(rows: list[dict]) -> dict:
    labels = [bool(row["autoeval_label"]["label"]) for row in rows]
    by_category: dict[int, list[bool]] = defaultdict(list)
    for row, label in zip(rows, labels, strict=True):
        by_category[int(row["category"])].append(label)
    return {
        "question_count": len(rows),
        "correct_count": sum(labels),
        "accuracy": round(statistics.fmean(labels), 4) if labels else None,
        "accuracy_wilson_95": _wilson_interval(sum(labels), len(labels)),
        "accuracy_by_category": {
            str(category): {
                "accuracy": round(statistics.fmean(values), 4),
                "count": len(values),
            }
            for category, values in sorted(by_category.items())
        },
        "protocol": rows[0]["autoeval_label"]["protocol"] if rows else None,
    }


def main() -> int:
    args = parse_args()
    retrieval = json.loads(args.retrieval.read_text(encoding="utf-8"))
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    if args.context_mode == "production-temporal" and args.temporal_db is None:
        raise RuntimeError("--temporal-db is required for --context-mode production-temporal")
    selected = retrieval["results"]
    if args.question_id:
        requested = set(args.question_id)
        selected = [row for row in selected if str(row["question_id"]) in requested]
        missing = requested - {str(row["question_id"]) for row in selected}
        if missing:
            raise RuntimeError(f"Unknown question IDs: {sorted(missing)}")
    selected = selected[: args.limit or None]
    if not selected:
        raise RuntimeError("The retrieval artifact contains no selected questions")
    if any(int(row["category"]) == 5 for row in selected):
        raise RuntimeError(
            "Standard LOCOMO QA input contains category 5. Rebuild retrieval with "
            "--category-scope standard; evaluate adversarial abstention separately."
        )
    if any(not str(row.get("answer") or "").strip() for row in selected):
        raise RuntimeError("Standard LOCOMO QA input contains a blank gold answer")
    selected_ids = [str(row["question_id"]) for row in selected]
    if len(selected_ids) != len(set(selected_ids)):
        raise RuntimeError("The retrieval artifact contains duplicate question IDs")

    reader = _provider("kimi", args.reader_model)
    primary_judge = _provider("kimi", args.primary_judge_model)
    independent_judge = _provider("openai", args.independent_judge_model)
    stem = args.output.with_suffix("")
    manifest = _ensure_manifest(
        stem.with_name(stem.name + ".manifest.json"),
        {
            "schema_version": SCHEMA_VERSION,
            "dataset_sha256": _file_sha256(args.dataset),
            "retrieval_sha256": _file_sha256(args.retrieval),
            "selected_question_ids": selected_ids,
            "selected_question_ids_sha256": _fingerprint(selected_ids),
            "reader_protocol": (
                f"{READER_PROTOCOL}+{PRODUCTION_TEMPORAL_PROTOCOL}"
                if args.context_mode == "production-temporal"
                else READER_PROTOCOL
            ),
            "context_mode": args.context_mode,
            "runtime_adapter_version": (
                RUNTIME_ADAPTER_VERSION
                if args.context_mode == "production-temporal"
                else None
            ),
            "judge_protocol": JUDGE_PROTOCOL,
            "reader": {"provider": reader.name, "model": reader.model},
            "primary_judge": {
                "provider": primary_judge.name,
                "model": primary_judge.model,
            },
            "independent_judge": {
                "provider": independent_judge.name,
                "model": independent_judge.model,
            },
            "max_answer_tokens": args.max_answer_tokens,
        },
    )
    run_fingerprint = manifest["fingerprint"]
    hypotheses_path = stem.with_name(stem.name + ".hypotheses.jsonl")
    primary_path = stem.with_name(stem.name + ".kimi-evaluated.jsonl")
    independent_path = stem.with_name(stem.name + ".openai-evaluated.jsonl")
    temporal_context = None
    try:
        if args.context_mode == "production-temporal":
            temporal_context = ProductionTemporalContext(
                dataset=dataset,
                dataset_sha256=manifest["dataset_sha256"],
                database_path=args.temporal_db,
            )
        hypotheses = _generate(
            args,
            reader,
            selected,
            _conversation_turns(dataset),
            hypotheses_path,
            run_fingerprint,
            temporal_context,
        )
    finally:
        if temporal_context is not None:
            temporal_context.close()
    hypotheses_sha256 = _fingerprint(
        [(row["question_id"], row["hypothesis"]) for row in hypotheses]
    )
    primary = _judge(
        args,
        primary_judge,
        hypotheses,
        primary_path,
        _fingerprint([run_fingerprint, hypotheses_sha256, primary_judge.model]),
    )
    independent = _judge(
        args,
        independent_judge,
        hypotheses,
        independent_path,
        _fingerprint([run_fingerprint, hypotheses_sha256, independent_judge.model]),
    )

    stemmer = _stemmer()
    official_scores = [
        _official_locomo_score(row, row["hypothesis"], stemmer) for row in hypotheses
    ]
    official_by_category: dict[int, list[float]] = defaultdict(list)
    for row, score in zip(hypotheses, official_scores, strict=True):
        official_by_category[int(row["category"])].append(score)
    primary_labels = [bool(row["autoeval_label"]["label"]) for row in primary]
    independent_labels = [bool(row["autoeval_label"]["label"]) for row in independent]
    agreement = [
        left == right
        for left, right in zip(primary_labels, independent_labels, strict=True)
    ]
    retrieval_scores = [
        float(row["recall_at_k"])
        for row in selected
        if row.get("recall_at_k") is not None
    ]
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run_fingerprint": run_fingerprint,
        "question_count": len(selected),
        "category_scope": "standard (categories 1-4)",
        "context_mode": args.context_mode,
        "runtime_adapter_version": (
            RUNTIME_ADAPTER_VERSION
            if args.context_mode == "production-temporal"
            else None
        ),
        "dataset_sha256": manifest["dataset_sha256"],
        "retrieval_sha256": manifest["retrieval_sha256"],
        "retrieval_macro_recall_at_k": round(statistics.fmean(retrieval_scores), 6),
        "retrieval_top_k": int((retrieval.get("protocol") or {}).get("top_k") or 10),
        "official_locomo_token_f1": round(statistics.fmean(official_scores), 4),
        "official_locomo_token_f1_by_category": {
            str(category): {
                "f1": round(statistics.fmean(scores), 4),
                "count": len(scores),
            }
            for category, scores in sorted(official_by_category.items())
        },
        "primary_judge": _judge_metrics(primary),
        "independent_judge": _judge_metrics(independent),
        "judge_agreement": round(statistics.fmean(agreement), 4),
        "judge_cohen_kappa": _cohen_kappa(primary_labels, independent_labels),
        "judge_disagreement_question_ids": [
            row["question_id"]
            for row, left, right in zip(
                hypotheses, primary_labels, independent_labels, strict=True
            )
            if left != right
        ],
        "reader_length_finish_count": sum(
            row.get("reader_finish_reason") == "length" for row in hypotheses
        ),
        "context_chars": {
            "mean": round(
                statistics.fmean(int(row["context_chars"]) for row in hypotheses), 1
            ),
            "max": max(int(row["context_chars"]) for row in hypotheses),
        },
        "temporal_memory": (
            {
                "contract_injected_count": sum(
                    bool((row.get("temporal_memory") or {}).get("contract_injected"))
                    for row in hypotheses
                ),
                "supported_runtime_count": sum(
                    (row.get("temporal_memory") or {}).get("runtime_status") != "fallback"
                    for row in hypotheses
                ),
                "mean_added_context_chars": round(
                    statistics.fmean(
                        int((row.get("temporal_memory") or {}).get("added_context_chars") or 0)
                        for row in hypotheses
                    ),
                    1,
                ),
            }
            if args.context_mode == "production-temporal"
            else None
        ),
        "comparison_note": (
            "The official token-F1 is reproducible. The binary judges are diagnostic; "
            "Graphify's unpublished atomic-key-fact files and sample manifest prevent "
            "an exact reproduction of its 45.3% judge score."
        ),
        "usage_and_estimated_cost": {
            "kimi_reader": _provider_cost(
                reader, _usage_attempts(hypotheses, kind="reader")
            ),
            "kimi_primary_judge": _provider_cost(
                primary_judge, _usage_attempts(primary, kind="judge")
            ),
            "openai_independent_judge": _provider_cost(
                independent_judge, _usage_attempts(independent, kind="judge")
            ),
        },
    }
    report["usage_and_estimated_cost"]["total_estimated_usd"] = round(
        sum(
            value["estimated_usd_at_uncached_rate"]
            for value in report["usage_and_estimated_cost"].values()
            if isinstance(value, dict)
        ),
        6,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
