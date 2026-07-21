from __future__ import annotations

import hashlib
import json
import sqlite3

from backend.app.core.atomic_memory import (
    ATOMIC_MEMORY_VERSION,
    AtomicCitation,
    AtomicFact,
    AtomicQuantity,
    compile_deterministic_atomic_session,
    materialize_progressive_counters,
    source_content_hash,
)
from backend.app.core.database import utc_now


def _fingerprint(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _session_payload(session_id: str, messages: list[sqlite3.Row]) -> dict:
    first_date = next(
        (str(row["created_at"])[:10] for row in messages if str(row["created_at"] or "")),
        "1970-01-01",
    )
    return {
        "session_id": session_id,
        "date": first_date,
        "turns": [
            {"role": str(row["role"]), "content": str(row["content"] or "")}
            for row in messages
        ],
    }


def sync_chat_session_atomic_memory(
    conn: sqlite3.Connection,
    *,
    vault_id: str,
    session_id: str,
    messages: list[sqlite3.Row],
) -> dict:
    """Regenerate the lossless atomic tier for one production chat session."""
    session = conn.execute(
        "SELECT scope_cluster_id FROM chat_sessions WHERE id = ? AND vault_id = ?",
        (session_id, vault_id),
    ).fetchone()
    if session is None:
        raise ValueError("chat_session_not_found")

    payload = _session_payload(session_id, messages)
    extraction = compile_deterministic_atomic_session(payload)
    compiled_source_hash = source_content_hash(
        payload["session_id"], payload["date"], payload["turns"]
    )
    message_ids = [str(row["id"]) for row in messages]
    desired_facts: set[str] = set()
    desired_units: set[str] = set()
    now = utc_now()

    for fact in extraction.facts:
        source_message_id = message_ids[fact.citation.turn_index]
        serialized = fact.model_dump(mode="json")
        origin = _fingerprint(
            {"compiler_version": ATOMIC_MEMORY_VERSION, "fact": serialized}
        )
        desired_facts.add(origin)
        quantity = fact.quantity
        conn.execute(
            """
            INSERT INTO atomic_memory_facts (
                id, vault_id, cluster_id, session_id, source_message_id, compiler_fact_id,
                turn_index, speaker_role, session_date, citation_excerpt,
                source_content_hash, subject_key, predicate_key, object_text, fact_kind,
                assertion_mode, event_date, observed_date, quantity_value, quantity_unit,
                quantity_role, qualifiers_json, supersession_key, confidence,
                compiler_version, origin_fingerprint, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, 'current', ?, ?)
            ON CONFLICT(origin_fingerprint) DO UPDATE SET
                status = 'current', updated_at = excluded.updated_at
            """,
            (
                f"atom-{origin[:32]}",
                vault_id,
                session["scope_cluster_id"],
                session_id,
                source_message_id,
                fact.fact_id,
                fact.citation.turn_index,
                fact.citation.speaker,
                fact.citation.session_date,
                fact.citation.excerpt,
                fact.citation.source_content_hash,
                fact.subject,
                fact.predicate,
                fact.object_text,
                fact.fact_kind,
                fact.assertion_mode,
                fact.event_date,
                fact.observed_date,
                quantity.value if quantity else None,
                quantity.unit if quantity else None,
                quantity.role if quantity else None,
                json.dumps(fact.qualifiers, sort_keys=True, separators=(",", ":")),
                fact.supersession_key,
                fact.confidence,
                ATOMIC_MEMORY_VERSION,
                origin,
                now,
                now,
            ),
        )

    for unit in extraction.source_units:
        source_message_id = message_ids[unit.turn_index]
        serialized = unit.model_dump(mode="json")
        origin = _fingerprint(
            {
                "compiler_version": ATOMIC_MEMORY_VERSION,
                "source_content_hash": compiled_source_hash,
                "unit": serialized,
            }
        )
        desired_units.add(origin)
        conn.execute(
            """
            INSERT INTO atomic_memory_source_units (
                id, vault_id, session_id, source_message_id, compiler_unit_id, turn_index,
                speaker_role, excerpt_hash, coverage_status, fact_ids_json,
                compiler_version, source_content_hash, origin_fingerprint, status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'current', ?, ?)
            ON CONFLICT(origin_fingerprint) DO UPDATE SET
                status = 'current', updated_at = excluded.updated_at
            """,
            (
                f"unit-{origin[:32]}",
                vault_id,
                session_id,
                source_message_id,
                unit.unit_id,
                unit.turn_index,
                unit.speaker,
                unit.excerpt_hash,
                unit.status,
                json.dumps(unit.fact_ids, separators=(",", ":")),
                ATOMIC_MEMORY_VERSION,
                compiled_source_hash,
                origin,
                now,
                now,
            ),
        )

    _retract_missing(conn, "atomic_memory_facts", session_id, desired_facts, now)
    _retract_missing(conn, "atomic_memory_source_units", session_id, desired_units, now)
    covered = sum(
        unit.status in {"facts_extracted", "processed_no_fact"}
        for unit in extraction.source_units
    )
    conn.execute(
        """
        INSERT INTO atomic_memory_session_state (
            session_id, vault_id, source_message_count, source_content_hash,
            compiler_version, fact_count, source_unit_count, covered_source_unit_count,
            processed_at, last_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '')
        ON CONFLICT(session_id) DO UPDATE SET
            vault_id = excluded.vault_id,
            source_message_count = excluded.source_message_count,
            source_content_hash = excluded.source_content_hash,
            compiler_version = excluded.compiler_version,
            fact_count = excluded.fact_count,
            source_unit_count = excluded.source_unit_count,
            covered_source_unit_count = excluded.covered_source_unit_count,
            processed_at = excluded.processed_at,
            last_error = ''
        """,
        (
            session_id,
            vault_id,
            len(messages),
            compiled_source_hash,
            ATOMIC_MEMORY_VERSION,
            len(extraction.facts),
            len(extraction.source_units),
            covered,
            now,
        ),
    )
    return {
        "fact_count": len(extraction.facts),
        "source_unit_count": len(extraction.source_units),
        "covered_source_unit_count": covered,
        "source_coverage_complete": bool(extraction.source_units)
        and covered == len(extraction.source_units),
    }


def _retract_missing(
    conn: sqlite3.Connection,
    table: str,
    session_id: str,
    desired: set[str],
    now: str,
) -> None:
    rows = conn.execute(
        f"SELECT origin_fingerprint FROM {table} WHERE session_id = ? AND status = 'current'",
        (session_id,),
    ).fetchall()
    missing = [
        str(row["origin_fingerprint"])
        for row in rows
        if row["origin_fingerprint"] not in desired
    ]
    conn.executemany(
        f"UPDATE {table} SET status = 'retracted', updated_at = ? WHERE origin_fingerprint = ?",
        [(now, fingerprint) for fingerprint in missing],
    )


def load_atomic_facts_for_sessions(
    conn: sqlite3.Connection,
    *,
    vault_id: str,
    session_ids: list[str],
) -> list[AtomicFact]:
    """Load current compiled facts for an already-authorized retrieval session set."""
    if not session_ids:
        return []
    placeholders = ",".join("?" for _ in session_ids)
    rows = conn.execute(
        f"""
        SELECT * FROM atomic_memory_facts
        WHERE vault_id = ? AND session_id IN ({placeholders}) AND status = 'current'
        ORDER BY observed_date, session_id, turn_index, compiler_fact_id
        """,
        (vault_id, *session_ids),
    ).fetchall()
    result: list[AtomicFact] = []
    for row in rows:
        quantity = None
        if row["quantity_value"] is not None:
            quantity = AtomicQuantity(
                value=float(row["quantity_value"]),
                unit=str(row["quantity_unit"]),
                role=str(row["quantity_role"]),
            )
        result.append(
            AtomicFact(
                fact_id=str(row["compiler_fact_id"]),
                citation=AtomicCitation(
                    session_id=str(row["session_id"]),
                    turn_index=int(row["turn_index"]),
                    speaker=str(row["speaker_role"]),
                    session_date=str(row["session_date"]),
                    excerpt=str(row["citation_excerpt"]),
                    source_content_hash=str(row["source_content_hash"]),
                ),
                subject=str(row["subject_key"]),
                predicate=str(row["predicate_key"]),
                object_text=str(row["object_text"]),
                fact_kind=str(row["fact_kind"]),
                assertion_mode=str(row["assertion_mode"]),
                event_date=row["event_date"],
                observed_date=str(row["observed_date"]),
                quantity=quantity,
                qualifiers=json.loads(str(row["qualifiers_json"])),
                supersession_key=row["supersession_key"],
                confidence=float(row["confidence"]),
            )
        )
    return materialize_progressive_counters(result)


def atomic_memory_coverage_report(
    conn: sqlite3.Connection,
    *,
    vault_id: str,
) -> dict:
    """Return content-free production coverage metrics for one vault."""
    session_rows = conn.execute(
        "SELECT id FROM chat_sessions WHERE vault_id = ? ORDER BY created_at, id",
        (vault_id,),
    ).fetchall()
    session_ids = [str(row["id"]) for row in session_rows]
    message_counts = conn.execute(
        """
        SELECT
            COUNT(*) AS message_count,
            SUM(CASE WHEN messages.role = 'user' THEN 1 ELSE 0 END) AS user_turn_count,
            SUM(CASE WHEN messages.role IN ('user', 'assistant', 'tool') THEN 1 ELSE 0 END)
                AS supported_turn_count
        FROM chat_messages messages
        JOIN chat_sessions sessions ON sessions.id = messages.session_id
        WHERE sessions.vault_id = ?
        """,
        (vault_id,),
    ).fetchone()
    indexed_sessions = conn.execute(
        "SELECT COUNT(*) AS count FROM atomic_memory_session_state WHERE vault_id = ?",
        (vault_id,),
    ).fetchone()["count"]
    fact_rows = conn.execute(
        """
        SELECT source_message_id, speaker_role, qualifiers_json
        FROM atomic_memory_facts
        WHERE vault_id = ? AND status = 'current'
        """,
        (vault_id,),
    ).fetchall()
    source_rows = conn.execute(
        """
        SELECT coverage_status FROM atomic_memory_source_units
        WHERE vault_id = ? AND status = 'current'
        """,
        (vault_id,),
    ).fetchall()
    fact_turns = {str(row["source_message_id"]) for row in fact_rows}
    user_fact_turns = {
        str(row["source_message_id"])
        for row in fact_rows
        if row["speaker_role"] == "user"
    }
    qualifier_rows = [json.loads(str(row["qualifiers_json"])) for row in fact_rows]
    origins: dict[str, int] = {}
    for qualifiers in qualifier_rows:
        origin = str(qualifiers.get("atomic_origin") or "unknown")
        origins[origin] = origins.get(origin, 0) + 1
    supported_turn_count = int(message_counts["supported_turn_count"] or 0)
    user_turn_count = int(message_counts["user_turn_count"] or 0)
    terminal_units = sum(
        row["coverage_status"] in {"facts_extracted", "processed_no_fact"}
        for row in source_rows
    )
    materialized = load_atomic_facts_for_sessions(
        conn,
        vault_id=vault_id,
        session_ids=session_ids,
    )
    return {
        "vault_id": vault_id,
        "compiler_version": ATOMIC_MEMORY_VERSION,
        "session_count": len(session_ids),
        "indexed_session_count": int(indexed_sessions),
        "message_count": int(message_counts["message_count"] or 0),
        "supported_turn_count": supported_turn_count,
        "user_turn_count": user_turn_count,
        "turns_with_atomic_facts": len(fact_turns),
        "user_turns_with_atomic_facts": len(user_fact_turns),
        "turn_fact_yield_rate": round(
            len(fact_turns) / supported_turn_count, 6
        ) if supported_turn_count else 0.0,
        "user_turn_fact_yield_rate": round(
            len(user_fact_turns) / user_turn_count, 6
        ) if user_turn_count else 0.0,
        "current_fact_count": len(fact_rows),
        "fact_origin_counts": origins,
        "source_unit_count": len(source_rows),
        "terminal_source_unit_count": terminal_units,
        "source_coverage_complete_rate": round(
            terminal_units / len(source_rows), 6
        ) if source_rows else 0.0,
        "closed_world_count_fact_count": sum(
            qualifiers.get("closed_world_category") == "true"
            for qualifiers in qualifier_rows
        ),
        "counter_snapshot_fact_count": sum(
            qualifiers.get("counter_snapshot") == "true"
            for qualifiers in qualifier_rows
        ),
        "counter_delta_fact_count": sum(
            qualifiers.get("counter_operation") == "increment"
            for qualifiers in qualifier_rows
        ),
        "materialized_counter_count": sum(
            fact.qualifiers.get("atomic_origin") == "deterministic_derived"
            for fact in materialized
        ),
    }
