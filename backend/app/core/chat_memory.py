import json
from collections import deque
from uuid import uuid4

from backend.app.core.database import dict_from_row, utc_now
from backend.app.core.embeddings import reindex_source_chunks
from backend.app.core.encrypted_storage import (
    hydrate_chat_message_rows,
    source_from_encrypted_row,
    store_source_content_fields,
    update_source_content_fields,
)
from backend.app.core.cluster_lifecycle import (
    SYSTEM_CHATS_CLUSTER_DESCRIPTION,
    SYSTEM_CHATS_CLUSTER_NAME,
    mark_cluster_needs_update,
)
from backend.app.core.cluster_membership import move_source_cluster_membership
from backend.app.core.memory_card import summarize_text

TRANSCRIPT_RECENT_MESSAGE_LIMIT = 40
TRANSCRIPT_SUMMARY_MAX_CHARS = 1_200
TRANSCRIPT_INDEX_MAX_CHARS = 120_000
TRANSCRIPT_SUMMARY_VERSION = "bounded-v1"


def upsert_chat_transcript_sources(conn, *, vault_id: str, session_id: str) -> None:
    session = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
    if session is None:
        return
    aggregate = conn.execute(
        "SELECT COUNT(*) AS count, COALESCE(MAX(rowid), 0) AS last_rowid "
        "FROM chat_messages WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    message_count = int(aggregate["count"] or 0)
    last_rowid = int(aggregate["last_rowid"] or 0)
    if message_count == 0:
        return
    state = conn.execute(
        "SELECT * FROM chat_transcript_memory_state WHERE session_id = ? AND vault_id = ?",
        (session_id, vault_id),
    ).fetchone()
    if (
        state is not None
        and state["summary_version"] == TRANSCRIPT_SUMMARY_VERSION
        and int(state["source_message_count"] or 0) == message_count
        and int(state["last_message_rowid"] or 0) == last_rowid
    ):
        return

    clusters = _transcript_target_clusters_bounded(conn, vault_id=vault_id, session=session)
    prior_count = int(state["source_message_count"] or 0) if state is not None else 0
    prior_rowid = int(state["last_message_rowid"] or 0) if state is not None else 0
    prefix_count = int(
        conn.execute(
            "SELECT COUNT(*) AS count FROM chat_messages WHERE session_id = ? AND rowid <= ?",
            (session_id, prior_rowid),
        ).fetchone()["count"]
    )
    append_only = (
        state is not None
        and state["summary_version"] == TRANSCRIPT_SUMMARY_VERSION
        and prior_count == prefix_count
        and prior_count <= message_count
        and prior_rowid <= last_rowid
    )
    rolling_summary = ""
    if append_only:
        for cluster in clusters:
            existing = conn.execute(
                "SELECT * FROM sources WHERE id = ?",
                (f"chat-source-{session_id}-{cluster['id']}",),
            ).fetchone()
            if existing is not None:
                rolling_summary = str(source_from_encrypted_row(conn, existing).get("summary") or "")
                break
    summary_cursor = prior_rowid if append_only else 0
    while True:
        batch_rows = conn.execute(
            """
            SELECT rowid AS message_rowid, * FROM chat_messages
            WHERE session_id = ? AND rowid > ? ORDER BY rowid ASC LIMIT 100
            """,
            (session_id, summary_cursor),
        ).fetchall()
        if not batch_rows:
            break
        batch = hydrate_chat_message_rows(conn, batch_rows)
        user_text = " ".join(
            str(message["content"] or "")
            for message in batch
            if str(message["role"] or "").casefold() == "user"
        )
        if user_text:
            rolling_summary = summarize_text(
                f"{rolling_summary} {user_text}".strip(), max_chars=TRANSCRIPT_SUMMARY_MAX_CHARS
            )[:TRANSCRIPT_SUMMARY_MAX_CHARS]
        summary_cursor = int(batch_rows[-1]["message_rowid"])

    recent_rows = conn.execute(
        """
        SELECT rowid AS message_rowid, * FROM chat_messages
        WHERE session_id = ? ORDER BY rowid DESC LIMIT ?
        """,
        (session_id, TRANSCRIPT_RECENT_MESSAGE_LIMIT),
    ).fetchall()
    recent_messages = hydrate_chat_message_rows(conn, list(reversed(recent_rows)))
    recent_ids = [str(message["id"]) for message in recent_messages]
    attachments = []
    if recent_ids:
        placeholders = ",".join("?" for _ in recent_ids)
        attachments = conn.execute(
            f"""
            SELECT chat_attachments.*, sources.title AS source_title, sources.cluster_id
            FROM chat_attachments
            JOIN sources ON sources.id = chat_attachments.source_id
            WHERE chat_attachments.session_id = ?
              AND chat_attachments.message_id IN ({placeholders})
            ORDER BY chat_attachments.created_at ASC
            """,
            [session_id, *recent_ids],
        ).fetchall()
    transcript = _bounded_transcript_text(
        session, recent_messages, attachments, rolling_summary=rolling_summary,
        total_message_count=message_count,
    )
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
            "source_type": "chat_transcript",
            "state": "indexed",
            "raw_text": transcript,
            "extracted_text": transcript,
            "summary": rolling_summary or summarize_text(transcript),
            "tags": tags,
            "updated_at": now,
        }
        if existing:
            stored_payload = update_source_content_fields(
                conn,
                vault_id=vault_id,
                source_id=source_id,
                updates=payload,
                now=now,
            )
            conn.execute(
                """
                UPDATE sources
                SET title = :title,
                    state = :state,
                    raw_text = :raw_text,
                    extracted_text = :extracted_text,
                    summary = :summary,
                    tags = :tags,
                    updated_at = :updated_at
                WHERE id = :id
                """,
                stored_payload,
            )
            move_source_cluster_membership(
                conn,
                source_id=source_id,
                target_cluster_id=str(cluster["id"]),
                reason="Chat transcript scope was refreshed.",
                actor="chat_transcript_memory",
                expected_vault_id=vault_id,
                prune_empty_cluster=False,
            )
        else:
            stored_payload = store_source_content_fields(conn, payload, now=now)
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
                stored_payload,
            )
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if row is not None:
            reindex_source_chunks(conn, dict_from_row(row))
            mark_cluster_needs_update(conn, cluster["id"], "Chat transcript memory was indexed.")
    conn.execute(
        """
        INSERT INTO chat_transcript_memory_state (
            session_id, vault_id, last_message_rowid, source_message_count,
            summary_version, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            vault_id = excluded.vault_id,
            last_message_rowid = excluded.last_message_rowid,
            source_message_count = excluded.source_message_count,
            summary_version = excluded.summary_version,
            updated_at = excluded.updated_at
        """,
        (session_id, vault_id, last_rowid, message_count, TRANSCRIPT_SUMMARY_VERSION, utc_now()),
    )


def _transcript_target_clusters_bounded(conn, *, vault_id: str, session) -> list[dict]:
    cluster_ids: set[str] = set()
    if session["scope_cluster_id"]:
        cluster_ids.add(str(session["scope_cluster_id"]))
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT json_extract(item.value, '$.cluster_id') AS cluster_id
            FROM chat_messages messages, json_each(messages.clusters_used) item
            WHERE messages.session_id = ?
              AND json_extract(item.value, '$.cluster_id') IS NOT NULL
            """,
            (session["id"],),
        ).fetchall()
        cluster_ids.update(str(row["cluster_id"]) for row in rows if row["cluster_id"])
    except Exception:
        rows = conn.execute(
            "SELECT clusters_used FROM chat_messages WHERE session_id = ?",
            (session["id"],),
        )
        for row in rows:
            cluster_ids.update(
                str(item.get("cluster_id"))
                for item in _json_list(row["clusters_used"])
                if item.get("cluster_id")
            )
    if not cluster_ids:
        return [_ensure_chats_cluster(conn, vault_id)]
    placeholders = ",".join("?" for _ in cluster_ids)
    rows = conn.execute(
        f"SELECT id, name FROM clusters WHERE vault_id = ? AND id IN ({placeholders})",
        [vault_id, *sorted(cluster_ids)],
    ).fetchall()
    clusters = [dict_from_row(row) for row in rows]
    return clusters or [_ensure_chats_cluster(conn, vault_id)]


def _bounded_transcript_text(session, messages, attachments, *, rolling_summary: str, total_message_count: int) -> str:
    lines = [f"Chat transcript: {session['title']}", ""]
    if rolling_summary:
        lines.extend(["Cumulative user-memory summary:", rolling_summary, ""])
    if total_message_count > len(messages):
        lines.append(f"Recent {len(messages)} of {total_message_count} messages:")
    for message in messages:
        role = "User" if message["role"] == "user" else "Assistant"
        lines.append(f"{role}: {message['content']}")
        for attachment in attachments or []:
            if attachment["message_id"] == message["id"]:
                lines.append(
                    f"Attachment stored as source: {attachment['source_title']} ({attachment['source_id']})"
                )
        lines.append("")
    return "\n".join(lines).strip()[:TRANSCRIPT_INDEX_MAX_CHARS]


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
        """
        SELECT id, name
        FROM clusters
        WHERE vault_id = ? AND name = ? AND description = ?
        LIMIT 1
        """,
        (vault_id, SYSTEM_CHATS_CLUSTER_NAME, SYSTEM_CHATS_CLUSTER_DESCRIPTION),
    ).fetchone()
    if row is not None:
        return dict_from_row(row)
    now = utc_now()
    cluster = {
        "id": f"cluster-{uuid4()}",
        "vault_id": vault_id,
        "name": SYSTEM_CHATS_CLUSTER_NAME,
        "name_origin": "auto",
        "description": SYSTEM_CHATS_CLUSTER_DESCRIPTION,
        "color": "sand",
        "index_status": "empty",
        "profile_status": "missing",
        "cluster_summary": "",
        "cluster_glossary": "[]",
        "created_at": now,
        "updated_at": now,
    }
    conn.execute(
        """
        INSERT INTO clusters (
            id, vault_id, name, name_origin, description, color, index_status, profile_status,
            cluster_summary, cluster_glossary, created_at, updated_at
        )
        VALUES (
            :id, :vault_id, :name, :name_origin, :description, :color, :index_status, :profile_status,
            :cluster_summary, :cluster_glossary, :created_at, :updated_at
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
