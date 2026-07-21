from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from typing import Any

from backend.app.core.typed_evidence import (
    ENTITY_LEXICONS,
    SCHEMA_HASH,
    Citation,
    EvidenceRecord,
    NumericValue,
    PreferenceSignal,
    QueryPlan,
    ReducerResult,
    plan_query,
    reduce_evidence,
    render_evidence_contract,
)


RUNTIME_ADAPTER_VERSION = "temporal-ledger-v4"


def evaluate_runtime_evidence(
    conn: sqlite3.Connection,
    *,
    vault_id: str,
    cluster_id: str | None,
    question: str,
    limit: int = 500,
) -> dict:
    """Evaluate typed evidence from Vault's authoritative temporal ledger.

    This adapter never calls a model and never converts retrieved prose into facts. It
    only consumes ledger rows whose source envelope and speaker provenance were already
    validated at ingestion time. Unsupported or incomplete plans fall back to the normal
    retrieval path.
    """

    plan = plan_runtime_query(question)
    if plan.intent == "unsupported":
        return _decision(plan=plan, result=_unsupported(question), records=[])

    rows, ledger_truncated = _load_temporal_rows(
        conn,
        vault_id=vault_id,
        cluster_id=cluster_id,
        limit=limit,
    )
    plan, rows = scope_runtime_query(plan, rows, question)
    history_requested = bool(
        re.search(
            r"\b(changed|change|history|over time|used to|previously|formerly)\b",
            question,
            re.I,
        )
    )
    if plan.intent == "personalized_advice" or (
        plan.intent == "preference_summary" and not history_requested
    ):
        rows = [row for row in rows if str(row.get("status") or "") == "current"]
    records = records_from_temporal_rows(rows, plan=plan)
    result = reduce_evidence(
        plan,
        records,
        question=question,
        allow_deterministic_advice_anchors=True,
        allow_cross_session_advice_anchors=True,
    )
    if ledger_truncated and result.status != "fallback":
        result = ReducerResult(
            intent=plan.intent,
            status="fallback",
            reason="The temporal ledger exceeded the bounded runtime scan; a partial result was not used.",
            confidence=0.0,
        )
    return _decision(
        plan=plan,
        result=result,
        records=records,
        ledger_truncated=ledger_truncated,
    )


def scope_runtime_query(
    plan: QueryPlan,
    rows: list[dict[str, Any]],
    question: str,
) -> tuple[QueryPlan, list[dict[str, Any]]]:
    """Apply the runtime subject/topic scope shared by chat memory and reducers."""

    if plan.intent != "preference_summary":
        return plan, rows
    named_subjects = _named_subjects_in_question(rows, question)
    if named_subjects:
        rows = [
            row
            for row in rows
            if str(row.get("subject_key") or "").casefold() in named_subjects
        ]
    updates: dict[str, Any] = {
        "topic_terms": _preference_topic_terms(
            question, named_subjects=named_subjects
        )
    }
    if len(named_subjects) == 1:
        updates["target_subject"] = next(iter(named_subjects))
    return plan.model_copy(update=updates), rows


def plan_runtime_query(question: str) -> QueryPlan:
    lowered = " ".join(str(question or "").lower().split())
    preference_markers = (
        "my preferences",
        "my preference",
        "my favorite",
        "my favourite",
        "what do i prefer",
        "what do i like",
        "what do i dislike",
        "what do i avoid",
        "do i still like",
        "do i still prefer",
    )
    named_preference_query = bool(
        re.search(
            r"\bwhat\s+are\s+[a-z][a-z .'-]{0,40}(?:'s|s')?\s+preferences?\b",
            lowered,
        )
        or re.search(
            r"\bwhat\s+(?:does|did)\s+[a-z][a-z'-]{0,30}\s+"
            r"(?:(?:usually|generally|typically|normally|tend(?:s)? to)\s+)?prefer\b",
            lowered,
        )
    )
    if any(marker in lowered for marker in preference_markers) or named_preference_query:
        base = plan_query(
            {"question": question, "question_type": "single-session-preference"}
        )
        return base.model_copy(
            update={
                "intent": "preference_summary",
                "allowed_primary_modes": ["current"],
                "required_anchor_types": [],
            }
        )
    personalized_markers = (
        "based on my",
        "given my",
        "for me",
        "my interests",
        "what should i",
        "recommend",
        "suggest",
        "advice",
    )
    if any(marker in lowered for marker in personalized_markers):
        return plan_query(
            {
                "question": question,
                "question_type": "single-session-preference",
            }
        )
    return plan_query({"question": question})


def records_from_temporal_rows(
    rows: list[dict[str, Any]], *, plan: QueryPlan
) -> list[EvidenceRecord]:
    records: list[EvidenceRecord] = []
    for row in rows:
        base = _record_from_temporal_row(row)
        if base is None:
            continue
        entity_records = _entity_records(base, plan=plan)
        if plan.intent == "distinct_count":
            records.extend(entity_records)
        else:
            records.append(base)
            records.extend(entity_records)
    return records


def _named_subjects_in_question(
    rows: list[dict[str, Any]], question: str
) -> set[str]:
    question_tokens = set(re.findall(r"[a-z0-9]+", question.casefold()))
    matched: set[str] = set()
    for row in rows:
        subject = str(row.get("subject_key") or "").casefold()
        if not subject or subject == "user":
            continue
        subject_tokens = set(re.findall(r"[a-z0-9]+", subject.replace("_", " ")))
        if subject_tokens and subject_tokens <= question_tokens:
            matched.add(subject)
    return matched


def _preference_topic_terms(
    question: str, *, named_subjects: set[str]
) -> list[str]:
    ignored = {
        "avoid",
        "are",
        "about",
        "changed",
        "changes",
        "current",
        "dislike",
        "does",
        "did",
        "for",
        "from",
        "favorite",
        "favourite",
        "generally",
        "history",
        "how",
        "have",
        "mine",
        "now",
        "like",
        "likes",
        "my",
        "normally",
        "our",
        "over",
        "prefer",
        "preference",
        "preferences",
        "still",
        "the",
        "time",
        "typically",
        "usually",
        "user",
        "what",
        "when",
        "your",
    }
    subject_terms = {
        token
        for subject in named_subjects
        for token in re.findall(r"[a-z0-9]{3,}", subject.replace("_", " "))
    }
    return list(
        dict.fromkeys(
            token
            for token in re.findall(r"[a-z0-9]{3,}", question.casefold())
            if token not in ignored and token not in subject_terms
        )
    )


def contract_memory_item(decision: dict) -> dict | None:
    result: ReducerResult = decision["result"]
    records: list[EvidenceRecord] = decision["records"]
    if result.status != "needs_generation" or result.contract is None:
        return None
    rendered = render_evidence_contract(result, records)
    if not rendered:
        return None
    required = set(result.contract.required_claim_ids)
    selected = [record for record in records if record.claim_id in required]
    return {
        "id": f"typed-contract:{SCHEMA_HASH[:12]}",
        "kind": "typed_evidence_contract",
        "summary": rendered,
        "detail_text": rendered,
        "confidence": result.confidence,
        "source_id": None,
        "session_id": selected[0].citation.session_id if selected else None,
        "updated_at": max(
            (record.citation.session_date for record in selected),
            default="",
        ),
        "typed_required_claim_ids": list(result.contract.required_claim_ids),
        "typed_supporting_claim_ids": list(result.contract.supporting_claim_ids),
    }


def public_diagnostics(decision: dict) -> dict:
    result: ReducerResult = decision["result"]
    plan: QueryPlan = decision["plan"]
    records: list[EvidenceRecord] = decision["records"]
    return {
        "adapter_version": RUNTIME_ADAPTER_VERSION,
        "schema_hash": SCHEMA_HASH,
        "intent": plan.intent,
        "status": result.status,
        "confidence": result.confidence,
        "record_count": len(records),
        "evidence_claim_count": len(result.evidence_claim_ids),
        "reason": result.reason or "",
        "deterministic_answer_used": result.status == "resolved",
        "contract_injected": result.status == "needs_generation",
        "ledger_truncated": bool(decision.get("ledger_truncated")),
    }


def _load_temporal_rows(
    conn: sqlite3.Connection,
    *,
    vault_id: str,
    cluster_id: str | None,
    limit: int,
) -> tuple[list[dict[str, Any]], bool]:
    clauses = [
        "facts.vault_id = ?",
        "facts.status != 'retracted'",
        "facts.speaker_role = 'user'",
        "facts.assertion_kind != 'suggestion'",
    ]
    params: list[Any] = [vault_id]
    if cluster_id:
        clauses.append("(facts.cluster_id = ? OR facts.cluster_id IS NULL)")
        params.append(cluster_id)
    bounded_limit = max(1, min(int(limit), 2000))
    params.append(bounded_limit + 1)
    rows = conn.execute(
        f"""
        SELECT facts.*
        FROM temporal_facts facts
        WHERE {' AND '.join(clauses)}
        ORDER BY facts.valid_from DESC, facts.created_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    ledger_truncated = len(rows) > bounded_limit
    return [dict(row) for row in rows[:bounded_limit]], ledger_truncated


def _record_from_temporal_row(row: dict[str, Any]) -> EvidenceRecord | None:
    excerpt = " ".join(str(row.get("citation_excerpt") or "").split())[:600]
    if not excerpt:
        return None
    speaker = str(row.get("speaker_role") or "").lower()
    if speaker != "user":
        return None
    assertion_kind = str(row.get("assertion_kind") or "fact")
    primary_mode = {
        "action": "completed",
        "plan": "planned",
        "goal": "goal",
        "suggestion": "suggested",
    }.get(assertion_kind, "current")
    semantic_tags: list[str] = []
    if assertion_kind == "action":
        semantic_tags.extend(["demonstrated_experience", "event"])
    elif assertion_kind in {"plan", "goal"}:
        semantic_tags.append("stated_goal_or_interest")
    elif assertion_kind == "preference":
        semantic_tags.extend(["preference", "stated_goal_or_interest"])
    elif assertion_kind == "state":
        semantic_tags.append("state_snapshot")

    metadata = _metadata(row.get("metadata_json"))
    numeric = _numeric_value(metadata.get("numeric"))
    preference = None
    if assertion_kind == "preference":
        polarity = str(metadata.get("polarity") or "positive")
        if polarity not in {"positive", "negative"}:
            polarity = "positive"
        supersession_key = str(row.get("supersession_key") or "")
        topic = (
            re.sub(r"^[^:]+:preference:", "", supersession_key)
            or re.sub(
                r"[^a-z0-9]+",
                "_",
                str(row.get("object_text") or "").casefold(),
            ).strip("_")
        )
        preference = PreferenceSignal(
            polarity=polarity,
            strength="soft",
            topic=topic,
        )
    fingerprint = str(row.get("origin_fingerprint") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        fingerprint = hashlib.sha256(
            json.dumps(row, default=str, sort_keys=True).encode("utf-8")
        ).hexdigest()
    session_id = str(row.get("session_id") or f"{row.get('source_type', 'fact')}:{row.get('source_id')}")
    fact_id = str(row.get("id") or fingerprint[:16])
    return EvidenceRecord(
        claim_id=f"temporal_{fact_id}",
        citation=Citation(
            session_id=session_id,
            turn_index=0,
            speaker="user",
            session_date=str(row.get("valid_from") or row.get("observed_at") or "unknown"),
            excerpt=excerpt,
            source_content_hash=fingerprint,
        ),
        extraction_origin="deterministic_envelope",
        provenance="user_statement",
        primary_mode=primary_mode,
        negated=str(row.get("modality") or "asserted") == "negated",
        subject=str(row.get("subject_key") or "user"),
        predicate=str(row.get("predicate_key") or "fact"),
        object=str(row.get("object_text") or "unknown"),
        object_type=str(row.get("object_type") or "text"),
        event_date=str(metadata.get("event_time") or row.get("valid_from") or "") or None,
        numeric=numeric,
        preference=preference,
        semantic_tags=semantic_tags,
        confidence=float(row.get("confidence") or 0.0),
    )


def _entity_records(base: EvidenceRecord, *, plan: QueryPlan) -> list[EvidenceRecord]:
    entity_type = plan.target_entity_type or ""
    lexicon = ENTITY_LEXICONS.get(entity_type)
    if not lexicon or base.primary_mode != "completed" or base.negated:
        return []
    searchable = f"{base.object.replace('_', ' ')} {base.citation.excerpt}".lower()
    found = [entity for entity in lexicon if re.search(rf"\b{re.escape(entity)}\b", searchable)]
    return [
        base.model_copy(
            update={
                "claim_id": f"{base.claim_id}_{entity_type}_{re.sub(r'[^a-z0-9]+', '_', entity)}",
                "object": entity,
                "object_type": entity_type,
            }
        )
        for entity in found
    ]


def _numeric_value(value: Any) -> NumericValue | None:
    if not isinstance(value, dict):
        return None
    try:
        return NumericValue.model_validate(value)
    except Exception:
        return None


def _metadata(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _unsupported(question: str) -> ReducerResult:
    return ReducerResult(
        intent="unsupported",
        status="fallback",
        reason=f"No typed reducer supports this question: {question}",
        confidence=0.0,
    )


def _decision(
    *,
    plan: QueryPlan,
    result: ReducerResult,
    records: list[EvidenceRecord],
    ledger_truncated: bool = False,
) -> dict:
    return {
        "plan": plan,
        "result": result,
        "records": records,
        "ledger_truncated": ledger_truncated,
    }
