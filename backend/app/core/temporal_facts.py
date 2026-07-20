from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.core.claim_semantics import extract_structured_claims
from backend.app.core.database import dict_from_row, utc_now


SpeakerRole = Literal["user", "assistant", "tool", "system", "external"]
AssertionKind = Literal[
    "fact", "preference", "suggestion", "action", "plan", "goal", "state"
]
Modality = Literal["asserted", "negated", "hypothetical"]
SourceType = Literal["chat_message", "source", "benchmark", "manual"]
CHAT_FACT_EXTRACTOR_VERSION = "chat-facts-v3"


class TemporalFactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vault_id: str = Field(min_length=1)
    cluster_id: str | None = None
    subject_key: str = Field(min_length=1)
    predicate_key: str = Field(min_length=1)
    object_text: str = Field(min_length=1)
    object_type: str = "text"
    assertion_kind: AssertionKind
    modality: Modality = "asserted"
    speaker_role: SpeakerRole
    source_type: SourceType
    source_id: str = Field(min_length=1)
    session_id: str | None = None
    citation_excerpt: str = ""
    observed_at: str | None = None
    valid_from: str | None = None
    supersession_key: str = ""
    supersedes_fact_id: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict = Field(default_factory=dict)

    @field_validator("subject_key", "predicate_key", "object_type", "supersession_key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        return re.sub(r"[^a-z0-9_.:-]+", "_", value.strip().lower()).strip("_")

    @field_validator("object_text", "citation_excerpt")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return " ".join(value.split())

    @model_validator(mode="after")
    def protect_speaker_provenance(self) -> "TemporalFactCreate":
        if (
            self.speaker_role == "assistant"
            and self.subject_key == "user"
            and self.assertion_kind == "action"
        ):
            raise ValueError("assistant_statement_cannot_assert_user_action")
        return self


def record_temporal_fact(
    conn: sqlite3.Connection,
    value: TemporalFactCreate | dict,
    *,
    supersede_current: bool = False,
) -> dict:
    payload = value if isinstance(value, TemporalFactCreate) else TemporalFactCreate.model_validate(value)
    envelope = _validate_source_envelope(conn, payload)
    observed_at = _iso(payload.observed_at or envelope.get("created_at") or utc_now())
    valid_from = _iso(payload.valid_from or observed_at)
    citation_excerpt = payload.citation_excerpt or str(envelope.get("content") or "")[:600]
    if envelope.get("content") and citation_excerpt not in str(envelope["content"]):
        raise ValueError("citation_excerpt_not_in_source")

    fingerprint = _fingerprint(payload, citation_excerpt, observed_at, valid_from)
    existing = conn.execute(
        "SELECT * FROM temporal_facts WHERE origin_fingerprint = ?", (fingerprint,)
    ).fetchone()
    if existing is not None:
        return _fact_dict(existing)

    fact_id = f"fact-{uuid4()}"
    prior = _resolve_prior_fact(conn, payload, supersede_current=supersede_current)
    if prior is not None and valid_from < str(prior["valid_from"]):
        raise ValueError("superseding_fact_precedes_prior_fact")

    now = utc_now()
    conn.execute(
        """
        INSERT INTO temporal_facts (
            id, vault_id, cluster_id, subject_key, predicate_key, object_text, object_type,
            assertion_kind, modality, speaker_role, source_type, source_id, session_id,
            citation_excerpt, observed_at, valid_from, valid_until, supersession_key,
            supersedes_fact_id, superseded_by_fact_id, status, confidence,
            origin_fingerprint, metadata_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL,
                  'current', ?, ?, ?, ?)
        """,
        (
            fact_id,
            payload.vault_id,
            payload.cluster_id or envelope.get("cluster_id"),
            payload.subject_key,
            payload.predicate_key,
            payload.object_text,
            payload.object_type,
            payload.assertion_kind,
            payload.modality,
            payload.speaker_role,
            payload.source_type,
            payload.source_id,
            payload.session_id or envelope.get("session_id"),
            citation_excerpt,
            observed_at,
            valid_from,
            payload.supersession_key,
            str(prior["id"]) if prior is not None else None,
            payload.confidence,
            fingerprint,
            json.dumps(payload.metadata, sort_keys=True, separators=(",", ":")),
            now,
        ),
    )
    if prior is not None:
        conn.execute(
            """
            UPDATE temporal_facts
            SET status = 'superseded', valid_until = ?, superseded_by_fact_id = ?
            WHERE id = ? AND status = 'current'
            """,
            (valid_from, fact_id, prior["id"]),
        )
    row = conn.execute("SELECT * FROM temporal_facts WHERE id = ?", (fact_id,)).fetchone()
    assert row is not None
    return _fact_dict(row)


def query_temporal_facts(
    conn: sqlite3.Connection,
    *,
    vault_id: str,
    cluster_id: str | None = None,
    subject_key: str | None = None,
    predicate_key: str | None = None,
    as_of: str | None = None,
    include_suggestions: bool = False,
    limit: int = 100,
) -> list[dict]:
    at = _iso(as_of or utc_now())
    clauses = [
        "vault_id = ?",
        "status != 'retracted'",
        "valid_from <= ?",
        "(valid_until IS NULL OR ? < valid_until)",
    ]
    params: list[object] = [vault_id, at, at]
    if cluster_id:
        clauses.append("(cluster_id = ? OR cluster_id IS NULL)")
        params.append(cluster_id)
    if subject_key:
        clauses.append("subject_key = ?")
        params.append(_key(subject_key))
    if predicate_key:
        clauses.append("predicate_key = ?")
        params.append(_key(predicate_key))
    if not include_suggestions:
        clauses.append("assertion_kind != 'suggestion'")
    params.append(max(1, min(limit, 500)))
    rows = conn.execute(
        f"""
        SELECT * FROM temporal_facts
        WHERE {' AND '.join(clauses)}
        ORDER BY valid_from DESC, created_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [_fact_dict(row) for row in rows]


def temporal_fact_history(
    conn: sqlite3.Connection,
    *,
    vault_id: str,
    supersession_key: str,
) -> list[dict]:
    rows = conn.execute(
        """
        SELECT * FROM temporal_facts
        WHERE vault_id = ? AND supersession_key = ?
        ORDER BY valid_from ASC, created_at ASC
        """,
        (vault_id, _key(supersession_key)),
    ).fetchall()
    return [_fact_dict(row) for row in rows]


def query_temporal_fact_versions(
    conn: sqlite3.Connection,
    *,
    vault_id: str,
    cluster_id: str | None = None,
    assertion_kind: AssertionKind | None = None,
    limit: int = 200,
) -> list[dict]:
    """Return provenance-preserving fact versions for explicit history questions."""
    clauses = ["vault_id = ?", "status != 'retracted'"]
    params: list[object] = [vault_id]
    if cluster_id:
        clauses.append("(cluster_id = ? OR cluster_id IS NULL)")
        params.append(cluster_id)
    if assertion_kind:
        clauses.append("assertion_kind = ?")
        params.append(assertion_kind)
    params.append(max(1, min(limit, 500)))
    rows = conn.execute(
        f"""
        SELECT * FROM temporal_facts
        WHERE {' AND '.join(clauses)}
        ORDER BY valid_from ASC, created_at ASC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [_fact_dict(row) for row in rows]


def list_reviewable_temporal_facts(
    conn: sqlite3.Connection,
    *,
    vault_id: str,
    cluster_id: str | None = None,
    limit: int = 25,
) -> list[dict]:
    clauses = ["facts.vault_id = ?", "facts.status = 'current'", "facts.assertion_kind != 'suggestion'"]
    params: list[object] = [vault_id]
    if cluster_id:
        clauses.append("facts.cluster_id = ?")
        params.append(cluster_id)
    params.append(max(1, min(limit, 100)))
    rows = conn.execute(
        f"""
        SELECT facts.*
        FROM temporal_facts facts
        WHERE {' AND '.join(clauses)}
        ORDER BY facts.observed_at DESC, facts.created_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [_fact_dict(row) for row in rows]


def correct_temporal_fact(
    conn: sqlite3.Connection,
    *,
    vault_id: str,
    fact_id: str,
    object_text: str,
    note: str = "",
    valid_from: str | None = None,
) -> dict:
    row = conn.execute(
        "SELECT * FROM temporal_facts WHERE id = ? AND vault_id = ?",
        (fact_id, vault_id),
    ).fetchone()
    if row is None:
        raise KeyError("temporal_fact_not_found")
    if row["status"] != "current":
        raise ValueError("temporal_fact_is_not_current")
    replacement_source_id = f"manual-correction-{uuid4()}"
    replacement = record_temporal_fact(
        conn,
        TemporalFactCreate(
            vault_id=vault_id,
            cluster_id=row["cluster_id"],
            subject_key=row["subject_key"],
            predicate_key=row["predicate_key"],
            object_text=object_text,
            object_type=row["object_type"],
            assertion_kind=row["assertion_kind"],
            modality=row["modality"],
            speaker_role="user",
            source_type="manual",
            source_id=replacement_source_id,
            session_id=row["session_id"],
            citation_excerpt=note.strip() or "Corrected by the user in Memory history.",
            observed_at=utc_now(),
            valid_from=valid_from or utc_now(),
            supersession_key=row["supersession_key"] or f"{row['subject_key']}:{row['predicate_key']}",
            supersedes_fact_id=fact_id,
            confidence=1.0,
            metadata={"review_action": "corrected", "original_fact_id": fact_id},
        ),
    )
    conn.execute(
        """
        INSERT INTO temporal_fact_reviews (id, vault_id, fact_id, replacement_fact_id, action, note, created_at)
        VALUES (?, ?, ?, ?, 'corrected', ?, ?)
        """,
        (f"fact-review-{uuid4()}", vault_id, fact_id, replacement["id"], note.strip(), utc_now()),
    )
    return replacement


def retract_temporal_fact(
    conn: sqlite3.Connection,
    *,
    vault_id: str,
    fact_id: str,
    note: str = "",
) -> dict:
    row = conn.execute(
        "SELECT * FROM temporal_facts WHERE id = ? AND vault_id = ?",
        (fact_id, vault_id),
    ).fetchone()
    if row is None:
        raise KeyError("temporal_fact_not_found")
    if row["status"] != "current":
        raise ValueError("temporal_fact_is_not_current")
    now = utc_now()
    conn.execute(
        "UPDATE temporal_facts SET status = 'retracted', valid_until = ? WHERE id = ?",
        (now, fact_id),
    )
    conn.execute(
        """
        INSERT INTO temporal_fact_reviews (id, vault_id, fact_id, replacement_fact_id, action, note, created_at)
        VALUES (?, ?, ?, NULL, 'retracted', ?, ?)
        """,
        (f"fact-review-{uuid4()}", vault_id, fact_id, note.strip(), now),
    )
    result = conn.execute("SELECT * FROM temporal_facts WHERE id = ?", (fact_id,)).fetchone()
    assert result is not None
    return _fact_dict(result)


def parse_as_of_query(query: str, *, reference_time: str | None = None) -> str | None:
    match = re.search(r"\bas of\s+([^?.,]+(?:,\s*\d{4})?)", query, re.IGNORECASE)
    if not match:
        return None
    raw = " ".join(match.group(1).strip().split())
    reference = datetime.fromisoformat(_iso(reference_time or utc_now()))
    relative_days = {"yesterday": 1, "last week": 7}
    if raw.lower() in relative_days:
        target = reference - timedelta(days=relative_days[raw.lower()])
        return target.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()
    if raw.lower() == "last month":
        year = reference.year if reference.month > 1 else reference.year - 1
        month = reference.month - 1 if reference.month > 1 else 12
        if month == 12:
            next_month = datetime(year + 1, 1, 1, tzinfo=UTC)
        else:
            next_month = datetime(year, month + 1, 1, tzinfo=UTC)
        return (next_month - timedelta(seconds=1)).isoformat()
    for format_string in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"):
        try:
            parsed = datetime.strptime(raw, format_string).replace(tzinfo=UTC)
        except ValueError:
            continue
        return parsed.replace(hour=23, minute=59, second=59).isoformat()
    return None


def temporal_fact_diagnostics(conn: sqlite3.Connection, *, vault_id: str) -> dict:
    status_rows = conn.execute(
        "SELECT status, COUNT(*) AS count FROM temporal_facts WHERE vault_id = ? GROUP BY status",
        (vault_id,),
    ).fetchall()
    speaker_rows = conn.execute(
        "SELECT speaker_role, COUNT(*) AS count FROM temporal_facts WHERE vault_id = ? GROUP BY speaker_role",
        (vault_id,),
    ).fetchall()
    kind_rows = conn.execute(
        "SELECT assertion_kind, COUNT(*) AS count FROM temporal_facts WHERE vault_id = ? GROUP BY assertion_kind",
        (vault_id,),
    ).fetchall()
    coverage = conn.execute(
        """
        SELECT
            COUNT(DISTINCT sessions.id) AS session_count,
            COUNT(DISTINCT state.session_id) AS indexed_session_count,
            MAX(facts.observed_at) AS latest_observed_at,
            MAX(state.processed_at) AS latest_processed_at
        FROM chat_sessions sessions
        LEFT JOIN temporal_fact_session_state state
          ON state.session_id = sessions.id AND state.vault_id = sessions.vault_id
         AND state.extractor_version = ?
        LEFT JOIN temporal_facts facts
          ON facts.session_id = sessions.id AND facts.vault_id = sessions.vault_id
        WHERE sessions.vault_id = ?
        """,
        (CHAT_FACT_EXTRACTOR_VERSION, vault_id),
    ).fetchone()
    return {
        "vault_id": vault_id,
        "extractor_version": CHAT_FACT_EXTRACTOR_VERSION,
        "status_counts": {str(row["status"]): int(row["count"]) for row in status_rows},
        "speaker_counts": {
            str(row["speaker_role"]): int(row["count"]) for row in speaker_rows
        },
        "assertion_kind_counts": {
            str(row["assertion_kind"]): int(row["count"]) for row in kind_rows
        },
        "session_count": int(coverage["session_count"] or 0),
        "indexed_session_count": int(coverage["indexed_session_count"] or 0),
        "latest_observed_at": coverage["latest_observed_at"],
        "latest_processed_at": coverage["latest_processed_at"],
    }


def sync_chat_session_temporal_facts(
    conn: sqlite3.Connection,
    *,
    vault_id: str,
    session_id: str,
    messages: list[sqlite3.Row],
) -> dict:
    desired_fingerprints: set[str] = set()
    created_ids: list[str] = []
    for message in messages:
        for candidate, supersede_current in _chat_candidates(vault_id, session_id, message):
            fact = record_temporal_fact(
                conn, candidate, supersede_current=supersede_current
            )
            desired_fingerprints.add(str(fact["origin_fingerprint"]))
            created_ids.append(str(fact["id"]))

    retained = conn.execute(
        """
        SELECT id, origin_fingerprint FROM temporal_facts
        WHERE vault_id = ? AND session_id = ? AND source_type = 'chat_message'
          AND status != 'retracted'
        """,
        (vault_id, session_id),
    ).fetchall()
    retracted = 0
    for row in retained:
        if str(row["origin_fingerprint"]) in desired_fingerprints:
            continue
        conn.execute(
            "UPDATE temporal_facts SET status = 'retracted', valid_until = ? WHERE id = ?",
            (utc_now(), row["id"]),
        )
        retracted += 1
    source_hash = temporal_fact_source_hash(messages)
    fact_count = int(
        conn.execute(
            """
            SELECT COUNT(*) AS count FROM temporal_facts
            WHERE vault_id = ? AND session_id = ? AND status != 'retracted'
            """,
            (vault_id, session_id),
        ).fetchone()["count"]
    )
    conn.execute(
        """
        INSERT INTO temporal_fact_session_state (
            session_id, vault_id, source_message_count, source_content_hash,
            extractor_version, fact_count, processed_at, last_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, '')
        ON CONFLICT(session_id) DO UPDATE SET
            vault_id = excluded.vault_id,
            source_message_count = excluded.source_message_count,
            source_content_hash = excluded.source_content_hash,
            extractor_version = excluded.extractor_version,
            fact_count = excluded.fact_count,
            processed_at = excluded.processed_at,
            last_error = ''
        """,
        (
            session_id,
            vault_id,
            len(messages),
            source_hash,
            CHAT_FACT_EXTRACTOR_VERSION,
            fact_count,
            utc_now(),
        ),
    )
    return {"fact_ids": list(dict.fromkeys(created_ids)), "retracted_count": retracted}


def temporal_fact_source_hash(messages: list[sqlite3.Row]) -> str:
    source_payload = [
        {
            "id": str(message["id"]),
            "role": str(message["role"]),
            "content": str(message["content"]),
            "created_at": str(message["created_at"]),
        }
        for message in messages
    ]
    return hashlib.sha256(
        json.dumps(source_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validate_source_envelope(conn: sqlite3.Connection, payload: TemporalFactCreate) -> dict:
    if payload.source_type == "chat_message":
        row = conn.execute(
            """
            SELECT messages.role, messages.content, messages.created_at,
                   messages.session_id, sessions.vault_id, sessions.scope_cluster_id AS cluster_id
            FROM chat_messages messages
            JOIN chat_sessions sessions ON sessions.id = messages.session_id
            WHERE messages.id = ?
            """,
            (payload.source_id,),
        ).fetchone()
        if row is None:
            raise ValueError("chat_message_source_not_found")
        envelope = dict_from_row(row)
        if envelope["vault_id"] != payload.vault_id:
            raise ValueError("source_vault_mismatch")
        if payload.session_id and envelope["session_id"] != payload.session_id:
            raise ValueError("source_session_mismatch")
        if payload.cluster_id and envelope["cluster_id"] != payload.cluster_id:
            raise ValueError("source_cluster_mismatch")
        if envelope["role"] != payload.speaker_role:
            raise ValueError("speaker_role_mismatch")
        return envelope
    if payload.source_type == "source":
        row = conn.execute(
            "SELECT vault_id, cluster_id, created_at FROM sources WHERE id = ?", (payload.source_id,)
        ).fetchone()
        if row is None:
            raise ValueError("source_not_found")
        envelope = dict_from_row(row)
        if envelope["vault_id"] != payload.vault_id:
            raise ValueError("source_vault_mismatch")
        if payload.cluster_id and envelope["cluster_id"] != payload.cluster_id:
            raise ValueError("source_cluster_mismatch")
        return envelope
    return {}


def _resolve_prior_fact(
    conn: sqlite3.Connection,
    payload: TemporalFactCreate,
    *,
    supersede_current: bool,
) -> sqlite3.Row | None:
    if payload.supersedes_fact_id:
        row = conn.execute(
            "SELECT * FROM temporal_facts WHERE id = ? AND vault_id = ?",
            (payload.supersedes_fact_id, payload.vault_id),
        ).fetchone()
        if row is None:
            raise ValueError("superseded_fact_not_found")
        if row["status"] != "current":
            raise ValueError("superseded_fact_is_not_current")
        if (
            row["subject_key"] != payload.subject_key
            or row["predicate_key"] != payload.predicate_key
        ):
            raise ValueError("superseded_fact_identity_mismatch")
        return row
    if supersede_current:
        if not payload.supersession_key:
            raise ValueError("supersession_key_required")
        return conn.execute(
            """
            SELECT * FROM temporal_facts
            WHERE vault_id = ? AND supersession_key = ? AND status = 'current'
            ORDER BY valid_from DESC, created_at DESC LIMIT 1
            """,
            (payload.vault_id, payload.supersession_key),
        ).fetchone()
    return None


def _chat_candidates(
    vault_id: str, session_id: str, message: sqlite3.Row
) -> list[tuple[TemporalFactCreate, bool]]:
    role = str(message["role"] or "").strip().lower()
    if role not in {"user", "assistant"}:
        return []
    content = " ".join(str(message["content"] or "").split())
    if not content:
        return []
    extraction_content = content
    attributed_subject = ""
    attributed = re.fullmatch(
        r"(?P<speaker>[A-Za-z][A-Za-z0-9 .'-]{0,80})\s+said,\s*[\"“](?P<quote>.*)[\"”]",
        content,
        re.IGNORECASE,
    )
    if role == "user" and attributed:
        attributed_subject = _key(attributed.group("speaker"))
        extraction_content = attributed.group("quote").strip()
    base = {
        "vault_id": vault_id,
        "speaker_role": role,
        "source_type": "chat_message",
        "source_id": str(message["id"]),
        "session_id": session_id,
        "citation_excerpt": content[:600],
        "observed_at": str(message["created_at"]),
        "valid_from": str(message["created_at"]),
    }
    candidates: list[tuple[TemporalFactCreate, bool]] = []
    for claim in extract_structured_claims(extraction_content, role):
        subject_key = attributed_subject or claim.subject_key
        supersession_key = claim.supersession_key
        if attributed_subject and supersession_key:
            supersession_key = re.sub(r"^user(?=:)", subject_key, supersession_key)
        metadata = {
            **claim.metadata,
            "extractor_version": CHAT_FACT_EXTRACTOR_VERSION,
        }
        if attributed_subject:
            metadata["attributed_speaker"] = attributed.group("speaker").strip()
        event_time = _resolve_claim_event_time(
            metadata.get("event_time_expression"), str(message["created_at"])
        )
        if event_time:
            metadata.update(event_time)
        valid_from = str(message["created_at"])
        if claim.assertion_kind == "action" and event_time and event_time.get("event_time"):
            valid_from = str(event_time["event_time"])
        candidates.append(
            (
                TemporalFactCreate(
                    **{
                        **base,
                        "citation_excerpt": claim.citation_excerpt[:600],
                        "valid_from": valid_from,
                    },
                    subject_key=subject_key,
                    predicate_key=claim.predicate_key,
                    object_text=claim.object_text,
                    assertion_kind=claim.assertion_kind,
                    modality=claim.modality,
                    supersession_key=supersession_key,
                    confidence=claim.confidence,
                    metadata=metadata,
                ),
                claim.supersede_current,
            )
        )
    return candidates


def _resolve_claim_event_time(expression: str | None, observed_at: str) -> dict[str, str]:
    if not expression:
        return {}
    reference = datetime.fromisoformat(_iso(observed_at))
    lowered = expression.casefold().strip()
    target: datetime | None = None
    if lowered == "today":
        target = reference
    elif lowered == "yesterday":
        target = reference - timedelta(days=1)
    else:
        relative = re.fullmatch(r"(\d+)\s+(days?|weeks?)\s+ago", lowered)
        if relative:
            amount = int(relative.group(1))
            days = amount * (7 if relative.group(2).startswith("week") else 1)
            target = reference - timedelta(days=days)
        explicit = re.fullmatch(r"on\s+(\d{4}-\d{2}-\d{2})", lowered)
        if explicit:
            try:
                target = datetime.strptime(explicit.group(1), "%Y-%m-%d").replace(tzinfo=UTC)
            except ValueError:
                return {"event_time_expression": expression, "event_time_precision": "unresolved"}
    if target is not None:
        resolved = target.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        return {
            "event_time_expression": expression,
            "event_time": resolved,
            "event_time_precision": "day",
            "event_time_resolved_from": _iso(observed_at),
        }
    if lowered == "last week":
        end = (reference - timedelta(days=reference.weekday() + 1)).replace(
            hour=23, minute=59, second=59, microsecond=0
        )
        start = (end - timedelta(days=6)).replace(hour=0, minute=0, second=0)
        return {
            "event_time_expression": expression,
            "event_time_start": start.isoformat(),
            "event_time_end": end.isoformat(),
            "event_time_precision": "week",
            "event_time_resolved_from": _iso(observed_at),
        }
    return {"event_time_expression": expression, "event_time_precision": "unresolved"}


def _fingerprint(
    payload: TemporalFactCreate,
    citation_excerpt: str,
    observed_at: str,
    valid_from: str,
) -> str:
    value = {
        "vault_id": payload.vault_id,
        "cluster_id": payload.cluster_id,
        "subject_key": payload.subject_key,
        "predicate_key": payload.predicate_key,
        "object_text": payload.object_text,
        "assertion_kind": payload.assertion_kind,
        "modality": payload.modality,
        "speaker_role": payload.speaker_role,
        "source_type": payload.source_type,
        "source_id": payload.source_id,
        "citation_excerpt": citation_excerpt,
        "observed_at": observed_at,
        "valid_from": valid_from,
    }
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _fact_dict(row: sqlite3.Row) -> dict:
    result = dict_from_row(row)
    result["metadata"] = json.loads(str(result.pop("metadata_json") or "{}"))
    return result


def _iso(value: str) -> str:
    normalized = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("invalid_fact_timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9_.:-]+", "_", value.strip().lower()).strip("_")
