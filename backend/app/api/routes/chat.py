from collections import OrderedDict
import json
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from backend.app.api.routes.search import semantic_search
from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.schemas import (
    ChatContextRequest,
    ChatContextResponse,
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
            "created_at": now,
            "updated_at": now,
        }
        conn.execute(
            """
            INSERT INTO chat_sessions (
                id, vault_id, title, scope_cluster_id, saved, created_at, updated_at
            )
            VALUES (
                :id, :vault_id, :title, :scope_cluster_id, :saved, :created_at, :updated_at
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
    return _session_from_row(row, [_message_from_row(message) for message in messages])


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
        assignments = ", ".join(f"{key} = :{key}" for key in updates)
        conn.execute(
            f"UPDATE chat_sessions SET {assignments} WHERE id = :id",
            {"id": session_id, **updates},
        )
    return get_chat_session(session_id)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_chat_session(session_id: str) -> None:
    with connect() as conn:
        result = conn.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Chat session not found")


@router.post("/context", response_model=ChatContextResponse)
def build_chat_context(payload: ChatContextRequest) -> dict:
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

    search_response = semantic_search(
        SemanticSearchRequest(
            vault_id=payload.vault_id,
            cluster_id=payload.cluster_id,
            query=payload.prompt,
            limit=payload.limit,
        )
    )
    results = search_response["results"]
    source_ids = list(OrderedDict.fromkeys(result["source_id"] for result in results))

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
            "snippet": _trim_snippet(result["snippet"]),
            "score": result["score"],
        }
        for result in results[:4]
    ]

    warnings = []
    if not citations:
        answer = (
            "I could not find matching indexed context for this prompt yet. "
            "Try adding sources, reindexing the vault, or asking with more specific terms."
        )
        warnings.append("No semantic citations were found.")
    else:
        answer = _build_extract_answer(payload.prompt, citations)
        warnings.append("This is a retrieval-grounded draft. Local model synthesis is not wired yet.")

    session_id = payload.session_id
    user_message_id = None
    assistant_message_id = None
    if payload.persist:
        session_id, user_message_id, assistant_message_id = _persist_chat_turn(
            vault_id=payload.vault_id,
            session_id=session_id,
            cluster_id=payload.cluster_id,
            prompt=payload.prompt,
            answer=answer,
            clusters_used=clusters_used,
            citations=citations,
            warnings=warnings,
        )

    return {
        "session_id": session_id,
        "user_message_id": user_message_id,
        "assistant_message_id": assistant_message_id,
        "prompt": payload.prompt,
        "answer": answer,
        "clusters_used": clusters_used,
        "citations": citations,
        "warnings": warnings,
    }


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
    now = utc_now()
    title = _title_from_prompt(prompt)
    with connect() as conn:
        if session_id is None:
            session_id = f"chat-{uuid4()}"
            conn.execute(
                """
                INSERT INTO chat_sessions (
                    id, vault_id, title, scope_cluster_id, saved, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 0, ?, ?)
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
        conn.execute(
            """
            INSERT INTO chat_messages (
                id, session_id, role, content, clusters_used, citations, warnings, created_at
            )
            VALUES (?, ?, 'user', ?, '[]', '[]', '[]', ?)
            """,
            (user_message_id, session_id, prompt, now),
        )
        conn.execute(
            """
            INSERT INTO chat_messages (
                id, session_id, role, content, clusters_used, citations, warnings, created_at
            )
            VALUES (?, ?, 'assistant', ?, ?, ?, ?, ?)
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
        conn.execute(
            """
            UPDATE chat_sessions
            SET updated_at = ?,
                title = CASE WHEN title = 'New chat' THEN ? ELSE title END
            WHERE id = ?
            """,
            (now, title, session_id),
        )

    return session_id, user_message_id, assistant_message_id


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
    session["messages"] = messages
    return session


def _message_from_row(row) -> dict:
    message = dict_from_row(row)
    message["clusters_used"] = _json_list(message.get("clusters_used"))
    message["citations"] = _json_list(message.get("citations"))
    message["warnings"] = _json_list(message.get("warnings"))
    return message


def _json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []
