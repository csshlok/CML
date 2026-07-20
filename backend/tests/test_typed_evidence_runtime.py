from __future__ import annotations

import json
import os
import sqlite3
from unittest.mock import patch

from backend.app.core.typed_evidence_runtime import (
    contract_memory_item,
    evaluate_runtime_evidence,
    plan_runtime_query,
    public_diagnostics,
)


def _database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE temporal_facts (
            id TEXT PRIMARY KEY,
            vault_id TEXT NOT NULL,
            cluster_id TEXT,
            subject_key TEXT NOT NULL,
            predicate_key TEXT NOT NULL,
            object_text TEXT NOT NULL,
            object_type TEXT NOT NULL,
            assertion_kind TEXT NOT NULL,
            modality TEXT NOT NULL,
            speaker_role TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            session_id TEXT,
            citation_excerpt TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            valid_from TEXT NOT NULL,
            valid_until TEXT,
            status TEXT NOT NULL,
            confidence REAL NOT NULL,
            origin_fingerprint TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    return conn


def _fact(
    conn: sqlite3.Connection,
    fact_id: str,
    *,
    excerpt: str,
    object_text: str,
    assertion_kind: str = "action",
    speaker_role: str = "user",
    predicate: str = "completed_action",
    session_id: str = "session-1",
    status: str = "current",
    date: str = "2025-01-01T00:00:00+00:00",
    metadata: dict | None = None,
    cluster_id: str | None = None,
    subject: str = "user",
) -> None:
    conn.execute(
        """
        INSERT INTO temporal_facts (
            id, vault_id, cluster_id, subject_key, predicate_key, object_text,
            object_type, assertion_kind, modality, speaker_role, source_type,
            source_id, session_id, citation_excerpt, observed_at, valid_from,
            valid_until, status, confidence, origin_fingerprint, metadata_json,
            created_at
        ) VALUES (?, 'vault-1', ?, ?, ?, ?, 'text', ?, 'asserted', ?,
                  'chat_message', ?, ?, ?, ?, ?, NULL, ?, 0.95, ?, ?, ?)
        """,
        (
            fact_id,
            cluster_id,
            subject,
            predicate,
            object_text,
            assertion_kind,
            speaker_role,
            f"message-{fact_id}",
            session_id,
            excerpt,
            date,
            date,
            status,
            fact_id[0] * 64,
            json.dumps(metadata or {}),
            date,
        ),
    )


def test_named_speaker_preference_query_filters_other_speakers() -> None:
    conn = _database()
    _fact(
        conn,
        "a",
        excerpt="My favorite editor is Vim.",
        object_text="Vim",
        assertion_kind="preference",
        predicate="prefers",
        subject="caroline",
        metadata={"polarity": "positive", "family": "favorite"},
    )
    _fact(
        conn,
        "b",
        excerpt="My favorite editor is Emacs.",
        object_text="Emacs",
        assertion_kind="preference",
        predicate="prefers",
        subject="melanie",
        metadata={"polarity": "positive", "family": "favorite"},
    )

    decision = evaluate_runtime_evidence(
        conn,
        vault_id="vault-1",
        cluster_id=None,
        question="What does Caroline generally prefer for an editor?",
    )

    assert decision["result"].status == "needs_generation"
    required = set(decision["result"].contract.required_claim_ids)
    selected = [record for record in decision["records"] if record.claim_id in required]
    assert [record.subject for record in selected] == ["caroline"]
    assert [record.object for record in selected] == ["vim"]


def test_named_speaker_bounded_favorite_question_stays_on_retrieval_path() -> None:
    plan = plan_runtime_query("What was Melanie's favorite childhood book?")
    assert plan.intent == "unsupported"


def test_preference_topic_miss_abstains_instead_of_injecting_other_preferences() -> None:
    conn = _database()
    _fact(
        conn,
        "a",
        excerpt="I prefer tea.",
        object_text="tea",
        assertion_kind="preference",
        predicate="prefers",
        metadata={"polarity": "positive"},
    )

    decision = evaluate_runtime_evidence(
        conn,
        vault_id="vault-1",
        cluster_id=None,
        question="What is my favorite editor now?",
    )

    assert decision["result"].status == "fallback"
    assert "matched the requested topic" in decision["result"].reason


def test_unsupported_question_does_not_require_temporal_table() -> None:
    conn = sqlite3.connect(":memory:")
    decision = evaluate_runtime_evidence(
        conn,
        vault_id="vault-1",
        cluster_id=None,
        question="Explain this source.",
    )
    assert decision["result"].status == "fallback"
    assert public_diagnostics(decision)["record_count"] == 0


def test_distinct_count_uses_user_actions_and_excludes_assistant_suggestions() -> None:
    conn = _database()
    _fact(
        conn,
        "a",
        excerpt="I made orange bitters with orange peel.",
        object_text="made orange bitters with orange peel",
    )
    _fact(
        conn,
        "b",
        excerpt="I used lime in a cocktail.",
        object_text="used lime in a cocktail",
    )
    _fact(
        conn,
        "c",
        excerpt="You should try grapefruit next.",
        object_text="try grapefruit next",
        assertion_kind="suggestion",
        speaker_role="assistant",
        predicate="suggested_option",
    )
    decision = evaluate_runtime_evidence(
        conn,
        vault_id="vault-1",
        cluster_id=None,
        question="How many different types of citrus fruit have I used?",
    )

    assert decision["result"].status == "resolved"
    assert decision["result"].answer == "2: lime, orange."
    diagnostics = public_diagnostics(decision)
    assert diagnostics["deterministic_answer_used"] is True
    assert diagnostics["evidence_claim_count"] == 2


def test_structured_numeric_history_resolves_latest_comparison() -> None:
    conn = _database()
    first_numeric = {
        "numeric": {
            "value": 6,
            "unit": "water_ounces_per_tablespoon",
            "role": "ratio",
            "context": "french_press",
        }
    }
    second_numeric = {
        "numeric": {
            "value": 5,
            "unit": "water_ounces_per_tablespoon",
            "role": "ratio",
            "context": "french_press",
        }
    }
    _fact(
        conn,
        "d",
        excerpt="I use six ounces of water per tablespoon for French press.",
        object_text="six ounces per tablespoon",
        assertion_kind="state",
        predicate="french_press_ratio",
        status="superseded",
        date="2025-01-01T00:00:00+00:00",
        metadata=first_numeric,
    )
    _fact(
        conn,
        "e",
        excerpt="I now use five ounces of water per tablespoon for French press.",
        object_text="five ounces per tablespoon",
        assertion_kind="state",
        predicate="french_press_ratio",
        date="2025-02-01T00:00:00+00:00",
        metadata=second_numeric,
    )
    decision = evaluate_runtime_evidence(
        conn,
        vault_id="vault-1",
        cluster_id=None,
        question="Did I switch to more or less water in my French press ratio?",
    )

    assert decision["result"].status == "resolved"
    assert decision["result"].answer.startswith("Less: from 6 to 5")


def test_preference_summary_uses_latest_topic_fact_and_preserves_history_on_request() -> None:
    conn = _database()
    _fact(
        conn,
        "p",
        excerpt="I love tea.",
        object_text="tea",
        assertion_kind="preference",
        predicate="prefers",
        session_id="session-old",
        status="superseded",
        date="2025-01-01T00:00:00+00:00",
        metadata={"polarity": "positive"},
    )
    _fact(
        conn,
        "n",
        excerpt="I no longer like tea.",
        object_text="tea",
        assertion_kind="preference",
        predicate="avoids",
        session_id="session-new",
        date="2025-02-01T00:00:00+00:00",
        metadata={"polarity": "negative"},
    )

    current = evaluate_runtime_evidence(
        conn,
        vault_id="vault-1",
        cluster_id=None,
        question="What are my preferences?",
    )
    history = evaluate_runtime_evidence(
        conn,
        vault_id="vault-1",
        cluster_id=None,
        question="How have my preferences changed over time?",
    )

    assert current["plan"].intent == "preference_summary"
    assert current["result"].status == "needs_generation"
    assert current["result"].contract.required_claim_ids == ["temporal_n"]
    assert set(history["result"].contract.required_claim_ids) == {
        "temporal_p",
        "temporal_n",
    }


def test_personalized_advice_can_use_cited_anchors_across_sessions() -> None:
    conn = _database()
    _fact(
        conn,
        "h",
        excerpt="I completed a long hiking trip.",
        object_text="completed a long hiking trip",
        session_id="session-experience",
    )
    _fact(
        conn,
        "g",
        excerpt="My goal is to improve my hiking endurance.",
        object_text="improve my hiking endurance",
        assertion_kind="goal",
        predicate="goal",
        session_id="session-goal",
        date="2025-02-01T00:00:00+00:00",
    )

    decision = evaluate_runtime_evidence(
        conn,
        vault_id="vault-1",
        cluster_id=None,
        question="Based on my hiking experience, what should I do to improve?",
    )

    assert decision["result"].status == "needs_generation"
    assert set(decision["result"].contract.required_claim_ids) == {
        "temporal_h",
        "temporal_g",
    }


def test_personalized_advice_injects_same_session_provenance_contract() -> None:
    conn = _database()
    _fact(
        conn,
        "f",
        excerpt="I made slow cooker beef stew successfully.",
        object_text="made slow cooker beef stew successfully",
    )
    _fact(
        conn,
        "1",
        excerpt="I want to make slow cooker yogurt.",
        object_text="make slow cooker yogurt",
        assertion_kind="goal",
        predicate="plans",
        date="2025-01-02T00:00:00+00:00",
    )
    decision = evaluate_runtime_evidence(
        conn,
        vault_id="vault-1",
        cluster_id=None,
        question="What slow cooker advice can you suggest based on my interests?",
    )

    assert decision["result"].status == "needs_generation"
    item = contract_memory_item(decision)
    assert item is not None
    assert item["kind"] == "typed_evidence_contract"
    assert "REQUIRED" in item["summary"]
    assert "beef stew" in item["summary"]
    assert "yogurt" in item["summary"]
    assert public_diagnostics(decision)["contract_injected"] is True


def test_cluster_scope_does_not_use_facts_from_another_cluster() -> None:
    conn = _database()
    _fact(
        conn,
        "2",
        excerpt="I used lime in a cocktail.",
        object_text="used lime in a cocktail",
        cluster_id="cluster-other",
    )
    decision = evaluate_runtime_evidence(
        conn,
        vault_id="vault-1",
        cluster_id="cluster-current",
        question="How many different types of citrus fruit have I used?",
    )
    assert decision["result"].status == "fallback"
    assert public_diagnostics(decision)["record_count"] == 0


def test_bounded_scan_never_returns_a_partial_deterministic_count() -> None:
    conn = _database()
    _fact(
        conn,
        "3",
        excerpt="I used lime in a cocktail.",
        object_text="used lime in a cocktail",
        date="2025-01-01T00:00:00+00:00",
    )
    _fact(
        conn,
        "4",
        excerpt="I used orange in a cocktail.",
        object_text="used orange in a cocktail",
        date="2025-01-02T00:00:00+00:00",
    )
    decision = evaluate_runtime_evidence(
        conn,
        vault_id="vault-1",
        cluster_id=None,
        question="How many different types of citrus fruit have I used?",
        limit=1,
    )
    assert decision["result"].status == "fallback"
    assert public_diagnostics(decision)["ledger_truncated"] is True


def test_production_chat_path_uses_deterministic_typed_answer(tmp_path) -> None:
    from backend.app.api.routes.chat import _build_retrieval_context
    from backend.app.api.routes.sources import create_source
    from backend.app.core.background_jobs import run_due_jobs_once
    from backend.app.core.config import get_settings
    from backend.app.core.database import connect, init_db, utc_now
    from backend.app.core.temporal_facts import sync_chat_session_temporal_facts
    from backend.app.schemas import ChatContextRequest, SourceCreate

    original = {
        key: os.environ.get(key)
        for key in (
            "CML_DATABASE_PATH",
            "CML_DATA_DIR",
            "CML_EMBEDDING_PROVIDER",
            "CML_ALLOW_HASH_EMBEDDINGS",
        )
    }
    os.environ["CML_DATABASE_PATH"] = str(tmp_path / "runtime.sqlite3")
    os.environ["CML_DATA_DIR"] = str(tmp_path)
    os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
    os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"
    get_settings.cache_clear()
    try:
        init_db()
        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(tmp_path), now, now),
            )
        create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Cocktail notes",
                source_type="note",
                raw_text="Cocktail history reference. " * 80,
            )
        )
        run_due_jobs_once(limit=1)
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions (id, vault_id, title, created_at, updated_at)
                VALUES ('session-history', 'vault-1', 'History', ?, ?)
                """,
                (now, now),
            )
            conn.execute(
                """
                INSERT INTO chat_messages (
                    id, session_id, role, content, clusters_used, citations, warnings, created_at
                ) VALUES (?, 'session-history', 'user', ?, '[]', '[]', '[]', ?)
                """,
                ("message-orange", "I made orange bitters.", "2025-01-01T00:00:00+00:00"),
            )
            conn.execute(
                """
                INSERT INTO chat_messages (
                    id, session_id, role, content, clusters_used, citations, warnings, created_at
                ) VALUES (?, 'session-history', 'user', ?, '[]', '[]', '[]', ?)
                """,
                ("message-lime", "I used lime in a cocktail.", "2025-01-02T00:00:00+00:00"),
            )
            messages = conn.execute(
                "SELECT * FROM chat_messages WHERE session_id = 'session-history' ORDER BY created_at"
            ).fetchall()
            sync_chat_session_temporal_facts(
                conn,
                vault_id="vault-1",
                session_id="session-history",
                messages=messages,
            )

        empty_bundle = {
            "citations": [],
            "selected_clusters": [],
            "memory_items": [],
            "working_memory": {},
            "cluster_profile": {},
            "warnings": [],
            "retrieval_authority": True,
            "token_estimate": {},
            "bundle_status": {},
        }
        with patch(
            "backend.app.api.routes.chat.build_cluster_bundle_context",
            return_value=empty_bundle,
        ):
            context = _build_retrieval_context(
                ChatContextRequest(
                    vault_id="vault-1",
                    prompt="How many different types of citrus fruit have I used?",
                    persist=False,
                ),
                synthesize=False,
            )

        assert context["answer"] == "2: lime, orange."
        assert context["typed_evidence_resolved"] is True
        assert context["coverage_ledger"]["partial_failure_mode"] == "typed_evidence_resolved"
        assert context["coverage_ledger"]["typed_evidence"]["evidence_claim_count"] == 2
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()


def test_typed_contract_survives_memory_budget_ranking() -> None:
    from backend.app.core.context_reduction import build_context_reduction_plan

    typed = {
        "id": "typed-contract:test",
        "kind": "typed_evidence_contract",
        "summary": (
            "Typed evidence contract: use REQUIRED beef stew experience and REQUIRED "
            "slow cooker yogurt interest."
        ),
    }
    ordinary = [
        {
            "id": f"memory-{index}",
            "kind": "fact",
            "summary": "slow cooker general background " * 30,
        }
        for index in range(12)
    ]
    plan = build_context_reduction_plan(
        prompt="What slow cooker advice fits my interests?",
        citations=[],
        recent_turns=[],
        memory_items=[*ordinary, typed],
        working_memory={},
        token_budget=300,
    )
    kept = plan["memory_items"]
    assert any(item["id"] == typed["id"] for item in kept)
    assert "REQUIRED" in next(item["summary"] for item in kept if item["id"] == typed["id"])
