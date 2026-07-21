from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.atomic_memory import (  # noqa: E402
    ATOMIC_EXTRACTION_RESPONSE_SCHEMA,
    compile_deterministic_atomic_session,
    compile_semantic_atomic_session,
    deduplicate_atomic_facts,
    pack_atomic_facts,
    plan_atomic_query,
    validate_atomic_contract,
)
from backend.app.core.llm_runtime import generate_local_structured_json  # noqa: E402
from scripts.backend.run_longmemeval_atomic_ablation import (  # noqa: E402
    _load_inputs,
    _session_rows,
)


SYSTEM_PROMPT = (
    "Extract durable conversational memory as one strict JSON object. "
    "Do not think aloud. Preserve exact citations, speaker attribution, modality, "
    "named entities, general entity categories, and coreference only when supported "
    "by the supplied conversation."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe local GPU write-time semantic extraction on one frozen question."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path(".tmp/vault-odin-memory-benchmark"),
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=Path(".tmp/vault-odin-memory-benchmark/atomic-memory-v1"),
    )
    parser.add_argument("--question-id", required=True)
    parser.add_argument(
        "--session-scope",
        choices=("answer", "retrieved"),
        default="answer",
    )
    parser.add_argument("--token-budget", type=int, default=9_000)
    parser.add_argument("--show-model-output", action="store_true")
    parser.add_argument("--roles", choices=("user", "all"), default="user")
    return parser.parse_args()


def _fact_summary(fact) -> dict:
    return {
        "fact_id": fact.fact_id,
        "session_id": fact.citation.session_id,
        "turn_index": fact.citation.turn_index,
        "speaker": fact.citation.speaker,
        "subject": fact.subject,
        "predicate": fact.predicate,
        "object_text": fact.object_text,
        "fact_kind": fact.fact_kind,
        "assertion_mode": fact.assertion_mode,
        "event_date": fact.event_date,
        "qualifiers": fact.qualifiers,
        "citation_excerpt": fact.citation.excerpt,
    }


def main() -> None:
    args = parse_args()
    _, references, _ = _load_inputs(args.artifact_dir)
    reference = references[args.question_id]
    session_ids = (
        reference["answer_session_ids"]
        if args.session_scope == "answer"
        else next(
            item["retrieved_session_ids"]
            for item in json.loads(
                (args.run_dir / "manifest.json").read_text(encoding="utf-8")
            )["questions"]
            if item["question_id"] == args.question_id
        )
    )
    sessions = _session_rows(reference, session_ids)
    semantic_facts = []
    deterministic_facts = []
    invalid_reasons: dict[str, int] = {}
    session_results: list[dict] = []

    for position, session in enumerate(sessions, start=1):
        deterministic_facts.extend(
            compile_deterministic_atomic_session(session).facts
        )

        def extractor(prompt: str) -> tuple[str, dict]:
            result = generate_local_structured_json(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=prompt,
                json_schema=ATOMIC_EXTRACTION_RESPONSE_SCHEMA,
            )
            if args.show_model_output:
                print(f"model-output={result.text[:500]!r}", flush=True)
            return result.text, {}

        started = time.perf_counter()
        extraction, rejected, _ = compile_semantic_atomic_session(
            session,
            extractor=extractor,
            included_roles={"user"} if args.roles == "user" else None,
        )
        elapsed = time.perf_counter() - started
        semantic_facts.extend(extraction.facts)
        for reason, count in rejected.items():
            invalid_reasons[reason] = invalid_reasons.get(reason, 0) + count
        session_results.append(
            {
                "session_id": session["session_id"],
                "wall_seconds": round(elapsed, 3),
                "semantic_fact_count": len(extraction.facts),
                "invalid_reasons": rejected,
            }
        )
        print(
            f"extracted {position}/{len(sessions)}: {session['session_id']} "
            f"facts={len(extraction.facts)} invalid={sum(rejected.values())} "
            f"seconds={elapsed:.2f}",
            flush=True,
        )

    combined, duplicate_count = deduplicate_atomic_facts(
        [*deterministic_facts, *semantic_facts]
    )
    plan = plan_atomic_query(reference["question"])

    def assess(facts: list) -> dict:
        _, packing = pack_atomic_facts(
            reference["question"],
            facts,
            session_ids,
            token_budget=args.token_budget,
            plan=plan,
        )
        contract = validate_atomic_contract(
            plan,
            facts,
            packing["satisfied_fact_ids"],
            packing,
        )
        return {
            "fact_count": len(facts),
            "packed_fact_count": packing["selected_fact_count"],
            "packed_tokens_estimate": packing["packed_tokens_estimate"],
            "contract_safe": contract.safe,
            "contract_missing_slots": contract.missing_slots,
            "contract_operand_fact_ids": contract.operand_fact_ids,
        }

    category_facts = [
        fact
        for fact in semantic_facts
        if fact.qualifiers.get("entity_category")
    ]
    report = {
        "protocol": "local-semantic-ingestion-pilot-v1",
        "question_id": args.question_id,
        "question_type": reference["question_type"],
        "question": reference["question"],
        "reference_answer": reference["answer"],
        "session_scope": args.session_scope,
        "roles": args.roles,
        "session_ids": session_ids,
        "session_results": session_results,
        "semantic_fact_count": len(semantic_facts),
        "semantic_invalid_fact_count": sum(invalid_reasons.values()),
        "semantic_invalid_reasons": invalid_reasons,
        "semantic_category_fact_count": len(category_facts),
        "semantic_category_facts": [_fact_summary(fact) for fact in category_facts],
        "semantic_facts": [_fact_summary(fact) for fact in semantic_facts],
        "deduplicated_fact_count": len(combined),
        "deduplicated_count": duplicate_count,
        "query_plan": plan.model_dump(mode="json"),
        "deterministic_only": assess(deterministic_facts),
        "deterministic_plus_semantic": assess(combined),
    }
    args.run_dir.mkdir(parents=True, exist_ok=True)
    output = args.run_dir / f"local-semantic-pilot-{args.question_id}.json"
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({**report, "semantic_facts": "omitted"}, indent=2))
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
