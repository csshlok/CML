from collections import OrderedDict
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.app.api.routes.search import semantic_search
from backend.app.core.background_jobs import enqueue_job
from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.core.embeddings import (
    active_embedding_model_id,
    content_hash,
    cosine_similarity,
    decode_embedding,
    embed_text,
    require_embeddings_available,
    reindex_source_chunks,
)
from backend.app.core.expert_lifecycle import mark_cluster_needs_update
from backend.app.core.extraction import ExtractionError, extract_pages_from_path
from backend.app.core.llm_runtime import (
    LLMRuntimeError,
    generate_direct_answer,
    generate_grounded_answer,
    runtime_status,
    stream_direct_answer,
    stream_grounded_answer,
)
from backend.app.core.memory_card import generate_tags, summarize_text
from backend.app.core.vector_maintenance import active_embedding_selector
from backend.app.core.chat_retention import (
    chat_evidence_retention_policy,
    compact_retrieval_snapshots,
    enforce_chat_evidence_retention,
    paginated_messages,
)
from backend.app.core.sql import build_update_assignments
from backend.app.schemas import (
    ChatContextRequest,
    ChatContextResponse,
    ChatMessageUpdate,
    ChatSessionCreate,
    ChatSessionRead,
    ChatSessionUpdate,
    SemanticSearchRequest,
)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("/sessions", response_model=list[ChatSessionRead])
def list_chat_sessions(vault_id: str | None = None) -> list[dict]:
    clauses: list[str] = []
    params: list[str] = []
    if vault_id:
        clauses.append("vault_id = ?")
        params.append(vault_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM chat_sessions {where} ORDER BY updated_at DESC",
            params,
        ).fetchall()
    return [_session_from_row(row, messages=[]) for row in rows]


@router.post("/sessions", response_model=ChatSessionRead)
def create_chat_session(payload: ChatSessionCreate) -> dict:
    now = utc_now()
    with connect() as conn:
        _ensure_vault(conn, payload.vault_id)
        if payload.scope_cluster_id:
            _ensure_cluster(conn, payload.scope_cluster_id, payload.vault_id)
        session = {
            "id": f"chat-{uuid4()}",
            "vault_id": payload.vault_id,
            "title": payload.title or "New chat",
            "scope_cluster_id": payload.scope_cluster_id,
            "saved": 0,
            "memory_status": "idle",
            "memory_updated_at": None,
            "created_at": now,
            "updated_at": now,
        }
        conn.execute(
            """
            INSERT INTO chat_sessions (
                id, vault_id, title, scope_cluster_id, saved, memory_status, memory_updated_at, created_at, updated_at
            )
            VALUES (
                :id, :vault_id, :title, :scope_cluster_id, :saved, :memory_status,
                :memory_updated_at, :created_at, :updated_at
            )
            """,
            session,
        )
    return _session_from_row(session, messages=[])


@router.get("/sessions/{session_id}", response_model=ChatSessionRead)
def get_chat_session(session_id: str) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Chat session not found")
        messages = conn.execute(
            "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()
        hydrated_messages = [_message_from_row(conn, message) for message in messages]
    return _session_from_row(row, hydrated_messages)


@router.get("/sessions/{session_id}/timeline")
def get_chat_timeline(session_id: str) -> dict:
    with connect() as conn:
        session = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
        if session is None:
            raise HTTPException(status_code=404, detail="Chat session not found")
        messages = conn.execute(
            "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()
        generations = conn.execute(
            """
            SELECT * FROM chat_generations
            WHERE session_id = ? AND state = 'retriable'
            ORDER BY updated_at ASC
            """,
            (session_id,),
        ).fetchall()
        items = []
        for message in messages:
            hydrated = _message_from_row(conn, message)
            items.append({
                "message_type": f"{hydrated['role']}_message",
                "sort_key": hydrated["created_at"],
                **hydrated,
            })
        for generation in generations:
            row = dict_from_row(generation)
            items.append({
                "message_type": "retriable_generation",
                "id": row["id"],
                "session_id": row["session_id"],
                "prompt": row["prompt"],
                "cluster_id": row.get("cluster_id"),
                "state": row["state"],
                "error": row["error"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "sort_key": row["updated_at"] or row["created_at"],
            })
        items.sort(key=lambda item: (item.get("sort_key") or "", item.get("id") or ""))
    return {"session_id": session_id, "items": items}


@router.get("/sessions/{session_id}/messages")
def get_chat_messages_page(session_id: str, limit: int = 50, cursor: str | None = None) -> dict:
    with connect() as conn:
        session = conn.execute("SELECT id FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return paginated_messages(session_id, limit=limit, cursor=cursor)


@router.post("/retrieval-snapshots/compact")
def compact_chat_retrieval_snapshots(message_id: str | None = None, keep_latest_per_message: int = 1) -> dict:
    return compact_retrieval_snapshots(
        message_id=message_id,
        keep_latest_per_message=keep_latest_per_message,
    )


@router.get("/evidence-retention/policy")
def get_chat_evidence_retention_policy() -> dict:
    return chat_evidence_retention_policy()


@router.post("/evidence-retention/enforce")
def enforce_chat_evidence_retention_route(
    message_id: str | None = None,
    keep_latest_per_message: int = 1,
    excerpt_chars: int = 240,
) -> dict:
    return enforce_chat_evidence_retention(
        message_id=message_id,
        keep_latest_per_message=keep_latest_per_message,
        excerpt_chars=excerpt_chars,
    )


@router.patch("/sessions/{session_id}", response_model=ChatSessionRead)
def update_chat_session(session_id: str, payload: ChatSessionUpdate) -> dict:
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return get_chat_session(session_id)

    updates["updated_at"] = utc_now()
    if "saved" in updates:
        updates["saved"] = 1 if updates["saved"] else 0

    with connect() as conn:
        existing = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Chat session not found")
        if updates.get("scope_cluster_id"):
            _ensure_cluster(conn, updates["scope_cluster_id"], existing["vault_id"])
        assignments = build_update_assignments(
            updates,
            {"title", "scope_cluster_id", "saved", "updated_at"},
        )
        conn.execute(
            f"UPDATE chat_sessions SET {assignments} WHERE id = :id",
            {"id": session_id, **updates},
        )
    return get_chat_session(session_id)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_chat_session(session_id: str) -> None:
    with connect() as conn:
        attachment_rows = conn.execute(
            "SELECT source_id FROM chat_attachments WHERE session_id = ?",
            (session_id,),
        ).fetchall()
        transcript_rows = conn.execute(
            "SELECT id FROM sources WHERE id LIKE ?",
            (f"chat-source-{session_id}-%",),
        ).fetchall()
        source_ids = {row["source_id"] for row in attachment_rows}
        source_ids.update(row["id"] for row in transcript_rows)
        for source_id in source_ids:
            conn.execute("DELETE FROM source_chunks WHERE source_id = ?", (source_id,))
            conn.execute("DELETE FROM source_pages WHERE source_id = ?", (source_id,))
            conn.execute("DELETE FROM chat_attachments WHERE source_id = ?", (source_id,))
            conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        result = conn.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Chat session not found")


@router.patch("/messages/{message_id}", response_model=ChatSessionRead)
def update_chat_message(message_id: str, payload: ChatMessageUpdate) -> dict:
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        with connect() as conn:
            row = conn.execute("SELECT session_id FROM chat_messages WHERE id = ?", (message_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Chat message not found")
            session_id = row["session_id"]
        return get_chat_session(session_id)

    update_values = {}
    allowed = set()
    if "useful" in updates:
        update_values["useful"] = None if updates["useful"] is None else 1 if updates["useful"] else 0
        allowed.add("useful")
    if "saved" in updates:
        update_values["saved"] = 1 if updates["saved"] else 0
        allowed.add("saved")

    assignments = build_update_assignments(update_values, allowed)
    with connect() as conn:
        row = conn.execute("SELECT session_id FROM chat_messages WHERE id = ?", (message_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Chat message not found")
        conn.execute(f"UPDATE chat_messages SET {assignments} WHERE id = :id", {"id": message_id, **update_values})
        session_id = row["session_id"]
        if update_values.get("saved") == 1:
            now = utc_now()
            conn.execute(
                "UPDATE chat_sessions SET saved = 1, updated_at = ? WHERE id = ?",
                (now, session_id),
            )
    return get_chat_session(session_id)


@router.post("/context", response_model=ChatContextResponse)
def build_chat_context(payload: ChatContextRequest) -> dict:
    generation = _start_chat_generation(
        vault_id=payload.vault_id,
        session_id=payload.session_id,
        cluster_id=payload.cluster_id,
        prompt=payload.prompt,
        attachments=payload.attachments,
    ) if payload.persist else None
    if generation:
        payload = payload.model_copy(update={"session_id": generation["session_id"]})
    try:
        context = _build_retrieval_context(payload)
    except Exception as exc:
        if generation:
            _mark_chat_generation_retriable(generation["generation_id"], str(exc))
        raise
    citations = context["citations"]
    clusters_used = context["clusters_used"]
    warnings = context["warnings"]
    answer = context["answer"]

    session_id = payload.session_id
    user_message_id = generation["user_message_id"] if generation else None
    assistant_message_id = generation["assistant_message_id"] if generation else None
    if generation:
        _complete_chat_generation(
            generation_id=generation["generation_id"],
            session_id=generation["session_id"],
            assistant_message_id=generation["assistant_message_id"],
            vault_id=payload.vault_id,
            prompt=payload.prompt,
            answer=answer,
            clusters_used=clusters_used,
            citations=citations,
            warnings=warnings,
        )
        session_id = generation["session_id"]

    return {
        "session_id": session_id,
        "user_message_id": user_message_id,
        "assistant_message_id": assistant_message_id,
        "prompt": payload.prompt,
        "answer": answer,
        "clusters_used": clusters_used,
        "citations": citations,
        "coverage_ledger": context["coverage_ledger"],
        "attachments_stored": generation["attachment_sources"] if generation else [],
        "intent": context["intent"],
        "runtime_state": context["runtime_state"],
        "warnings": warnings,
        "memory_status": "indexing" if payload.persist else None,
    }


@router.post("/context/stream")
def stream_chat_context(payload: ChatContextRequest) -> StreamingResponse:
    def events():
        generation = None
        if payload.persist:
            generation = _start_chat_generation(
                vault_id=payload.vault_id,
                session_id=payload.session_id,
                cluster_id=payload.cluster_id,
                prompt=payload.prompt,
                attachments=payload.attachments,
            )
            active_payload = payload.model_copy(update={"session_id": generation["session_id"]})
        else:
            active_payload = payload
        context = _build_retrieval_context(active_payload, synthesize=False)
        answer_parts: list[str] = []
        warnings = list(context["warnings"])
        citations = context["citations"]
        clusters_used = context["clusters_used"]
        attachments_stored = generation["attachment_sources"] if generation else []
        yield _sse("meta", {
            "clusters_used": clusters_used,
            "citations": citations,
            "coverage_ledger": context["coverage_ledger"],
            "attachments_stored": attachments_stored,
            "intent": context["intent"],
            "runtime_state": context["runtime_state"],
            "warnings": warnings,
        })
        if context["intent"] == "general_chat" and context["runtime_state"] == "ready":
            try:
                for chunk in stream_direct_answer(prompt=active_payload.prompt):
                    answer_parts.append(chunk)
                    yield _sse("token", {"text": chunk})
                warnings.append("Answered by local LLM runtime without vault retrieval.")
            except LLMRuntimeError as exc:
                fallback = _build_runtime_unavailable_answer(active_payload.prompt, str(exc))
                warnings.append(f"Local LLM runtime became unavailable during chat: {exc}")
                for chunk in _chunk_text(fallback):
                    answer_parts.append(chunk)
                    yield _sse("token", {"text": chunk})
        elif not citations:
            for chunk in _chunk_text(context["answer"]):
                answer_parts.append(chunk)
                yield _sse("token", {"text": chunk})
        else:
            try:
                for chunk in stream_grounded_answer(
                    prompt=active_payload.prompt,
                    citations=citations,
                    clusters_used=clusters_used,
                ):
                    answer_parts.append(chunk)
                    yield _sse("token", {"text": chunk})
                warnings.append("Answered by streaming local model runtime.")
            except LLMRuntimeError as exc:
                fallback = _build_extract_answer(active_payload.prompt, citations)
                warnings.append(f"Using retrieval draft fallback because local streaming is unavailable: {exc}")
                for chunk in _chunk_text(fallback):
                    answer_parts.append(chunk)
                    yield _sse("token", {"text": chunk})

        answer = "".join(answer_parts).strip()
        session_id = generation["session_id"] if generation else payload.session_id
        user_message_id = generation["user_message_id"] if generation else None
        assistant_message_id = generation["assistant_message_id"] if generation else None
        if generation:
            _complete_chat_generation(
                generation_id=generation["generation_id"],
                session_id=generation["session_id"],
                assistant_message_id=generation["assistant_message_id"],
                vault_id=payload.vault_id,
                prompt=payload.prompt,
                answer=answer,
                clusters_used=clusters_used,
                citations=citations,
                warnings=warnings,
            )
        yield _sse("done", {
            "session_id": session_id,
            "user_message_id": user_message_id,
            "assistant_message_id": assistant_message_id,
            "answer": answer,
            "coverage_ledger": context["coverage_ledger"],
            "attachments_stored": attachments_stored,
            "intent": context["intent"],
            "runtime_state": context["runtime_state"],
            "warnings": warnings,
            "memory_status": "indexing" if payload.persist else None,
        })

    return StreamingResponse(events(), media_type="text/event-stream")


def _build_retrieval_context(payload: ChatContextRequest, synthesize: bool = True) -> dict:
    with connect() as conn:
        _ensure_vault(conn, payload.vault_id)
        if payload.cluster_id:
            _ensure_cluster(conn, payload.cluster_id, payload.vault_id)
        session = None
        if payload.session_id:
            session = conn.execute(
                "SELECT * FROM chat_sessions WHERE id = ? AND vault_id = ?",
                (payload.session_id, payload.vault_id),
            ).fetchone()
            if session is None:
                raise HTTPException(status_code=404, detail="Chat session not found")

    intent = _classify_chat_intent(payload)
    runtime = runtime_status()
    if intent == "general_chat":
        return _build_direct_chat_context(payload, runtime_state=runtime["state"], synthesize=synthesize)

    include_chat_transcripts = _should_include_chat_transcripts(payload.prompt)
    if intent != "general_chat":
        try:
            require_embeddings_available("Vault retrieval chat")
        except RuntimeError as exc:
            return _build_embedding_unavailable_context(payload, intent=intent, detail=str(exc))

    effective_limit = 12 if payload.expanded_analysis else payload.limit
    source_scores = _score_sources_for_query(
        vault_id=payload.vault_id,
        cluster_id=payload.cluster_id,
        query=payload.prompt,
        include_chat_transcripts=include_chat_transcripts,
    )
    analyzed_source_ids = [item["source_id"] for item in source_scores[: effective_limit]]

    search_response = semantic_search(
        SemanticSearchRequest(
            vault_id=payload.vault_id,
            cluster_id=payload.cluster_id,
            query=payload.prompt,
            limit=min(30, max(effective_limit * 4, 12)),
        )
    )
    results = [
        result for result in search_response["results"]
        if (not analyzed_source_ids or result["source_id"] in analyzed_source_ids)
        and (include_chat_transcripts or not _is_chat_transcript_result(result))
    ]
    source_ids = list(OrderedDict.fromkeys(result["source_id"] for result in results))
    coverage_ledger = _build_coverage_ledger(
        vault_id=payload.vault_id,
        cluster_id=payload.cluster_id,
        analyzed_source_ids=analyzed_source_ids,
    )

    clusters_used = []
    if results:
        with connect() as conn:
            rows = conn.execute(
                f"""
                SELECT DISTINCT clusters.id, clusters.name
                FROM clusters
                JOIN sources ON sources.cluster_id = clusters.id
                WHERE sources.id IN ({",".join("?" for _ in source_ids)})
                """,
                source_ids,
            ).fetchall()
        clusters_used = [
            {
                "cluster_id": row["id"],
                "cluster_name": row["name"],
                "reason": "semantic match",
            }
            for row in rows
        ]

    citations = [
        {
            "source_id": result["source_id"],
            "source_title": result["source_title"],
            "chunk_id": result.get("chunk_id"),
            "page_id": result.get("page_id"),
            "page_number": result.get("page_number"),
            "snippet": _trim_snippet(result["snippet"]),
            "score": result["score"],
            "state": "current",
        }
        for result in results[:4]
    ]

    warnings = []
    if payload.expanded_analysis:
        warnings.append("Expanded analysis mode: scored every indexed source in scope before selecting the analysis set.")
        _queue_expanded_analysis_job(
            vault_id=payload.vault_id,
            cluster_id=payload.cluster_id,
            query=payload.prompt,
            limit=effective_limit,
        )
    warnings.append(
        "Coverage ledger: considered "
        f"{coverage_ledger['sources_considered']} source(s), analyzed "
        f"{coverage_ledger['sources_analyzed']} source(s), marked "
        f"{coverage_ledger['sources_low_relevance']} low relevance."
    )
    if not citations:
        answer = (
            "I could not find matching indexed context for this prompt yet. "
            "Try adding sources, reindexing the vault, or asking with more specific terms."
        )
        warnings.append("No semantic citations were found.")
    elif synthesize:
        try:
            result = generate_grounded_answer(
                prompt=payload.prompt,
                citations=citations,
                clusters_used=clusters_used,
            )
            answer = result.text
            warnings.append(f"Answered by local model runtime: {result.provider} / {result.model}.")
        except LLMRuntimeError as exc:
            answer = _build_extract_answer(payload.prompt, citations)
            warnings.append(f"Using retrieval draft fallback because local synthesis is unavailable: {exc}")
    else:
        answer = _build_extract_answer(payload.prompt, citations)

    return {
        "answer": answer,
        "clusters_used": clusters_used,
        "citations": citations,
        "coverage_ledger": coverage_ledger,
        "intent": intent,
        "runtime_state": runtime["state"],
        "warnings": warnings,
    }


def _build_embedding_unavailable_context(payload: ChatContextRequest, *, intent: str, detail: str) -> dict:
    coverage_ledger = _build_coverage_ledger(
        vault_id=payload.vault_id,
        cluster_id=payload.cluster_id,
        analyzed_source_ids=[],
    )
    return {
        "answer": (
            "This question needs your local memory, but semantic search is unavailable because the embedding model "
            "is missing or not configured. Set up the embedding model to get a sourced answer, or ask a general question."
        ),
        "clusters_used": [],
        "citations": [],
        "coverage_ledger": {**coverage_ledger, "sources_analyzed": 0, "sources_low_relevance": coverage_ledger["sources_considered"]},
        "intent": intent,
        "runtime_state": runtime_status()["state"],
        "warnings": [detail],
    }


def _queue_expanded_analysis_job(
    *,
    vault_id: str,
    cluster_id: str | None,
    query: str,
    limit: int,
) -> None:
    fingerprint = content_hash(f"{vault_id}|{cluster_id or ''}|{query.strip().lower()}|{limit}")
    with connect() as conn:
        enqueue_job(
            conn,
            job_type="expanded_analysis",
            payload={
                "vault_id": vault_id,
                "cluster_id": cluster_id,
                "query": query,
                "limit": limit,
            },
            dedupe_key=f"expanded-analysis:{fingerprint}",
            scope_id=f"{vault_id}:{cluster_id or 'all'}",
            user_initiated=True,
        )


def _build_direct_chat_context(payload: ChatContextRequest, *, runtime_state: str, synthesize: bool) -> dict:
    coverage_ledger = _build_coverage_ledger(
        vault_id=payload.vault_id,
        cluster_id=payload.cluster_id,
        analyzed_source_ids=[],
    )
    warnings = ["Vault retrieval was not used for this general chat message."]
    if _is_conversational_prompt(payload.prompt):
        answer = _build_direct_chat_answer(payload.prompt)
        warnings.append("Answered directly because this was conversational chat.")
    elif synthesize and runtime_state == "ready":
        try:
            result = generate_direct_answer(prompt=payload.prompt)
            answer = result.text
            warnings.append(f"Answered by local LLM runtime: {result.provider} / {result.model}.")
        except LLMRuntimeError as exc:
            answer = _build_runtime_unavailable_answer(payload.prompt, str(exc))
            warnings.append(f"Local LLM runtime is unavailable: {exc}")
    elif runtime_state == "ready":
        answer = ""
    else:
        answer = _build_runtime_unavailable_answer(payload.prompt, runtime_state)
        warnings.append("Local LLM runtime is unavailable; general chat is in degraded mode.")
    return {
        "answer": answer,
        "clusters_used": [],
        "citations": [],
        "coverage_ledger": {**coverage_ledger, "sources_analyzed": 0, "sources_low_relevance": coverage_ledger["sources_considered"]},
        "intent": "general_chat",
        "runtime_state": runtime_state,
        "warnings": warnings,
    }


def _build_coverage_ledger(*, vault_id: str, cluster_id: str | None, analyzed_source_ids: list[str]) -> dict:
    params: list[str] = [vault_id]
    cluster_clause = ""
    if cluster_id:
        cluster_clause = "AND cluster_id = ?"
        params.append(cluster_id)
    with connect() as conn:
        row = conn.execute(
            f"""
            SELECT COUNT(DISTINCT id) AS source_count
            FROM sources
            WHERE vault_id = ? AND state = 'indexed' AND deleted_at IS NULL {cluster_clause}
            """,
            params,
        ).fetchone()
    considered = int(row["source_count"] if row else 0)
    analyzed = min(len(set(analyzed_source_ids)), considered)
    return {
        "sources_considered": considered,
        "sources_analyzed": analyzed,
        "sources_low_relevance": max(considered - analyzed, 0),
        "relevance_threshold": 0.0,
        "scope": "cluster" if cluster_id else "vault",
    }


def _score_sources_for_query(
    *,
    vault_id: str,
    cluster_id: str | None,
    query: str,
    include_chat_transcripts: bool = False,
) -> list[dict]:
    query_vector = embed_text(query)
    selector = active_embedding_selector()
    params: list[str] = [vault_id]
    cluster_clause = ""
    if cluster_id:
        cluster_clause = "AND chunks.cluster_id = ?"
        params.append(cluster_id)
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT chunks.source_id, chunks.embedding, sources.source_type, sources.tags
            FROM source_chunks chunks
            JOIN sources ON sources.id = chunks.source_id
            WHERE chunks.vault_id = ?
              AND sources.state = 'indexed'
              AND sources.deleted_at IS NULL
              AND chunks.embedding_model_id = ?
              AND chunks.index_version = ?
              {cluster_clause}
            """,
            [params[0], selector["embedding_model_id"], selector["index_version"], *params[1:]],
        ).fetchall()
    best_by_source: dict[str, float] = {}
    for row in rows:
        if not include_chat_transcripts and _is_chat_transcript_source(row):
            continue
        score = cosine_similarity(query_vector, decode_embedding(row["embedding"]))
        source_id = row["source_id"]
        if score > best_by_source.get(source_id, -1):
            best_by_source[source_id] = score
    scored = [
        {"source_id": source_id, "score": round(score, 4)}
        for source_id, score in best_by_source.items()
        if score > 0
    ]
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored


def _is_conversational_prompt(prompt: str) -> bool:
    normalized = " ".join(prompt.lower().strip().split())
    trimmed = normalized.strip(" .!?")
    if trimmed in {
        "hi",
        "hello",
        "hey",
        "yo",
        "sup",
        "good morning",
        "good afternoon",
        "good evening",
        "thanks",
        "thank you",
        "ok",
        "okay",
    }:
        return True
    return False


def _classify_chat_intent(payload: ChatContextRequest) -> str:
    prompt = payload.prompt.lower()
    if payload.attachments:
        return "attachment_ingestion"
    if payload.expanded_analysis:
        return "expanded_analysis"
    if payload.cluster_id:
        return "cluster_question"
    if _is_conversational_prompt(payload.prompt):
        return "general_chat"
    retrieval_markers = (
        "vault",
        "source",
        "sources",
        "cluster",
        "clusters",
        "document",
        "documents",
        "file",
        "files",
        "pdf",
        "note",
        "notes",
        "citation",
        "citations",
        "context",
        "indexed",
        "stored",
        "memory",
        "summarize my",
        "what do you know about",
        "what context",
        "according to",
        "based on",
    )
    if any(marker in prompt for marker in retrieval_markers):
        return "vault_question"
    return "general_chat"


def _should_include_chat_transcripts(prompt: str) -> bool:
    normalized = prompt.lower()
    return any(
        phrase in normalized
        for phrase in (
            "previous chat",
            "chat history",
            "our conversation",
            "earlier conversation",
            "what did i ask",
            "what did we discuss",
            "transcript",
        )
    )


def _is_chat_transcript_result(result: dict) -> bool:
    return str(result.get("source_id") or "").startswith("chat-source-")


def _is_chat_transcript_source(row) -> bool:
    tags = row["tags"] if "tags" in row.keys() else ""
    return str(row["source_id"]).startswith("chat-source-") or "TRANSCRIPT" in str(tags)


def _build_direct_chat_answer(prompt: str) -> str:
    trimmed = prompt.strip().lower().strip(" .!?")
    if trimmed in {"hi", "hello", "hey", "yo", "sup"}:
        return "Hello. What do you want to work on in your vault?"
    if trimmed in {"thanks", "thank you"}:
        return "You are welcome."
    if trimmed in {"ok", "okay"}:
        return "Okay. Send me what you want to work on next."
    return "I am here. Ask me anything, or attach a file if you want me to store and use it."


def _build_runtime_unavailable_answer(prompt: str, detail: str) -> str:
    if _is_conversational_prompt(prompt):
        return _build_direct_chat_answer(prompt)
    return (
        "The local LLM runtime is not available, so I cannot answer this as a general chatbot yet. "
        "Start or configure a local model runtime, then retry this message. "
        f"Runtime state: {detail}"
    )


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def _chunk_text(text: str, size: int = 18):
    words = text.split(" ")
    chunk = ""
    for word in words:
        next_chunk = f"{chunk} {word}".strip()
        if len(next_chunk) >= size:
            yield next_chunk + " "
            chunk = ""
        else:
            chunk = next_chunk
    if chunk:
        yield chunk


def _trim_snippet(text: str, limit: int = 420) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "..."


def _build_extract_answer(prompt: str, citations: list[dict]) -> str:
    lead = f"Based on the closest local context for: \"{prompt}\""
    points = []
    for index, citation in enumerate(citations[:3], start=1):
        points.append(f"{index}. {citation['snippet']}")
    return lead + "\n\n" + "\n".join(points)


def _persist_chat_turn(
    *,
    vault_id: str,
    session_id: str | None,
    cluster_id: str | None,
    prompt: str,
    answer: str,
    clusters_used: list[dict],
    citations: list[dict],
    warnings: list[str],
) -> tuple[str, str, str]:
    generation = _start_chat_generation(
        vault_id=vault_id,
        session_id=session_id,
        cluster_id=cluster_id,
        prompt=prompt,
        attachments=[],
    )
    _complete_chat_generation(
        generation_id=generation["generation_id"],
        session_id=generation["session_id"],
        assistant_message_id=generation["assistant_message_id"],
        vault_id=vault_id,
        prompt=prompt,
        answer=answer,
        clusters_used=clusters_used,
        citations=citations,
        warnings=warnings,
    )
    return generation["session_id"], generation["user_message_id"], generation["assistant_message_id"]


def _start_chat_generation(
    *,
    vault_id: str,
    session_id: str | None,
    cluster_id: str | None,
    prompt: str,
    attachments: list | None = None,
) -> dict:
    now = utc_now()
    title = _title_from_prompt(prompt)
    with connect() as conn:
        _ensure_vault(conn, vault_id)
        if session_id is None:
            session_id = f"chat-{uuid4()}"
            conn.execute(
                """
                INSERT INTO chat_sessions (
                    id, vault_id, title, scope_cluster_id, saved, memory_status, memory_updated_at,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 0, 'idle', NULL, ?, ?)
                """,
                (session_id, vault_id, title, cluster_id, now, now),
            )
        else:
            session = conn.execute(
                "SELECT id FROM chat_sessions WHERE id = ? AND vault_id = ?",
                (session_id, vault_id),
            ).fetchone()
            if session is None:
                raise HTTPException(status_code=404, detail="Chat session not found")

        user_message_id = f"msg-{uuid4()}"
        assistant_message_id = f"msg-{uuid4()}"
        generation_id = f"gen-{uuid4()}"
        runtime = runtime_status()
        conn.execute(
            """
            INSERT INTO chat_messages (
                id, session_id, role, content, clusters_used, citations, warnings, useful, saved, created_at
            )
            VALUES (?, ?, 'user', ?, '[]', '[]', '[]', NULL, 0, ?)
            """,
            (user_message_id, session_id, prompt, now),
        )
        attachment_sources = _ingest_chat_attachments(
            conn,
            vault_id=vault_id,
            session_id=session_id,
            message_id=user_message_id,
            default_cluster_id=cluster_id,
            attachments=attachments or [],
            now=now,
        )
        conn.execute(
            """
            INSERT INTO chat_generations (
                id, session_id, user_message_id, assistant_message_id, vault_id, prompt, state,
                runtime_provider, runtime_model, error, heartbeat_at, created_at, updated_at,
                completed_at
            )
            VALUES (?, ?, ?, NULL, ?, ?, 'in_flight', ?, ?, '', ?, ?, ?, NULL)
            """,
            (
                generation_id,
                session_id,
                user_message_id,
                vault_id,
                prompt,
                runtime["provider"],
                runtime["model"],
                now,
                now,
                now,
            ),
        )
        conn.execute(
            """
            UPDATE chat_sessions
            SET updated_at = ?,
                title = CASE WHEN title = 'New chat' THEN ? ELSE title END
            WHERE id = ?
            """,
            (now, title, session_id),
        )

    return {
        "generation_id": generation_id,
        "session_id": session_id,
        "user_message_id": user_message_id,
        "assistant_message_id": assistant_message_id,
        "attachment_sources": attachment_sources,
    }


def _complete_chat_generation(
    *,
    generation_id: str,
    session_id: str,
    assistant_message_id: str,
    vault_id: str,
    prompt: str,
    answer: str,
    clusters_used: list[dict],
    citations: list[dict],
    warnings: list[str],
) -> None:
    now = utc_now()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO chat_messages (
                id, session_id, role, content, clusters_used, citations, warnings, useful, saved, created_at
            )
            VALUES (?, ?, 'assistant', ?, ?, ?, ?, NULL, 0, ?)
            """,
            (
                assistant_message_id,
                session_id,
                answer,
                json.dumps(clusters_used),
                json.dumps(citations),
                json.dumps(warnings),
                now,
            ),
        )
        _write_retrieval_snapshot(
            conn,
            message_id=assistant_message_id,
            session_id=session_id,
            vault_id=vault_id,
            query=prompt,
            citations=citations,
            now=now,
        )
        conn.execute(
            """
            UPDATE chat_generations
            SET state = 'completed', assistant_message_id = ?, completed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (assistant_message_id, now, now, generation_id),
        )
        conn.execute(
            "UPDATE chat_sessions SET memory_status = 'indexing', memory_updated_at = ? WHERE id = ?",
            (now, session_id),
        )
        enqueue_job(
            conn,
            job_type="chat_transcript_memory",
            payload={"vault_id": vault_id, "session_id": session_id},
            dedupe_key=f"chat-memory:{session_id}",
        )


def _mark_chat_generation_retriable(generation_id: str, error: str) -> None:
    now = utc_now()
    with connect() as conn:
        conn.execute(
            """
            UPDATE chat_generations
            SET state = 'retriable',
                error = ?,
                updated_at = ?
            WHERE id = ? AND state = 'in_flight'
            """,
            (error[:1000], now, generation_id),
        )


def _write_retrieval_snapshot(
    conn,
    *,
    message_id: str,
    session_id: str,
    vault_id: str,
    query: str,
    citations: list[dict],
    now: str,
) -> None:
    snapshot_id = f"snapshot-{uuid4()}"
    conn.execute(
        """
        INSERT INTO retrieval_snapshots (
            id, message_id, session_id, vault_id, query, retrieval_mode,
            embedding_model_id, token_budget, created_at
        )
        VALUES (?, ?, ?, ?, ?, 'semantic', ?, NULL, ?)
        """,
        (snapshot_id, message_id, session_id, vault_id, query, active_embedding_model_id(), now),
    )
    for rank, citation in enumerate(citations, start=1):
        conn.execute(
            """
            INSERT INTO retrieval_snapshot_items (
                id, snapshot_id, source_id, chunk_id, page_id, source_title_at_answer_time,
                page_number, snippet_hash, short_snippet_excerpt, relevance_score, item_rank,
                state, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"snapshot-item-{uuid4()}",
                snapshot_id,
                citation.get("source_id"),
                citation.get("chunk_id"),
                citation.get("page_id"),
                citation.get("source_title") or "",
                citation.get("page_number"),
                content_hash(citation.get("snippet") or ""),
                _trim_snippet(citation.get("snippet") or "", limit=260),
                float(citation.get("score") or 0),
                rank,
                citation.get("state") or "current",
                now,
            ),
        )


def _ingest_chat_attachments(
    conn,
    *,
    vault_id: str,
    session_id: str,
    message_id: str,
    default_cluster_id: str | None,
    attachments: list,
    now: str,
) -> list[dict]:
    try:
        require_embeddings_available("Chat attachment ingestion")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    stored_sources: list[dict] = []
    for attachment in attachments:
        path = str(getattr(attachment, "path", "") or "").strip()
        if not path:
            continue
        target_cluster_id = str(getattr(attachment, "cluster_id", "") or default_cluster_id or "").strip() or None
        if target_cluster_id:
            _ensure_cluster(conn, target_cluster_id, vault_id)
        try:
            title, pages = extract_pages_from_path(path)
        except ExtractionError as exc:
            raise HTTPException(status_code=400, detail=f"Could not read chat attachment {Path(path).name}: {exc}") from exc
        text = "\n\n".join(page for page in pages if page.strip()).strip()
        if not text:
            raise HTTPException(status_code=400, detail=f"Chat attachment {Path(path).name} had no readable text.")
        checksum = _file_checksum(Path(path))
        existing = conn.execute(
            """
            SELECT * FROM sources
            WHERE vault_id = ? AND checksum = ? AND deleted_at IS NULL
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (vault_id, checksum),
        ).fetchone()
        if existing is not None:
            source = dict_from_row(existing)
            if target_cluster_id and source.get("cluster_id") != target_cluster_id:
                conn.execute(
                    "UPDATE sources SET cluster_id = ?, updated_at = ? WHERE id = ?",
                    (target_cluster_id, now, source["id"]),
                )
                source["cluster_id"] = target_cluster_id
        else:
            source = {
                "id": f"source-{uuid4()}",
                "vault_id": vault_id,
                "cluster_id": target_cluster_id,
                "title": title,
                "source_type": _source_type_for_suffix(Path(path).suffix.lower()),
                "state": "indexed",
                "original_path": path,
                "url": None,
                "checksum": checksum,
                "raw_text": text,
                "extracted_text": text,
                "summary": summarize_text(text),
                "tags": json.dumps(generate_tags(title, text, "file") + ["CHAT_ATTACHMENT"]),
                "cover_image_url": None,
                "created_at": now,
                "updated_at": now,
            }
            conn.execute(
                """
                INSERT INTO sources (
                    id, vault_id, cluster_id, title, source_type, state, original_path, url,
                    checksum, raw_text, extracted_text, summary, tags, cover_image_url,
                    created_at, updated_at
                )
                VALUES (
                    :id, :vault_id, :cluster_id, :title, :source_type, :state, :original_path,
                    :url, :checksum, :raw_text, :extracted_text, :summary, :tags,
                    :cover_image_url, :created_at, :updated_at
                )
                """,
                source,
            )
            _replace_source_pages(conn, source_id=source["id"], vault_id=vault_id, page_texts=pages, now=now)
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source["id"],)).fetchone()
        if row is not None:
            source = dict_from_row(row)
            reindex_source_chunks(conn, source)
        conn.execute(
            """
            INSERT INTO chat_attachments (
                id, session_id, message_id, source_id, file_name, original_path, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (f"chat-attachment-{uuid4()}", session_id, message_id, source["id"], title, path, now),
        )
        if source.get("cluster_id"):
            mark_cluster_needs_update(conn, source["cluster_id"], "Chat attachment was added to this cluster.")
        stored_sources.append({"source_id": source["id"], "title": source["title"], "cluster_id": source.get("cluster_id")})
    return stored_sources


def _replace_source_pages(conn, *, source_id: str, vault_id: str, page_texts: list[str], now: str) -> None:
    conn.execute("DELETE FROM source_pages WHERE source_id = ?", (source_id,))
    for index, text in enumerate(page_texts, start=1):
        page_text = (text or "").strip()
        if not page_text:
            continue
        conn.execute(
            """
            INSERT INTO source_pages (
                id, source_id, vault_id, page_number, raw_text, extraction_version,
                content_hash, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'v1', ?, ?, ?)
            """,
            (
                f"page-{uuid4()}",
                source_id,
                vault_id,
                index,
                page_text,
                content_hash(page_text),
                now,
                now,
            ),
        )


def _file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_type_for_suffix(suffix: str) -> str:
    if suffix in {".md", ".markdown", ".txt", ".text"}:
        return "note"
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}:
        return "image"
    if suffix in {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"}:
        return "audio"
    if suffix in {".mp4", ".mov", ".webm"}:
        return "video"
    if suffix in {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".cs", ".cpp", ".c"}:
        return "code"
    return "file"


def _upsert_chat_transcript_sources(conn, *, vault_id: str, session_id: str) -> None:
    session = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
    if session is None:
        return
    messages = conn.execute(
        "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC",
        (session_id,),
    ).fetchall()
    if not messages:
        return

    clusters = _transcript_target_clusters(conn, vault_id=vault_id, session=session, messages=messages)
    transcript = _transcript_text(session, messages)
    now = utc_now()
    for cluster in clusters:
        source_id = f"chat-source-{session_id}-{cluster['id']}"
        title = f"Chat transcript - {session['title']} - {cluster['name']}"[:240]
        tags = json.dumps(["CHAT", "TRANSCRIPT", cluster["name"].upper()[:40]])
        existing = conn.execute("SELECT id FROM sources WHERE id = ?", (source_id,)).fetchone()
        payload = {
            "id": source_id,
            "vault_id": vault_id,
            "cluster_id": cluster["id"],
            "title": title,
            "source_type": "note",
            "state": "indexed",
            "raw_text": transcript,
            "extracted_text": transcript,
            "summary": summarize_text(transcript),
            "tags": tags,
            "updated_at": now,
        }
        if existing:
            conn.execute(
                """
                UPDATE sources
                SET cluster_id = :cluster_id,
                    title = :title,
                    state = :state,
                    raw_text = :raw_text,
                    extracted_text = :extracted_text,
                    summary = :summary,
                    tags = :tags,
                    updated_at = :updated_at
                WHERE id = :id
                """,
                payload,
            )
        else:
            conn.execute(
                """
                INSERT INTO sources (
                    id, vault_id, cluster_id, title, source_type, state, original_path, url,
                    raw_text, extracted_text, summary, tags, cover_image_url, created_at, updated_at
                )
                VALUES (
                    :id, :vault_id, :cluster_id, :title, :source_type, :state, NULL, NULL,
                    :raw_text, :extracted_text, :summary, :tags, NULL, :updated_at, :updated_at
                )
                """,
                payload,
            )
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if row is not None:
            from backend.app.core.embeddings import reindex_source_chunks

            reindex_source_chunks(conn, dict_from_row(row))
            mark_cluster_needs_update(conn, cluster["id"], "Chat transcript memory was indexed.")


def _transcript_target_clusters(conn, *, vault_id: str, session, messages) -> list[dict]:
    cluster_ids: list[str] = []
    if session["scope_cluster_id"]:
        cluster_ids.append(session["scope_cluster_id"])
    for message in messages:
        for cluster in _json_list(message["clusters_used"]):
            cluster_id = cluster.get("cluster_id")
            if cluster_id and cluster_id not in cluster_ids:
                cluster_ids.append(cluster_id)

    if not cluster_ids:
        return [_ensure_chats_cluster(conn, vault_id)]

    rows = conn.execute(
        f"SELECT id, name FROM clusters WHERE vault_id = ? AND id IN ({','.join('?' for _ in cluster_ids)})",
        [vault_id, *cluster_ids],
    ).fetchall()
    clusters = [dict_from_row(row) for row in rows]
    return clusters or [_ensure_chats_cluster(conn, vault_id)]


def _ensure_chats_cluster(conn, vault_id: str) -> dict:
    row = conn.execute(
        "SELECT id, name FROM clusters WHERE vault_id = ? AND name = 'Chats' LIMIT 1",
        (vault_id,),
    ).fetchone()
    if row is not None:
        return dict_from_row(row)
    now = utc_now()
    cluster = {
        "id": f"cluster-{uuid4()}",
        "vault_id": vault_id,
        "name": "Chats",
        "description": "Chat transcripts that were not scoped to a specific context cluster.",
        "color": "sand",
        "expert_status": "setting-up",
        "created_at": now,
        "updated_at": now,
    }
    conn.execute(
        """
        INSERT INTO clusters (
            id, vault_id, name, description, color, expert_status, created_at, updated_at
        )
        VALUES (
            :id, :vault_id, :name, :description, :color, :expert_status, :created_at, :updated_at
        )
        """,
        cluster,
    )
    return {"id": cluster["id"], "name": cluster["name"]}


def _transcript_text(session, messages) -> str:
    lines = [f"Chat transcript: {session['title']}", ""]
    for message in messages:
        role = "User" if message["role"] == "user" else "Assistant"
        lines.append(f"{role}: {message['content']}")
        lines.append("")
    return "\n".join(lines).strip()


def _title_from_prompt(prompt: str) -> str:
    cleaned = " ".join(prompt.split())
    if not cleaned:
        return "New chat"
    return cleaned[:57].rstrip() + "..." if len(cleaned) > 60 else cleaned


def _ensure_vault(conn, vault_id: str) -> None:
    vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone()
    if vault is None:
        raise HTTPException(status_code=404, detail="Vault not found")


def _ensure_cluster(conn, cluster_id: str, vault_id: str) -> None:
    cluster = conn.execute(
        "SELECT id FROM clusters WHERE id = ? AND vault_id = ?",
        (cluster_id, vault_id),
    ).fetchone()
    if cluster is None:
        raise HTTPException(status_code=404, detail="Cluster not found")


def _session_from_row(row, messages: list[dict]) -> dict:
    session = dict_from_row(row) if hasattr(row, "keys") else dict(row)
    session["saved"] = bool(session["saved"])
    session["memory_status"] = session.get("memory_status") or "idle"
    session["memory_updated_at"] = session.get("memory_updated_at")
    session["messages"] = messages
    return session


def _message_from_row(conn, row) -> dict:
    message = dict_from_row(row)
    message["clusters_used"] = _json_list(message.get("clusters_used"))
    message["citations"] = _snapshot_citations_for_message(conn, message) or _json_list(message.get("citations"))
    message["warnings"] = _json_list(message.get("warnings"))
    message["useful"] = None if message.get("useful") is None else bool(message["useful"])
    message["saved"] = bool(message.get("saved", 0))
    return message


def _snapshot_citations_for_message(conn, message: dict) -> list[dict]:
    if message.get("role") != "assistant":
        return []
    snapshot = conn.execute(
        "SELECT * FROM retrieval_snapshots WHERE message_id = ? ORDER BY created_at DESC LIMIT 1",
        (message["id"],),
    ).fetchone()
    if snapshot is None:
        return []
    rows = conn.execute(
        """
        SELECT
            items.*,
            sources.deleted_at AS source_deleted_at,
            sources.updated_at AS source_updated_at,
            chunks.indexed_at AS chunk_indexed_at
        FROM retrieval_snapshot_items items
        LEFT JOIN sources ON sources.id = items.source_id
        LEFT JOIN source_chunks chunks ON chunks.id = items.chunk_id
        WHERE items.snapshot_id = ?
        ORDER BY items.item_rank ASC
        """,
        (snapshot["id"],),
    ).fetchall()
    citations = []
    for row in rows:
        state = "current"
        if row["source_id"] is None or row["source_deleted_at"]:
            state = "source_deleted"
        elif row["chunk_id"] and row["chunk_indexed_at"] is None:
            state = "source_reindexed"
        elif row["source_updated_at"] and row["source_updated_at"] > snapshot["created_at"]:
            state = "source_reindexed"
        citations.append(
            {
                "source_id": row["source_id"] or "",
                "source_title": row["source_title_at_answer_time"],
                "chunk_id": row["chunk_id"],
                "page_id": row["page_id"],
                "page_number": row["page_number"],
                "snippet": row["short_snippet_excerpt"],
                "score": row["relevance_score"],
                "state": state,
            }
        )
    return citations


def _json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []
