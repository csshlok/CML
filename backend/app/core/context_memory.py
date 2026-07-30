import json
import re
from collections import Counter
from uuid import uuid4

from backend.app.core.database import dict_from_row, utc_now
from backend.app.core.embeddings import content_hash
from backend.app.core.encrypted_storage import hydrate_chat_message_rows, source_from_encrypted_row
from backend.app.core.memory_card import summarize_text
from backend.app.core.atomic_memory_store import load_v2_atomic_memory_items
from backend.app.core.temporal_facts import (
    parse_as_of_query,
    query_temporal_fact_versions,
    query_temporal_facts,
    sync_chat_session_temporal_facts,
)
from backend.app.core.typed_evidence import QueryPlan
from backend.app.core.typed_evidence_runtime import plan_runtime_query, scope_runtime_query


MEMORY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("decision", re.compile(r"\b(decided|decision|chosen|we will|we'll|will use|selected)\b", re.IGNORECASE)),
    ("constraint", re.compile(r"\b(must|should not|cannot|can't|need to|requires|constraint)\b", re.IGNORECASE)),
    ("goal", re.compile(r"\b(goal|vision|want to|need to build|target|aim)\b", re.IGNORECASE)),
    ("task", re.compile(r"\b(todo|to do|implement|build|fix|add|update|work on)\b", re.IGNORECASE)),
    ("open_loop", re.compile(r"\b(question|follow up|later|remaining|still need|next pass)\b", re.IGNORECASE)),
]


def rebuild_chat_session_memory(conn, *, vault_id: str, session_id: str) -> None:
    session = conn.execute("SELECT * FROM chat_sessions WHERE id = ? AND vault_id = ?", (session_id, vault_id)).fetchone()
    if session is None:
        return
    messages = hydrate_chat_message_rows(conn, conn.execute(
        "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC, rowid ASC",
        (session_id,),
    ).fetchall())
    if not messages:
        return
    cluster_id = session["scope_cluster_id"]
    # Durable personal memory is sourced from the user's own statements.
    # Assistant turns remain available through recent conversation and the
    # provenance-aware temporal ledgers, but cannot silently become user facts.
    text = "\n".join(
        str(row["content"])
        for row in messages
        if str(row["role"] or "").strip().casefold() == "user"
        and str(row["content"] or "").strip()
    )
    _replace_memory_items(
        conn,
        vault_id=vault_id,
        cluster_id=cluster_id,
        source_id=None,
        session_id=session_id,
        text=text,
        origin_prefix=f"chat-session:{session_id}",
        review_state="user_asserted",
        include_fallback=False,
    )
    sync_chat_session_temporal_facts(
        conn,
        vault_id=vault_id,
        session_id=session_id,
        messages=messages,
    )
    refresh_working_memory(conn, vault_id=vault_id, cluster_id=cluster_id)
    refresh_bootstrap_memory_map(conn, vault_id=vault_id, cluster_id=cluster_id)


def rebuild_source_memory(conn, *, source_id: str) -> None:
    row = conn.execute("SELECT * FROM sources WHERE id = ? AND deleted_at IS NULL", (source_id,)).fetchone()
    if row is None:
        return
    source = source_from_encrypted_row(conn, row)
    if _source_is_memory_excluded(source):
        _invalidate_memory_items(conn, source_id=source_id)
        return
    text = str(source.get("summary") or source.get("extracted_text") or source.get("raw_text") or "").strip()
    if not text:
        _invalidate_memory_items(conn, source_id=source_id)
        return
    _replace_memory_items(
        conn,
        vault_id=source["vault_id"],
        cluster_id=source.get("cluster_id"),
        source_id=source_id,
        session_id=None,
        text=text,
        origin_prefix=f"source:{source_id}",
    )
    refresh_working_memory(conn, vault_id=source["vault_id"], cluster_id=source.get("cluster_id"))
    refresh_bootstrap_memory_map(conn, vault_id=source["vault_id"], cluster_id=source.get("cluster_id"))


def get_context_memory(
    conn,
    *,
    vault_id: str,
    cluster_id: str | None,
    query: str,
    limit: int = 8,
    personal_only: bool = False,
) -> tuple[list[dict], dict]:
    working = (
        {}
        if personal_only
        else _latest_working_memory(conn, vault_id=vault_id, cluster_id=cluster_id)
    )
    memory_items = _select_memory_items(
        conn,
        vault_id=vault_id,
        cluster_id=cluster_id,
        query=query,
        limit=limit,
        personal_only=personal_only,
    )
    temporal_items = _select_temporal_memory_items(
        conn,
        vault_id=vault_id,
        cluster_id=cluster_id,
        query=query,
        limit=limit,
    )
    from backend.app.core.config import get_settings

    v2_items = []
    if get_settings().atomic_v2_retrieval_enabled:
        v2_items = load_v2_atomic_memory_items(
            conn,
            vault_id=vault_id,
            cluster_id=cluster_id,
            query=query,
            limit=limit,
        )
    if personal_only:
        temporal_items = [
            item
            for item in temporal_items
            if str(item.get("speaker_role") or "").casefold() == "user"
        ]
        v2_items = [
            item
            for item in v2_items
            if str(item.get("speaker_role") or "").casefold() == "user"
        ]
    memory_items = _merge_memory_items(
        temporal_items,
        v2_items,
        memory_items,
        limit=limit,
    )
    if not working and not personal_only:
        refresh_bootstrap_memory_map(conn, vault_id=vault_id, cluster_id=cluster_id)
        working = _latest_working_memory(conn, vault_id=vault_id, cluster_id=cluster_id)
    return memory_items, working or {}


def refresh_working_memory(conn, *, vault_id: str, cluster_id: str | None) -> None:
    memory_rows = _select_memory_items(conn, vault_id=vault_id, cluster_id=cluster_id, query="", limit=6)
    source_count = _indexed_source_count(conn, vault_id=vault_id, cluster_id=cluster_id)
    summary_parts = []
    if memory_rows:
        top_kinds = Counter(item["kind"] for item in memory_rows)
        summary_parts.append(
            "Current memory signals: "
            + ", ".join(f"{count} {kind}" for kind, count in top_kinds.most_common(3))
        )
        summary_parts.extend(item["summary"] for item in memory_rows[:3] if item.get("summary"))
    else:
        summary_parts.append("No distilled memory items have been extracted yet.")
    summary = summarize_text(" ".join(summary_parts), max_chars=320)
    _upsert_working_memory_snapshot(
        conn,
        vault_id=vault_id,
        cluster_id=cluster_id,
        scope_type="cluster" if cluster_id else "vault",
        summary=summary,
        source_count=source_count,
        memory_count=len(memory_rows),
    )


def refresh_bootstrap_memory_map(conn, *, vault_id: str, cluster_id: str | None) -> None:
    if _latest_working_memory(conn, vault_id=vault_id, cluster_id=cluster_id):
        return
    if cluster_id:
        cluster = conn.execute("SELECT name FROM clusters WHERE id = ? AND vault_id = ?", (cluster_id, vault_id)).fetchone()
        source_rows = conn.execute(
            """
            SELECT *
            FROM sources
            WHERE vault_id = ? AND cluster_id = ? AND state = 'indexed' AND deleted_at IS NULL
            ORDER BY updated_at DESC
            LIMIT 5
            """,
            (vault_id, cluster_id),
        ).fetchall()
        sources = [source_from_encrypted_row(conn, row) for row in source_rows]
        cluster_name = str(cluster["name"]) if cluster else "cluster"
        summary = f"Bootstrap map for {cluster_name}: "
        if sources:
            summary += "; ".join(
                summarize_text(f"{source['title']}. {source['summary']}", max_chars=80)
                for source in sources
            )
        else:
            summary += "No indexed sources are available yet."
    else:
        clusters = conn.execute(
            """
            SELECT name
            FROM clusters
            WHERE vault_id = ?
            ORDER BY updated_at DESC
            LIMIT 6
            """,
            (vault_id,),
        ).fetchall()
        summary = "Bootstrap map for vault: "
        if clusters:
            summary += "Clusters present: " + ", ".join(str(row["name"]) for row in clusters)
        else:
            summary += "No clusters are available yet."
    _upsert_working_memory_snapshot(
        conn,
        vault_id=vault_id,
        cluster_id=cluster_id,
        scope_type="cluster" if cluster_id else "vault",
        summary=summarize_text(summary, max_chars=320),
        source_count=_indexed_source_count(conn, vault_id=vault_id, cluster_id=cluster_id),
        memory_count=_memory_item_count(conn, vault_id=vault_id, cluster_id=cluster_id),
    )


def classify_external_response_quality(
    conn,
    *,
    vault_id: str,
    context_request_id: str | None,
    response_text: str,
    artifact_mode: bool = False,
) -> dict:
    if artifact_mode:
        return {"quality_state": "user_artifact", "reasons": ["explicit_artifact_capture"]}
    if not context_request_id:
        return {"quality_state": "unknown", "reasons": ["missing_context_request_id"]}
    packet = conn.execute(
        "SELECT * FROM bridge_context_packets WHERE id = ? AND vault_id = ?",
        (context_request_id, vault_id),
    ).fetchone()
    if packet is None:
        return {"quality_state": "unknown", "reasons": ["context_request_not_found"]}
    handles = _json_list(packet["evidence_handles_json"])
    titles = _json_list(packet["source_titles_json"])
    packet_text = " ".join(str(packet["packet_text"] or "").lower().split())
    normalized = " ".join(response_text.lower().split())
    matched_handles = [handle for handle in handles if handle.lower() in normalized]
    matched_titles = [title for title in titles if str(title).lower() in normalized]
    sentence_profile = _response_sentence_support_profile(
        response_text=response_text,
        packet_text=packet_text,
        handles=handles,
        titles=titles,
    )
    supported_sentences = sentence_profile["supported_count"]
    unsupported_sentences = sentence_profile["unsupported_count"]
    total_sentences = sentence_profile["total_sentences"]
    referenced_only_sentences = sentence_profile["referenced_only_count"]
    contradiction = _response_contradicts_packet(normalized, packet_text)
    reasons = []
    if matched_handles:
        reasons.append("matched_packet_handle")
    if matched_titles:
        reasons.append("matched_source_title")
    if supported_sentences:
        reasons.append("matched_packet_terms")
    if referenced_only_sentences:
        reasons.append("insufficient_packet_support")
    if unsupported_sentences:
        reasons.append("unsupported_claims_detected")
    if contradiction:
        reasons.append("contradiction_detected")
        if supported_sentences or matched_titles or matched_handles:
            return {"quality_state": "partially_grounded", "reasons": _unique_reasons(reasons)}
        return {"quality_state": "ungrounded", "reasons": _unique_reasons(reasons) or ["contradiction_detected"]}
    if supported_sentences == total_sentences and total_sentences > 0 and unsupported_sentences == 0:
        return {"quality_state": "grounded", "reasons": _unique_reasons(reasons) or ["full_packet_support"]}
    if supported_sentences > 0 or referenced_only_sentences > 0:
        return {"quality_state": "partially_grounded", "reasons": _unique_reasons(reasons) or ["partial_packet_support"]}
    if matched_handles or matched_titles:
        return {"quality_state": "partially_grounded", "reasons": _unique_reasons(reasons)}
    if unsupported_sentences:
        reasons.append("no_packet_overlap_detected")
        return {"quality_state": "ungrounded", "reasons": _unique_reasons(reasons)}
    if titles:
        return {"quality_state": "ungrounded", "reasons": _unique_reasons(reasons) or ["no_packet_overlap_detected"]}
    return {"quality_state": "unknown", "reasons": ["packet_had_no_evidence"]}


def persist_bridge_writeback_review(
    conn,
    *,
    source_id: str,
    vault_id: str,
    context_request_id: str | None,
    quality_state: str,
    reasons: list[str],
) -> None:
    now = utc_now()
    existing = conn.execute("SELECT id FROM bridge_writeback_reviews WHERE source_id = ?", (source_id,)).fetchone()
    payload = {
        "source_id": source_id,
        "vault_id": vault_id,
        "context_request_id": context_request_id,
        "quality_state": quality_state,
        "reasons_json": json.dumps(reasons, separators=(",", ":")),
        "updated_at": now,
    }
    if existing is None:
        conn.execute(
            """
            INSERT INTO bridge_writeback_reviews (
                id, source_id, vault_id, context_request_id, quality_state, reasons_json, approved, created_at, updated_at
            )
            VALUES (:id, :source_id, :vault_id, :context_request_id, :quality_state, :reasons_json, 0, :updated_at, :updated_at)
            """,
            {"id": f"bridge-review-{uuid4()}", **payload},
        )
    else:
        conn.execute(
            """
            UPDATE bridge_writeback_reviews
            SET context_request_id = :context_request_id,
                quality_state = :quality_state,
                reasons_json = :reasons_json,
                updated_at = :updated_at
            WHERE source_id = :source_id
            """,
            payload,
        )


def apply_bridge_quality_to_source(conn, *, source_id: str, quality_state: str, reasons: list[str]) -> None:
    row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    if row is None:
        return
    source = dict_from_row(row)
    labels = set(_json_list(source.get("security_labels") or "[]"))
    labels.discard("review_needed")
    labels.discard("ungrounded_external")
    labels.discard("partial_external")
    labels.discard("external_untrusted")
    trust_tier = source.get("trust_tier") or "external_capture"
    if quality_state in {"ungrounded", "unknown"}:
        trust_tier = "low_trust_web"
        labels.update({"review_needed", "ungrounded_external", "external_untrusted"})
    elif quality_state == "partially_grounded":
        trust_tier = "external_capture"
        labels.update({"review_needed", "partial_external", "external_untrusted"})
    elif quality_state == "user_artifact":
        trust_tier = "external_capture"
        labels.add("external_untrusted")
    else:
        trust_tier = "external_capture"
    conn.execute(
        """
        UPDATE sources
        SET trust_tier = ?, security_labels = ?, parser_security_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            trust_tier,
            json.dumps(sorted(labels)),
            json.dumps({"bridge_quality_state": quality_state, "bridge_quality_reasons": reasons}, separators=(",", ":")),
            utc_now(),
            source_id,
        ),
    )


def set_bridge_writeback_review_approval(
    conn,
    *,
    source_id: str,
    approved: bool,
) -> dict | None:
    review = conn.execute("SELECT * FROM bridge_writeback_reviews WHERE source_id = ?", (source_id,)).fetchone()
    source_row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    if review is None or source_row is None:
        return None
    now = utc_now()
    conn.execute(
        "UPDATE bridge_writeback_reviews SET approved = ?, updated_at = ? WHERE source_id = ?",
        (1 if approved else 0, now, source_id),
    )
    source = dict_from_row(source_row)
    labels = set(_json_list(source.get("security_labels") or "[]"))
    labels.discard("review_needed")
    labels.discard("ungrounded_external")
    labels.discard("partial_external")
    if approved:
        labels.discard("external_untrusted")
        trust_tier = "trusted_reviewed"
    else:
        quality_state = str(review["quality_state"] or "")
        trust_tier = "low_trust_web" if quality_state in {"ungrounded", "unknown"} else "external_capture"
        if quality_state != "grounded":
            labels.add("review_needed")
    metadata = {}
    try:
        metadata = json.loads(source.get("parser_security_json") or "{}")
    except json.JSONDecodeError:
        metadata = {}
    metadata["bridge_review_approved"] = bool(approved)
    metadata["bridge_review_updated_at"] = now
    conn.execute(
        """
        UPDATE sources
        SET trust_tier = ?, security_labels = ?, parser_security_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            trust_tier,
            json.dumps(sorted(labels)),
            json.dumps(metadata, separators=(",", ":")),
            now,
            source_id,
        ),
    )
    if approved:
        rebuild_source_memory(conn, source_id=source_id)
    else:
        _invalidate_memory_items(conn, source_id=source_id)
    return {
        "source_id": source_id,
        "approved": bool(approved),
        "trust_tier": trust_tier,
        "security_labels": sorted(labels),
        "quality_state": review["quality_state"],
    }


def _replace_memory_items(
    conn,
    *,
    vault_id: str,
    cluster_id: str | None,
    source_id: str | None,
    session_id: str | None,
    text: str,
    origin_prefix: str,
    review_state: str = "auto",
    include_fallback: bool = True,
) -> None:
    _invalidate_memory_items(conn, source_id=source_id, session_id=session_id)
    items = _extract_memory_candidates(text, include_fallback=include_fallback)
    now = utc_now()
    for index, item in enumerate(items, start=1):
        fingerprint = content_hash(f"{origin_prefix}:{item['kind']}:{item['summary']}")
        conn.execute(
            """
            INSERT INTO memory_items (
                id, vault_id, cluster_id, source_id, session_id, kind, summary, detail_text,
                confidence, freshness, review_state, status, origin_fingerprint, created_at, updated_at, invalidated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, NULL)
            """,
            (
                f"memory-{uuid4()}",
                vault_id,
                cluster_id,
                source_id,
                session_id,
                item["kind"],
                item["summary"],
                item["detail_text"],
                item["confidence"],
                item["freshness"],
                review_state,
                fingerprint,
                now,
                now,
            ),
        )


def _extract_memory_candidates(
    text: str,
    *,
    include_fallback: bool = True,
) -> list[dict]:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return []
    sentences = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", cleaned) if segment.strip()]
    items: list[dict] = []
    seen: set[str] = set()
    for sentence in sentences[:24]:
        lower = sentence.lower()
        kind = None
        for candidate_kind, pattern in MEMORY_PATTERNS:
            if pattern.search(lower):
                kind = candidate_kind
                break
        if kind is None:
            continue
        summary = summarize_text(sentence, max_chars=180)
        if summary.lower() in seen:
            continue
        seen.add(summary.lower())
        items.append(
            {
                "kind": kind,
                "summary": summary,
                "detail_text": sentence,
                "confidence": 0.7 if kind in {"decision", "constraint"} else 0.6,
                "freshness": 0.9,
            }
        )
    if not items and cleaned and include_fallback:
        items.append(
            {
                "kind": "fact",
                "summary": summarize_text(cleaned, max_chars=180),
                "detail_text": summarize_text(cleaned, max_chars=320),
                "confidence": 0.5,
                "freshness": 0.7,
            }
        )
    return items[:10]


def _response_sentence_support_profile(
    *,
    response_text: str,
    packet_text: str,
    handles: list[str],
    titles: list[str],
) -> dict:
    supported = 0
    referenced_only = 0
    unsupported = 0
    packet_terms = {term for term in re.findall(r"[a-z0-9]{4,}", packet_text)}
    normalized_handles = [str(handle).lower() for handle in handles if str(handle).strip()]
    normalized_titles = [str(title).lower() for title in titles if str(title).strip()]
    reference_terms = {
        term
        for value in [*normalized_handles, *normalized_titles]
        for term in re.findall(r"[a-z0-9]{4,}", value)
    }
    for sentence in _split_response_sentences(response_text):
        normalized_sentence = " ".join(sentence.lower().split())
        sentence_terms = {term for term in re.findall(r"[a-z0-9]{4,}", sentence)}
        has_term_support = len(sentence_terms & packet_terms) >= 3
        has_handle_support = any(handle in normalized_sentence for handle in normalized_handles)
        has_title_support = any(title in normalized_sentence for title in normalized_titles)
        if has_term_support:
            supported += 1
        elif has_handle_support or has_title_support:
            referenced_only += 1
            unsupported_terms = sentence_terms - packet_terms - reference_terms
            if unsupported_terms:
                unsupported += 1
        else:
            unsupported += 1
    return {
        "supported_count": supported,
        "referenced_only_count": referenced_only,
        "unsupported_count": unsupported,
        "total_sentences": max(supported + referenced_only + unsupported, 1 if response_text.strip() else 0),
    }


def _response_sentence_count(response_text: str) -> int:
    return max(len(_split_response_sentences(response_text)), 1 if response_text.strip() else 0)


def _response_contradicts_packet(response_text: str, packet_text: str) -> bool:
    pairs = (
        ("retrieval first", "do not use retrieval first"),
        ("local-first", "not local-first"),
        ("must ", "must not"),
        ("allowed", "not allowed"),
    )
    for left, right in pairs:
        if left in packet_text and right in response_text:
            return True
        if right in packet_text and left in response_text:
            return True
    return False


def _split_response_sentences(response_text: str) -> list[str]:
    return [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", response_text) if segment.strip()]


def _unique_reasons(reasons: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for reason in reasons:
        normalized = str(reason or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _invalidate_memory_items(conn, *, source_id: str | None = None, session_id: str | None = None) -> None:
    if not source_id and not session_id:
        return
    now = utc_now()
    if source_id:
        conn.execute(
            "UPDATE memory_items SET status = 'inactive', invalidated_at = ?, updated_at = ? WHERE source_id = ? AND status = 'active'",
            (now, now, source_id),
        )
    if session_id:
        conn.execute(
            "UPDATE memory_items SET status = 'inactive', invalidated_at = ?, updated_at = ? WHERE session_id = ? AND status = 'active'",
            (now, now, session_id),
        )


def _select_memory_items(
    conn,
    *,
    vault_id: str,
    cluster_id: str | None,
    query: str,
    limit: int,
    personal_only: bool = False,
) -> list[dict]:
    params: list[str] = [vault_id]
    cluster_clause = ""
    if cluster_id:
        cluster_clause = "AND (cluster_id = ? OR cluster_id IS NULL)"
        params.append(cluster_id)
    personal_clause = (
        "AND session_id IS NOT NULL AND review_state = 'user_asserted'"
        if personal_only
        else ""
    )
    bounded_limit = max(1, min(limit, 50))
    candidate_limit = min(500, max(100, bounded_limit * 12))
    rows = conn.execute(
        f"""
        SELECT *
        FROM memory_items
        WHERE vault_id = ? AND status = 'active' {cluster_clause} {personal_clause}
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        [*params, candidate_limit],
    ).fetchall()
    query_terms = {term for term in re.findall(r"[a-z0-9]{3,}", query.lower())}
    scored = []
    for row in rows:
        item = dict_from_row(row)
        haystack = f"{item.get('summary','')} {item.get('detail_text','')}".lower()
        overlap = sum(1 for term in query_terms if term in haystack)
        scored.append((overlap, item["confidence"], item))
    scored.sort(key=lambda value: (value[0], value[1], value[2]["updated_at"]), reverse=True)
    return [item for _, _, item in scored[:bounded_limit]]


def _select_temporal_memory_items(
    conn,
    *,
    vault_id: str,
    cluster_id: str | None,
    query: str,
    limit: int,
) -> list[dict]:
    as_of = parse_as_of_query(query)
    facts = query_temporal_facts(
        conn,
        vault_id=vault_id,
        cluster_id=cluster_id,
        as_of=as_of,
        limit=100,
    )
    runtime_plan = plan_runtime_query(query)
    runtime_plan, scoped_facts = scope_runtime_query(runtime_plan, facts, query)
    consolidation = _consolidated_temporal_item(
        conn,
        vault_id=vault_id,
        cluster_id=cluster_id,
        query=query,
        current_facts=facts,
        as_of=as_of,
        runtime_plan=runtime_plan,
    )
    query_terms = (
        set(runtime_plan.topic_terms)
        if runtime_plan.intent == "preference_summary"
        else {term for term in re.findall(r"[a-z0-9]{3,}", query.lower())}
    )
    candidate_facts = (
        [fact for fact in scoped_facts if fact["assertion_kind"] == "preference"]
        if runtime_plan.intent == "preference_summary"
        else [fact for fact in facts if fact["assertion_kind"] != "preference"]
    )
    scored: list[tuple[int, float, str, dict]] = []
    for fact in candidate_facts:
        predicate = str(fact["predicate_key"]).replace("_", " ")
        if fact["modality"] == "negated":
            predicate = f"no longer {predicate}"
        summary = " ".join(
            (
                str(fact["subject_key"]).replace("_", " "),
                predicate,
                str(fact["object_text"]),
            )
        )
        searchable = f"{summary} {fact['citation_excerpt']}".casefold()
        overlap = sum(term in searchable for term in query_terms)
        if query_terms and overlap == 0:
            continue
        item = {
            "id": fact["id"],
            "kind": f"temporal_{fact['assertion_kind']}",
            "summary": summary,
            # The ledger date is already resolved from relative source wording such
            # as "yesterday". Keep the verbatim citation as metadata, but do not put
            # both representations in model-facing prose: readers can otherwise
            # apply the relative offset a second time.
            "detail_text": f"- {str(fact['valid_from'])[:10]} {summary}",
            "confidence": fact["confidence"],
            "source_id": fact["source_id"],
            "session_id": fact["session_id"],
            "updated_at": fact["valid_from"],
            "speaker_role": fact["speaker_role"],
            "valid_from": fact["valid_from"],
            "valid_until": fact["valid_until"],
            "citation_excerpt": fact["citation_excerpt"],
        }
        scored.append((overlap, float(fact["confidence"]), str(fact["valid_from"]), item))
    scored.sort(key=lambda value: (value[0], value[1], value[2]), reverse=True)
    ranked = [item for _, _, _, item in scored]
    if consolidation is not None:
        ranked.insert(0, consolidation)
    return ranked[: max(1, min(limit, 50))]


def _consolidated_temporal_item(
    conn,
    *,
    vault_id: str,
    cluster_id: str | None,
    query: str,
    current_facts: list[dict],
    as_of: str | None,
    runtime_plan: QueryPlan,
) -> dict | None:
    lowered = query.casefold()
    preference_query = runtime_plan.intent == "preference_summary"
    history_query = as_of is None and bool(
        re.search(
            r"\b(changed|change|history|over time|used to|previously|formerly|before)\b",
            lowered,
        )
    )
    state_predicate = _state_predicate_for_query(lowered)
    if not preference_query and not (history_query and state_predicate):
        return None

    if history_query:
        kind = "preference" if preference_query else "state"
        candidates = query_temporal_fact_versions(
            conn,
            vault_id=vault_id,
            cluster_id=cluster_id,
            assertion_kind=kind,
            limit=200,
        )
        if state_predicate:
            candidates = [
                fact for fact in candidates if fact["predicate_key"] == state_predicate
            ]
    else:
        candidates = [fact for fact in current_facts if fact["assertion_kind"] == "preference"]

    if preference_query:
        runtime_plan, candidates = scope_runtime_query(runtime_plan, candidates, query)
        query_terms = set(runtime_plan.topic_terms)
    else:
        query_terms = {term for term in re.findall(r"[a-z0-9]{3,}", lowered)}
    scored: list[tuple[int, str, dict]] = []
    for fact in candidates:
        text = " ".join(
            (
                str(fact["predicate_key"]).replace("_", " "),
                str(fact["object_text"]),
                str(fact["citation_excerpt"]),
            )
        ).casefold()
        overlap = sum(term in text for term in query_terms)
        if query_terms and overlap == 0:
            continue
        scored.append((overlap, str(fact["valid_from"]), fact))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    selected = [fact for _, _, fact in scored[:12]]
    if len({str(fact.get("session_id") or "") for fact in selected if fact.get("session_id")}) < 2:
        return None

    selected.sort(key=lambda fact: (str(fact["valid_from"]), str(fact["id"])))
    summaries: list[str] = []
    detail_lines: list[str] = []
    citations: list[dict] = []
    for fact in selected:
        predicate = str(fact["predicate_key"]).replace("_", " ")
        if fact["modality"] == "negated":
            predicate = f"no longer {predicate}"
        summary = f"{str(fact['subject_key']).replace('_', ' ')} {predicate} {fact['object_text']}"
        summaries.append(summary)
        detail_lines.append(
            f"- {str(fact['valid_from'])[:10]} [{fact['status']}] {summary} — \"{fact['citation_excerpt']}\""
        )
        citations.append(
            {
                "fact_id": fact["id"],
                "source_id": fact["source_id"],
                "session_id": fact["session_id"],
                "valid_from": fact["valid_from"],
                "status": fact["status"],
                "citation_excerpt": fact["citation_excerpt"],
            }
        )
    unique_summaries = list(dict.fromkeys(summaries))
    digest = content_hash("|".join(str(fact["id"]) for fact in selected))[:16]
    label = (
        "Preference history"
        if history_query and preference_query
        else "State history"
        if history_query
        else "Current preference evidence"
    )
    return {
        "id": f"temporal-consolidation-{digest}",
        "kind": "temporal_consolidation",
        "summary": f"{label}: " + "; ".join(unique_summaries),
        "detail_text": "\n".join(detail_lines),
        "confidence": min(float(fact["confidence"]) for fact in selected),
        "source_id": selected[-1]["source_id"],
        "session_id": selected[-1]["session_id"],
        "source_ids": list(dict.fromkeys(str(fact["source_id"]) for fact in selected)),
        "session_ids": list(
            dict.fromkeys(str(fact["session_id"]) for fact in selected if fact.get("session_id"))
        ),
        "citations": citations,
        "updated_at": selected[-1]["valid_from"],
        "speaker_role": "user",
        "derived": True,
        "authoritative_source_claims_preserved": True,
    }


def _state_predicate_for_query(query: str) -> str | None:
    mappings = (
        (r"\b(location|live|lived|moved|based)\b", "lives_in"),
        (r"\b(company|employer|workplace|work at|worked at)\b", "works_at"),
        (r"\b(role|job title|profession|occupation)\b", "role"),
        (r"\btime ?zone\b", "timezone"),
    )
    for pattern, predicate in mappings:
        if re.search(pattern, query):
            return predicate
    return None


def _merge_memory_items(*groups: list[dict], limit: int) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            item_id = str(item.get("id") or "")
            if not item_id or item_id in seen:
                continue
            seen.add(item_id)
            merged.append(item)
            if len(merged) >= max(1, min(limit, 50)):
                return merged
    return merged


def _latest_working_memory(conn, *, vault_id: str, cluster_id: str | None) -> dict | None:
    params: list[str] = [vault_id]
    cluster_clause = "cluster_id IS NULL"
    if cluster_id:
        cluster_clause = "cluster_id = ?"
        params.append(cluster_id)
    row = conn.execute(
        f"""
        SELECT *
        FROM working_memory_snapshots
        WHERE vault_id = ? AND {cluster_clause} AND status = 'active'
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        params,
    ).fetchone()
    return dict_from_row(row) if row is not None else None


def _upsert_working_memory_snapshot(
    conn,
    *,
    vault_id: str,
    cluster_id: str | None,
    scope_type: str,
    summary: str,
    source_count: int,
    memory_count: int,
) -> None:
    now = utc_now()
    if cluster_id:
        existing = conn.execute(
            "SELECT id FROM working_memory_snapshots WHERE vault_id = ? AND cluster_id = ? AND status = 'active' ORDER BY updated_at DESC LIMIT 1",
            (vault_id, cluster_id),
        ).fetchone()
    else:
        existing = conn.execute(
            "SELECT id FROM working_memory_snapshots WHERE vault_id = ? AND cluster_id IS NULL AND status = 'active' ORDER BY updated_at DESC LIMIT 1",
            (vault_id,),
        ).fetchone()
    if existing is None:
        conn.execute(
            """
            INSERT INTO working_memory_snapshots (
                id, vault_id, cluster_id, scope_type, summary, source_count, memory_count, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (f"working-memory-{uuid4()}", vault_id, cluster_id, scope_type, summary, source_count, memory_count, now, now),
        )
        return
    conn.execute(
        """
        UPDATE working_memory_snapshots
        SET summary = ?, source_count = ?, memory_count = ?, scope_type = ?, updated_at = ?
        WHERE id = ?
        """,
        (summary, source_count, memory_count, scope_type, now, existing["id"]),
    )


def _indexed_source_count(conn, *, vault_id: str, cluster_id: str | None) -> int:
    params: list[str] = [vault_id]
    cluster_clause = ""
    if cluster_id:
        cluster_clause = "AND cluster_id = ?"
        params.append(cluster_id)
    row = conn.execute(
        f"SELECT COUNT(*) AS count FROM sources WHERE vault_id = ? AND state = 'indexed' AND deleted_at IS NULL {cluster_clause}",
        params,
    ).fetchone()
    return int(row["count"] if row else 0)


def _memory_item_count(conn, *, vault_id: str, cluster_id: str | None) -> int:
    params: list[str] = [vault_id]
    cluster_clause = ""
    if cluster_id:
        cluster_clause = "AND (cluster_id = ? OR cluster_id IS NULL)"
        params.append(cluster_id)
    row = conn.execute(
        f"SELECT COUNT(*) AS count FROM memory_items WHERE vault_id = ? AND status = 'active' {cluster_clause}",
        params,
    ).fetchone()
    return int(row["count"] if row else 0)


def _source_is_memory_excluded(source: dict) -> bool:
    metadata = {}
    try:
        metadata = json.loads(source.get("parser_security_json") or "{}")
    except json.JSONDecodeError:
        metadata = {}
    if bool(metadata.get("bridge_review_approved")):
        return False
    quality_state = str(metadata.get("bridge_quality_state") or "")
    if quality_state in {"ungrounded", "unknown", "partially_grounded"}:
        return True
    labels = set(_json_list(source.get("security_labels") or "[]"))
    return "review_needed" in labels or "ungrounded_external" in labels or "partial_external" in labels


def _json_list(value) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []
