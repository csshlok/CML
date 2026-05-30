import json
from uuid import uuid4

from backend.app.core.database import dict_from_row, utc_now
from backend.app.core.embeddings import reindex_source_chunks
from backend.app.core.expert_lifecycle import mark_cluster_needs_update
from backend.app.core.memory_card import summarize_text


def upsert_chat_transcript_sources(conn, *, vault_id: str, session_id: str) -> None:
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
    attachments = conn.execute(
        """
        SELECT chat_attachments.*, sources.title AS source_title, sources.cluster_id
        FROM chat_attachments
        JOIN sources ON sources.id = chat_attachments.source_id
        WHERE chat_attachments.session_id = ?
        ORDER BY chat_attachments.created_at ASC
        """,
        (session_id,),
    ).fetchall()
    transcript = _transcript_text(session, messages, attachments)
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


def _transcript_text(session, messages, attachments=None) -> str:
    lines = [f"Chat transcript: {session['title']}", ""]
    for message in messages:
        role = "User" if message["role"] == "user" else "Assistant"
        lines.append(f"{role}: {message['content']}")
        message_attachments = [
            attachment
            for attachment in (attachments or [])
            if attachment["message_id"] == message["id"]
        ]
        for attachment in message_attachments:
            lines.append(
                f"Attachment stored as source: {attachment['source_title']} ({attachment['source_id']})"
            )
        lines.append("")
    return "\n".join(lines).strip()


def _json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []
