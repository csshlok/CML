from __future__ import annotations

# DEAD EXPERIMENT (2026-08-03): retained only for audit/reproduction. With the
# fixed retriever and local Qwen, raw context scored 0.40, facts-only 0.00, and
# hybrid 0.20. Do not use this path in production or as a supported benchmark.

import argparse
import hashlib
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.atomic_memory import (  # noqa: E402
    AtomicCitation,
    AtomicFact,
    AtomicSessionExtraction,
    load_atomic_session_cache,
    pack_atomic_facts,
    source_content_hash,
    store_atomic_session_cache,
)
from backend.app.core.claim_evidence_packing import (  # noqa: E402
    SessionEnvelope,
    pack_claim_evidence,
)
from scripts.backend.benchmark_reader_evidence_local import (  # noqa: E402
    _normalized_contains,
    _token_f1,
)
from scripts.backend.evaluate_vault_longmemeval_local import (  # noqa: E402
    _judge_prompt,
    _routed_answer_prompt,
)


PROTOCOL = "vault-local-mem0-style-fact-ab-v1"
ARMS = ("raw", "facts-only", "hybrid")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare the existing RAG reader with question-independent local-Qwen "
            "fact extraction over exactly the same retrieved LongMemEval sessions."
        )
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--retrieval", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8084/v1")
    parser.add_argument("--model", default="cml-local")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--raw-token-budget", type=int, default=3_400)
    parser.add_argument("--fact-token-budget", type=int, default=3_400)
    parser.add_argument("--hybrid-fact-token-budget", type=int, default=1_400)
    parser.add_argument("--hybrid-raw-token-budget", type=int, default=2_000)
    parser.add_argument("--extraction-max-source-chars", type=int, default=8_000)
    parser.add_argument("--extraction-max-facts", type=int, default=8)
    parser.add_argument("--extraction-max-tokens", type=int, default=2_048)
    parser.add_argument(
        "--retrieved-session-limit",
        type=int,
        default=5,
        help="Use the same top-N retrieved sessions for every arm; zero keeps all.",
    )
    parser.add_argument("--answer-max-tokens", type=int, default=256)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _post_chat(
    base_url: str,
    model: str,
    prompt: str,
    *,
    max_tokens: int,
    timeout: float,
    json_mode: bool = False,
) -> tuple[str, dict]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if json_mode:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "memory_facts",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "facts": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "turn_index": {"type": "integer"},
                                    "fact": {"type": "string"},
                                    "excerpt": {"type": "string"},
                                    "kind": {
                                        "type": "string",
                                        "enum": [
                                            "identity",
                                            "attribute",
                                            "event",
                                            "state",
                                            "preference",
                                            "plan",
                                            "relationship",
                                            "recommendation",
                                            "list_item",
                                            "quantity",
                                            "other",
                                        ],
                                    },
                                },
                                "required": ["turn_index", "fact", "excerpt", "kind"],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["facts"],
                    "additionalProperties": False,
                },
            },
        }
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload["choices"][0]["message"]["content"].strip(), payload.get(
        "usage"
    ) or {}


def _session_rows(reference: dict, session_ids: list[str]) -> list[dict]:
    wanted = {str(value) for value in session_ids}
    rows = []
    for session_id, date, turns in zip(
        reference["haystack_session_ids"],
        reference["haystack_dates"],
        reference["haystack_sessions"],
        strict=True,
    ):
        if str(session_id) in wanted:
            rows.append(
                {"session_id": str(session_id), "date": str(date), "turns": turns}
            )
    ranks = {str(value): rank for rank, value in enumerate(session_ids)}
    rows.sort(key=lambda row: ranks.get(row["session_id"], len(ranks)))
    return rows


def _raw_context(
    reference: dict, session_ids: list[str], token_budget: int
) -> tuple[str, dict]:
    sessions = [
        SessionEnvelope(
            session_id=row["session_id"],
            date=row["date"],
            turns=row["turns"],
            retrieval_rank=rank,
        )
        for rank, row in enumerate(_session_rows(reference, session_ids))
    ]
    return pack_claim_evidence(
        question=reference["question"],
        sessions=sessions,
        token_budget=token_budget,
        question_type=str(reference.get("question_type") or ""),
        consolidate=False,
        presentation="legacy",
    )


def build_arm_contexts(
    reference: dict,
    session_ids: list[str],
    facts: list,
    *,
    raw_token_budget: int,
    fact_token_budget: int,
    hybrid_fact_token_budget: int,
    hybrid_raw_token_budget: int,
) -> dict[str, tuple[str, dict]]:
    raw_context, raw_metadata = _raw_context(reference, session_ids, raw_token_budget)
    fact_context, fact_metadata = pack_atomic_facts(
        reference["question"], facts, session_ids, token_budget=fact_token_budget
    )
    hybrid_facts, hybrid_fact_metadata = pack_atomic_facts(
        reference["question"], facts, session_ids, token_budget=hybrid_fact_token_budget
    )
    hybrid_raw, hybrid_raw_metadata = _raw_context(
        reference, session_ids, hybrid_raw_token_budget
    )
    return {
        "raw": (raw_context, raw_metadata),
        "facts-only": (fact_context, fact_metadata),
        "hybrid": (
            "EXTRACTED FACTS (each fact retains its source):\n"
            + hybrid_facts
            + "\n\nORIGINAL RETRIEVED EVIDENCE:\n"
            + hybrid_raw,
            {"fact": hybrid_fact_metadata, "raw": hybrid_raw_metadata},
        ),
    }


def _fingerprint(*values: object) -> str:
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _compact_chunks(session: dict, max_chars: int) -> list[list[dict]]:
    chunks: list[list[dict]] = []
    pending: list[dict] = []
    used = 0
    for turn_index, turn in enumerate(session["turns"]):
        content = str(turn.get("content") or "")
        fragments = [
            content[start : start + max_chars]
            for start in range(0, len(content), max_chars)
        ] or [""]
        for fragment in fragments:
            if pending and used + len(fragment) > max_chars:
                chunks.append(pending)
                pending = []
                used = 0
            pending.append(
                {
                    "turn_index": turn_index,
                    "role": str(turn.get("role") or "user"),
                    "content": fragment,
                }
            )
            used += len(fragment)
    if pending:
        chunks.append(pending)
    return chunks


def _compact_prompt(session: dict, turns: list[dict], max_facts: int) -> str:
    return f"""Extract durable memory facts from this conversation chunk.

This happens before any future question is known. Return JSON only:
{{"facts":[{{"turn_index":0,"fact":"The user prefers tea","excerpt":"I prefer tea","kind":"preference"}}]}}

Rules:
- Return at most {max_facts} useful concrete facts. Skip greetings and generic filler.
- Preserve preferences, personal details, events, decisions, plans, constraints, quantities, named entities, and meaningful assistant recommendations.
- Split unrelated facts. Do not invent or infer unsupported details.
- turn_index must match the supplied zero-based original turn index.
- excerpt must be a short exact contiguous quotation from that turn that proves the fact.
- kind is one of identity, attribute, event, state, preference, plan, relationship, recommendation, list_item, quantity, other.

Session ID: {session["session_id"]}
Session date: {session["date"]}
Turns:
{json.dumps(turns, ensure_ascii=False)}
"""


def compile_compact_session(
    args: argparse.Namespace, session: dict
) -> tuple[AtomicSessionExtraction, Counter, Counter]:
    valid_kinds = {
        "identity",
        "attribute",
        "event",
        "state",
        "preference",
        "plan",
        "relationship",
        "recommendation",
        "list_item",
        "quantity",
        "other",
    }
    digest = source_content_hash(
        session["session_id"], session["date"], session["turns"]
    )
    facts: list[AtomicFact] = []
    invalid: Counter = Counter()
    usage: Counter = Counter()
    for chunk_index, turns in enumerate(
        _compact_chunks(session, args.extraction_max_source_chars)
    ):
        response, response_usage = _post_chat(
            args.base_url,
            args.model,
            _compact_prompt(session, turns, args.extraction_max_facts),
            max_tokens=args.extraction_max_tokens,
            timeout=args.timeout,
            json_mode=True,
        )
        usage.update(
            {
                key: int(value)
                for key, value in response_usage.items()
                if isinstance(value, (int, float))
            }
        )
        try:
            payload = json.loads(response)
        except json.JSONDecodeError as exc:
            raise ValueError("compact_extractor_invalid_json") from exc
        for fact_index, raw in enumerate(payload.get("facts") or []):
            if not isinstance(raw, dict):
                invalid["malformed_fact"] += 1
                continue
            try:
                turn_index = int(raw["turn_index"])
                source_turn = session["turns"][turn_index]
                excerpt = str(raw["excerpt"]).strip()
                fact_text = str(raw["fact"]).strip()
            except (KeyError, TypeError, ValueError, IndexError):
                invalid["invalid_fields"] += 1
                continue
            if (
                not excerpt
                or len(excerpt) > 1_200
                or excerpt not in str(source_turn.get("content") or "")
            ):
                invalid["excerpt_not_exact"] += 1
                continue
            if not fact_text:
                invalid["empty_fact"] += 1
                continue
            kind = str(raw.get("kind") or "other")
            if kind not in valid_kinds:
                kind = "other"
            speaker = str(source_turn.get("role") or "user")
            if speaker not in {"user", "assistant", "tool"}:
                speaker = "user"
            facts.append(
                AtomicFact(
                    fact_id=f"compact-{session['session_id']}-c{chunk_index}-f{fact_index}",
                    citation=AtomicCitation(
                        session_id=session["session_id"],
                        turn_index=turn_index,
                        speaker=speaker,
                        session_date=session["date"],
                        excerpt=excerpt,
                        source_content_hash=digest,
                    ),
                    subject="user" if speaker == "user" else speaker,
                    predicate="remembered_fact",
                    object_text=fact_text,
                    fact_kind=kind,
                    observed_date=session["date"],
                    confidence=0.9,
                )
            )
    deduplicated: dict[tuple[int, str], AtomicFact] = {}
    for fact in facts:
        deduplicated[(fact.citation.turn_index, fact.object_text.casefold())] = fact
    return (
        AtomicSessionExtraction(
            session_id=session["session_id"], facts=list(deduplicated.values())
        ),
        invalid,
        usage,
    )


def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _extract_all(
    args: argparse.Namespace, selected: list[dict], references: dict[str, dict]
) -> tuple[dict[str, list], dict]:
    cache_dir = args.cache_dir or args.output.parent / "fact-cache"
    cache_model = (
        f"{args.model}-mem0-style-v1-f{args.extraction_max_facts}"
        f"-c{args.extraction_max_source_chars}"
    )
    unique: dict[str, dict] = {}
    question_sessions: dict[str, list[dict]] = {}
    for retrieval in selected:
        reference = references[retrieval["question_id"]]
        retrieved_ids = retrieval["retrieved_session_ids"][
            : args.retrieved_session_limit or None
        ]
        sessions = _session_rows(reference, retrieved_ids)
        question_sessions[retrieval["question_id"]] = sessions
        for session in sessions:
            digest = source_content_hash(
                session["session_id"], session["date"], session["turns"]
            )
            unique[digest] = session

    extraction_rows = []
    for position, session in enumerate(unique.values(), start=1):
        cached = load_atomic_session_cache(
            cache_dir=cache_dir, model=cache_model, session=session
        )
        if cached is not None and not args.force:
            extraction_rows.append(
                {
                    "session_id": session["session_id"],
                    "cache_hit": True,
                    "fact_count": len(cached.facts),
                    "invalid_fact_count": 0,
                    "wall_seconds": 0.0,
                }
            )
            continue
        started = time.perf_counter()

        extraction, invalid, usage = compile_compact_session(args, session)
        store_atomic_session_cache(
            extraction, cache_dir=cache_dir, model=cache_model, session=session
        )
        row = {
            "session_id": session["session_id"],
            "cache_hit": False,
            "fact_count": len(extraction.facts),
            "invalid_fact_count": sum(invalid.values()),
            "invalid_reasons": invalid,
            "usage": usage,
            "wall_seconds": round(time.perf_counter() - started, 4),
        }
        extraction_rows.append(row)
        print(
            f"extracted {position}/{len(unique)} {session['session_id']} ({len(extraction.facts)} facts)",
            flush=True,
        )

    facts_by_question: dict[str, list] = {}
    for question_id, sessions in question_sessions.items():
        facts_by_question[question_id] = [
            fact
            for session in sessions
            for fact in (
                load_atomic_session_cache(
                    cache_dir=cache_dir, model=cache_model, session=session
                ).facts
            )
        ]
    return facts_by_question, {
        "unique_session_count": len(unique),
        "cache_hit_count": sum(bool(row["cache_hit"]) for row in extraction_rows),
        "fact_count": sum(int(row["fact_count"]) for row in extraction_rows),
        "invalid_fact_count": sum(
            int(row["invalid_fact_count"]) for row in extraction_rows
        ),
        "invalid_fact_rate": round(
            sum(int(row["invalid_fact_count"]) for row in extraction_rows)
            / max(
                1,
                sum(int(row["fact_count"]) for row in extraction_rows)
                + sum(int(row["invalid_fact_count"]) for row in extraction_rows),
            ),
            6,
        ),
        "invalid_reasons": dict(
            sum(
                (Counter(row.get("invalid_reasons") or {}) for row in extraction_rows),
                Counter(),
            )
        ),
        "wall_seconds": round(
            sum(float(row["wall_seconds"]) for row in extraction_rows), 4
        ),
        "accepted_fact_citation_validity": 1.0,
    }


def _metrics(rows: list[dict]) -> dict:
    by_arm: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_arm[row["arm"]].append(row)
    output = {}
    for arm, arm_rows in by_arm.items():
        output[arm] = {
            "question_count": len(arm_rows),
            "correct_count": sum(bool(row["judge_label"]) for row in arm_rows),
            "accuracy": round(
                statistics.fmean(bool(row["judge_label"]) for row in arm_rows), 6
            ),
            "mean_token_f1": round(
                statistics.fmean(float(row["token_f1"]) for row in arm_rows), 6
            ),
            "gold_containment_rate": round(
                statistics.fmean(bool(row["gold_contained"]) for row in arm_rows), 6
            ),
            "mean_reader_seconds": round(
                statistics.fmean(float(row["reader_wall_seconds"]) for row in arm_rows),
                4,
            ),
        }
    baseline = {
        row["question_id"]: bool(row["judge_label"]) for row in by_arm.get("raw", [])
    }
    for arm in ("facts-only", "hybrid"):
        if arm not in by_arm:
            continue
        output[arm]["wins_vs_raw"] = sum(
            bool(row["judge_label"]) and not baseline[row["question_id"]]
            for row in by_arm[arm]
        )
        output[arm]["losses_vs_raw"] = sum(
            not bool(row["judge_label"]) and baseline[row["question_id"]]
            for row in by_arm[arm]
        )
    return output


def main() -> int:
    args = parse_args()
    prior_report = (
        json.loads(args.output.read_text(encoding="utf-8"))
        if args.output.exists() and not args.force
        else None
    )
    dataset_bytes = args.dataset.read_bytes()
    dataset = json.loads(dataset_bytes)
    references = {str(row["question_id"]): row for row in dataset}
    retrieval_report = json.loads(args.retrieval.read_text(encoding="utf-8"))
    selected = retrieval_report["results"][: args.limit or None]
    missing = [
        row["question_id"] for row in selected if row["question_id"] not in references
    ]
    if missing:
        raise RuntimeError(
            f"Retrieval report contains unknown questions: {missing[:3]}"
        )

    facts_by_question, extraction = _extract_all(args, selected, references)
    prior_extraction = (prior_report or {}).get("extraction") or {}
    if (
        extraction["cache_hit_count"] == extraction["unique_session_count"]
        and prior_extraction.get("unique_session_count")
        == extraction["unique_session_count"]
    ):
        extraction["invalid_fact_count"] = int(
            prior_extraction.get("invalid_fact_count") or 0
        )
        extraction["invalid_fact_rate"] = round(
            extraction["invalid_fact_count"]
            / max(1, extraction["fact_count"] + extraction["invalid_fact_count"]),
            6,
        )
        extraction["invalid_reasons"] = prior_extraction.get("invalid_reasons") or {}
        extraction["quality_metrics_reused_from_prior_report"] = True
    rows_path = args.output.with_suffix(".rows.jsonl")
    existing = (
        {}
        if args.force
        else {
            (row["question_id"], row["arm"], row.get("fingerprint")): row
            for row in _load_jsonl(rows_path)
        }
    )
    completed_rows = []
    for position, retrieval in enumerate(selected, start=1):
        question_id = retrieval["question_id"]
        reference = references[question_id]
        session_ids = [
            str(value)
            for value in retrieval["retrieved_session_ids"][
                : args.retrieved_session_limit or None
            ]
        ]
        gold_ids = {str(value) for value in reference.get("answer_session_ids") or []}
        actual_recall = (
            len(gold_ids & set(session_ids)) / len(gold_ids) if gold_ids else None
        )
        contexts = build_arm_contexts(
            reference,
            session_ids,
            facts_by_question[question_id],
            raw_token_budget=args.raw_token_budget,
            fact_token_budget=args.fact_token_budget,
            hybrid_fact_token_budget=args.hybrid_fact_token_budget,
            hybrid_raw_token_budget=args.hybrid_raw_token_budget,
        )
        for arm in ARMS:
            context, metadata = contexts[arm]
            fingerprint = _fingerprint(
                PROTOCOL, question_id, arm, session_ids, context, args.model
            )
            cached = existing.get((question_id, arm, fingerprint))
            if cached is not None:
                completed_rows.append(cached)
                continue
            started = time.perf_counter()
            answer, answer_usage = _post_chat(
                args.base_url,
                args.model,
                _routed_answer_prompt(reference, context),
                max_tokens=args.answer_max_tokens,
                timeout=args.timeout,
            )
            reader_seconds = time.perf_counter() - started
            verdict, judge_usage = _post_chat(
                args.base_url,
                args.model,
                _judge_prompt(reference, answer),
                max_tokens=12,
                timeout=args.timeout,
            )
            row = {
                "question_id": question_id,
                "question_type": reference.get("question_type"),
                "arm": arm,
                "answer": answer,
                "judge_label": verdict.casefold().startswith("yes"),
                "judge_raw": verdict,
                "token_f1": round(
                    _token_f1(str(reference.get("answer") or ""), answer), 6
                ),
                "gold_contained": _normalized_contains(
                    str(reference.get("answer") or ""), answer
                ),
                "retrieved_session_ids": session_ids,
                "retrieval_recall_at_k": actual_recall,
                "context_metadata": metadata,
                "reader_usage": answer_usage,
                "judge_usage": judge_usage,
                "reader_wall_seconds": round(reader_seconds, 4),
                "fingerprint": fingerprint,
            }
            _append_jsonl(rows_path, row)
            completed_rows.append(row)
            print(
                f"answered {position}/{len(selected)} {question_id} {arm}: {verdict}",
                flush=True,
            )

    report = {
        "schema_version": 1,
        "protocol": PROTOCOL,
        "limitations": [
            "Local Qwen is both reader and judge; accuracy is a directional proxy, not the official headline score.",
            "Extraction is question-independent but restricted to sessions selected by the fixed retriever for this reader ablation.",
        ],
        "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
        "retrieval_protocol": retrieval_report.get("protocol"),
        "reader_retrieved_session_limit": args.retrieved_session_limit,
        "question_ids": [row["question_id"] for row in selected],
        "retrieval_summary": retrieval_report.get("summary"),
        "extraction": extraction,
        "summary": _metrics(completed_rows),
        "rows": completed_rows,
    }
    actual_recall = [
        float(row["retrieval_recall_at_k"])
        for row in completed_rows
        if row["arm"] == "raw" and row["retrieval_recall_at_k"] is not None
    ]
    report["reader_retrieval_summary"] = {
        "question_count": len(actual_recall),
        "macro_recall_at_reader_k": round(statistics.fmean(actual_recall), 6)
        if actual_recall
        else None,
        "all_gold_sessions_retrieved_rate": round(
            statistics.fmean(value == 1.0 for value in actual_recall), 6
        )
        if actual_recall
        else None,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "summary": report["summary"],
                "extraction": extraction,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(
        "DEAD EXPERIMENT: Qwen fact extraction reduced accuracy versus raw RAG"
    )
    # raise SystemExit(main())  # Intentionally disabled; audit code only.
