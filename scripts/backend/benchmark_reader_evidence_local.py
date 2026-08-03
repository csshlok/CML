from __future__ import annotations

# DEAD EXPERIMENT (2026-08-03): retained only for audit/reproduction. The
# candidate regressed local proxy accuracy from 0.64 to 0.62, then 0.50 to
# 0.44 on the disjoint v2 selection. Do not reactivate without a new design
# and a new preregistered holdout.

import argparse
import hashlib
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PROTOCOL = "vault-reader-evidence-local-ab-v2"
DEFAULT_SEED = "vault-reader-evidence-2026-08-02"
STRATA = ("numeric", "temporal", "preference", "knowledge-update", "multi-session")
NUMERIC_RE = re.compile(
    r"\b(how many|how much|how often|how long|total|combined|sum|times|days|weeks|months|years)\b",
    re.IGNORECASE,
)
TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a frozen, no-cost local A/B evaluation of legacy versus reader-evidence "
            "claim presentation on official LongMemEval oracle sessions."
        )
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8084/v1")
    parser.add_argument("--model", default="cml-local")
    parser.add_argument("--per-stratum", type=int, default=10)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument("--reader-token-budget", type=int, default=3_400)
    parser.add_argument("--max-answer-tokens", type=int, default=192)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--exclude-report",
        type=Path,
        help="Exclude every question ID selected by a previous report.",
    )
    parser.add_argument(
        "--selection-manifest",
        type=Path,
        help="Use an immutable list of question IDs and strata instead of selecting again.",
    )
    parser.add_argument(
        "--selection-only",
        action="store_true",
        help="Freeze and print the selected IDs without calling the model.",
    )
    return parser.parse_args()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _fingerprint(parts: list[object]) -> str:
    payload = json.dumps(
        parts, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return _sha256_bytes(payload.encode("utf-8"))


def _eligible(reference: dict, stratum: str) -> bool:
    question_id = str(reference.get("question_id") or "")
    if question_id.endswith("_abs") or not reference.get("answer_session_ids"):
        return False
    question_type = str(reference.get("question_type") or "")
    question = str(reference.get("question") or "")
    if stratum == "numeric":
        return bool(NUMERIC_RE.search(question))
    if stratum == "temporal":
        return question_type == "temporal-reasoning"
    if stratum == "preference":
        return question_type == "single-session-preference"
    return question_type == stratum


def select_references(
    dataset: list[dict],
    *,
    per_stratum: int,
    seed: str,
    excluded_ids: set[str] | None = None,
) -> list[dict]:
    used: set[str] = set(excluded_ids or ())
    selected: list[dict] = []
    for stratum in STRATA:
        candidates = [
            row
            for row in dataset
            if str(row.get("question_id") or "") not in used and _eligible(row, stratum)
        ]
        candidates.sort(
            key=lambda row: _fingerprint(
                [seed, stratum, str(row.get("question_id") or "")]
            )
        )
        chosen = candidates[:per_stratum]
        if len(chosen) != per_stratum:
            raise RuntimeError(
                f"Stratum {stratum!r} has only {len(chosen)} eligible unique cases; "
                f"{per_stratum} were requested."
            )
        for row in chosen:
            copied = dict(row)
            copied["evaluation_stratum"] = stratum
            selected.append(copied)
            used.add(str(row["question_id"]))
    return selected


def select_from_manifest(
    dataset: list[dict],
    *,
    manifest: dict,
    dataset_hash: str,
) -> list[dict]:
    expected_hash = str(manifest.get("dataset_sha256") or "")
    if expected_hash != dataset_hash:
        raise RuntimeError(
            f"Selection manifest expects dataset {expected_hash}, received {dataset_hash}."
        )
    by_id = {str(row.get("question_id") or ""): row for row in dataset}
    selected: list[dict] = []
    seen: set[str] = set()
    for item in manifest.get("items") or []:
        question_id = str(item.get("question_id") or "")
        stratum = str(item.get("stratum") or "")
        if question_id in seen or question_id not in by_id or stratum not in STRATA:
            raise RuntimeError(f"Invalid frozen selection item: {item!r}")
        copied = dict(by_id[question_id])
        copied["evaluation_stratum"] = stratum
        selected.append(copied)
        seen.add(question_id)
    if not selected:
        raise RuntimeError("Selection manifest contains no cases.")
    return selected


def _sessions(reference: dict):
    from backend.app.core.claim_evidence_packing import SessionEnvelope

    return [
        SessionEnvelope(
            session_id=str(session_id),
            date=str(date),
            turns=list(turns),
            retrieval_rank=rank,
        )
        for rank, (session_id, date, turns) in enumerate(
            zip(
                reference["haystack_session_ids"],
                reference["haystack_dates"],
                reference["haystack_sessions"],
                strict=True,
            )
        )
    ]


def _reader_prompt(
    reference: dict, *, presentation: str, token_budget: int
) -> tuple[str, dict]:
    from backend.app.core.claim_evidence_packing import (
        estimate_claim_tokens,
        pack_claim_evidence,
    )
    from scripts.backend.evaluate_vault_longmemeval_local import _routed_answer_prompt

    empty_prompt = _routed_answer_prompt(reference, "")
    overhead = estimate_claim_tokens(empty_prompt)
    evidence_budget = max(256, token_budget - overhead - 48)
    context, metadata = pack_claim_evidence(
        question=str(reference["question"]),
        sessions=_sessions(reference),
        token_budget=evidence_budget,
        question_type=str(reference.get("question_type") or ""),
        consolidate=True,
        presentation=presentation,
    )
    prompt = _routed_answer_prompt(reference, context)
    metadata = {
        **metadata,
        "prompt_tokens_estimate": estimate_claim_tokens(prompt),
        "prompt_overhead_tokens_estimate": overhead,
        "evidence_token_budget": evidence_budget,
    }
    return prompt, metadata


def _post_chat(
    *,
    base_url: str,
    model: str,
    prompt: str,
    max_tokens: int,
    timeout: float,
) -> str:
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
    ).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Local reader request failed: {exc}") from exc
    try:
        answer = str(result["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Local reader returned an unexpected response.") from exc
    if not answer:
        raise RuntimeError("Local reader returned an empty answer.")
    return answer


def _judge_prompt(reference: dict, answer: str) -> str:
    return f"""Judge whether the candidate answer satisfies the reference answer for the question.

Rules:
- Accept equivalent wording.
- For lists or compound questions, reject an answer missing a required component.
- For counts, dates, durations, comparisons, or updated facts, require the correct value.
- For preference questions, accept a concise answer that correctly applies the reference personal information.
- Ignore style differences and extra harmless explanation.
- Return exactly YES or NO and nothing else.

Question: {reference["question"]}
Reference answer or rubric: {reference["answer"]}
Candidate answer: {answer}

Verdict:"""


def _judge(
    *,
    base_url: str,
    model: str,
    reference: dict,
    answer: str,
    timeout: float,
) -> bool:
    verdict = _post_chat(
        base_url=base_url,
        model=model,
        prompt=_judge_prompt(reference, answer),
        max_tokens=8,
        timeout=timeout,
    )
    normalized = verdict.strip().casefold()
    if normalized.startswith("yes"):
        return True
    if normalized.startswith("no"):
        return False
    raise RuntimeError(f"Local judge returned an invalid verdict: {verdict!r}")


def _token_f1(reference: str, answer: str) -> float:
    expected = TOKEN_RE.findall(reference.casefold())
    actual = TOKEN_RE.findall(answer.casefold())
    if not expected or not actual:
        return float(expected == actual)
    overlap = sum((Counter(expected) & Counter(actual)).values())
    precision = overlap / len(actual)
    recall = overlap / len(expected)
    return (
        0.0
        if precision + recall == 0
        else 2 * precision * recall / (precision + recall)
    )


def _normalized_contains(reference: str, answer: str) -> bool:
    expected = " ".join(TOKEN_RE.findall(reference.casefold()))
    actual = " ".join(TOKEN_RE.findall(answer.casefold()))
    return bool(expected and expected in actual)


def _metrics(rows: list[dict], presentation: str) -> dict:
    judged = [bool(row[presentation]["accepted"]) for row in rows]
    return {
        "question_count": len(rows),
        "accepted_count": sum(judged),
        "local_proxy_accuracy": round(sum(judged) / len(rows), 6) if rows else 0.0,
        "mean_token_f1": round(
            sum(float(row[presentation]["token_f1"]) for row in rows) / len(rows), 6
        )
        if rows
        else 0.0,
        "reference_containment_rate": round(
            sum(bool(row[presentation]["reference_contained"]) for row in rows)
            / len(rows),
            6,
        )
        if rows
        else 0.0,
        "mean_prompt_tokens_estimate": round(
            sum(
                int(row[presentation]["packing"]["prompt_tokens_estimate"])
                for row in rows
            )
            / len(rows),
            2,
        )
        if rows
        else 0.0,
    }


def _report(
    *,
    args: argparse.Namespace,
    dataset_hash: str,
    selected: list[dict],
    rows: list[dict],
) -> dict:
    by_stratum: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_stratum[str(row["stratum"])].append(row)
    gains = sum(
        not row["legacy"]["accepted"] and row["reader_evidence"]["accepted"]
        for row in rows
    )
    losses = sum(
        row["legacy"]["accepted"] and not row["reader_evidence"]["accepted"]
        for row in rows
    )
    changed_answers = sum(
        row["legacy"]["answer"].strip() != row["reader_evidence"]["answer"].strip()
        for row in rows
    )
    return {
        "protocol": PROTOCOL,
        "scope": "local_directional_proxy_not_release_accuracy",
        "dataset": {
            "path": str(args.dataset.resolve()),
            "sha256": dataset_hash,
            "source": "xiaowu0162/longmemeval-cleaned/longmemeval_oracle.json",
        },
        "selection": {
            "seed": args.seed,
            "per_stratum": args.per_stratum,
            "question_count": len(selected),
            "selection_manifest": str(args.selection_manifest.resolve())
            if args.selection_manifest
            else None,
            "excluded_question_count": len(
                json.loads(args.exclude_report.read_text(encoding="utf-8"))
                .get("selection", {})
                .get("question_ids", [])
            )
            if args.exclude_report
            else 0,
            "question_ids": [str(row["question_id"]) for row in selected],
            "selection_fingerprint": _fingerprint(
                [
                    args.seed,
                    args.per_stratum,
                    [str(row["question_id"]) for row in selected],
                ]
            ),
        },
        "model": args.model,
        "base_url": args.base_url,
        "reader_token_budget": args.reader_token_budget,
        "max_answer_tokens": args.max_answer_tokens,
        "legacy": _metrics(rows, "legacy"),
        "reader_evidence": _metrics(rows, "reader_evidence"),
        "paired": {
            "gains": gains,
            "losses": losses,
            "unchanged_verdicts": len(rows) - gains - losses,
            "changed_answers": changed_answers,
            "accuracy_delta": round(
                _metrics(rows, "reader_evidence")["local_proxy_accuracy"]
                - _metrics(rows, "legacy")["local_proxy_accuracy"],
                6,
            ),
        },
        "strata": {
            stratum: {
                "legacy": _metrics(by_stratum[stratum], "legacy"),
                "reader_evidence": _metrics(by_stratum[stratum], "reader_evidence"),
            }
            for stratum in STRATA
        },
        "rows": rows,
    }


def main() -> int:
    args = parse_args()
    dataset_bytes = args.dataset.read_bytes()
    dataset_hash = _sha256_bytes(dataset_bytes)
    dataset = json.loads(dataset_bytes)
    if not isinstance(dataset, list):
        raise RuntimeError("LongMemEval dataset must be a JSON list.")
    excluded_ids: set[str] = set()
    if args.selection_manifest:
        selected = select_from_manifest(
            dataset,
            manifest=json.loads(args.selection_manifest.read_text(encoding="utf-8")),
            dataset_hash=dataset_hash,
        )
    else:
        if args.exclude_report:
            excluded = json.loads(args.exclude_report.read_text(encoding="utf-8"))
            excluded_ids.update(
                str(item)
                for item in (excluded.get("selection") or {}).get("question_ids") or []
            )
        selected = select_references(
            dataset,
            per_stratum=max(1, args.per_stratum),
            seed=args.seed,
            excluded_ids=excluded_ids,
        )
    selection = [
        {
            "question_id": row["question_id"],
            "stratum": row["evaluation_stratum"],
            "question_type": row["question_type"],
        }
        for row in selected
    ]
    if args.selection_only:
        print(
            json.dumps(
                {
                    "protocol": PROTOCOL,
                    "dataset_sha256": dataset_hash,
                    "selection": selection,
                },
                indent=2,
            )
        )
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    if args.output.exists() and not args.force:
        existing = json.loads(args.output.read_text(encoding="utf-8"))
        if (
            existing.get("protocol") == PROTOCOL
            and (existing.get("dataset") or {}).get("sha256") == dataset_hash
            and (existing.get("selection") or {}).get("question_ids")
            == [str(row["question_id"]) for row in selected]
            and existing.get("model") == args.model
        ):
            rows = list(existing.get("rows") or [])
    by_id = {str(row["question_id"]): row for row in rows}

    for position, reference in enumerate(selected, start=1):
        question_id = str(reference["question_id"])
        if question_id in by_id:
            continue
        condition_order = ["legacy", "reader_evidence"]
        if int(_fingerprint([args.seed, question_id])[:2], 16) % 2:
            condition_order.reverse()
        condition_results: dict[str, dict] = {}
        for presentation in condition_order:
            prompt, packing = _reader_prompt(
                reference,
                presentation=presentation,
                token_budget=args.reader_token_budget,
            )
            started = time.perf_counter()
            answer = _post_chat(
                base_url=args.base_url,
                model=args.model,
                prompt=prompt,
                max_tokens=args.max_answer_tokens,
                timeout=args.timeout,
            )
            condition_results[presentation] = {
                "answer": answer,
                "packing": packing,
                "reader_seconds": round(time.perf_counter() - started, 4),
                "token_f1": round(_token_f1(str(reference["answer"]), answer), 6),
                "reference_contained": _normalized_contains(
                    str(reference["answer"]), answer
                ),
            }
        for presentation in condition_order:
            condition_results[presentation]["accepted"] = _judge(
                base_url=args.base_url,
                model=args.model,
                reference=reference,
                answer=str(condition_results[presentation]["answer"]),
                timeout=args.timeout,
            )
        row = {
            "question_id": question_id,
            "stratum": reference["evaluation_stratum"],
            "question_type": reference["question_type"],
            "question": reference["question"],
            "reference_answer": reference["answer"],
            "condition_order": condition_order,
            **condition_results,
        }
        by_id[question_id] = row
        rows = [
            by_id[str(item["question_id"])]
            for item in selected
            if str(item["question_id"]) in by_id
        ]
        report = _report(
            args=args, dataset_hash=dataset_hash, selected=selected, rows=rows
        )
        args.output.write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(
            f"{position}/{len(selected)} {reference['evaluation_stratum']} {question_id}: "
            f"legacy={condition_results['legacy']['accepted']} "
            f"reader_evidence={condition_results['reader_evidence']['accepted']}",
            flush=True,
        )

    report = _report(args=args, dataset_hash=dataset_hash, selected=selected, rows=rows)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "scope",
                    "selection",
                    "legacy",
                    "reader_evidence",
                    "paired",
                    "strata",
                )
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(
        "DEAD EXPERIMENT: reader-evidence packing failed its frozen accuracy gates"
    )
    # raise SystemExit(main())  # Intentionally disabled; audit code only.
