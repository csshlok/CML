from __future__ import annotations

import os
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError


class TemporalFactLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "temporal-facts.sqlite3"
        os.environ["CML_DATABASE_PATH"] = str(self.db_path)
        os.environ["CML_DATA_DIR"] = self.tmp.name

        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        from backend.app.core.database import connect, init_db

        init_db()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test", self.tmp.name, "2025-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"),
            )
            conn.execute(
                """
                INSERT INTO chat_sessions (id, vault_id, title, created_at, updated_at)
                VALUES ('session-1', 'vault-1', 'History', ?, ?)
                """,
                ("2025-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"),
            )

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        os.environ.pop("CML_DATABASE_PATH", None)
        os.environ.pop("CML_DATA_DIR", None)
        self.tmp.cleanup()

    def _message(self, message_id: str, role: str, content: str, created_at: str) -> None:
        from backend.app.core.database import connect

        with connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_messages (
                    id, session_id, role, content, clusters_used, citations, warnings, created_at
                ) VALUES (?, 'session-1', ?, ?, '[]', '[]', '[]', ?)
                """,
                (message_id, role, content, created_at),
            )

    def test_source_envelope_rejects_speaker_spoofing_and_assistant_user_action(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.temporal_facts import TemporalFactCreate, record_temporal_fact

        self._message("assistant-1", "assistant", "You should try grapefruit.", "2025-01-01T10:00:00+00:00")
        with self.assertRaises(ValidationError):
            TemporalFactCreate(
                vault_id="vault-1",
                subject_key="user",
                predicate_key="completed_action",
                object_text="tried grapefruit",
                assertion_kind="action",
                speaker_role="assistant",
                source_type="chat_message",
                source_id="assistant-1",
            )
        with connect() as conn, self.assertRaisesRegex(ValueError, "speaker_role_mismatch"):
            record_temporal_fact(
                conn,
                {
                    "vault_id": "vault-1",
                    "subject_key": "user",
                    "predicate_key": "prefers",
                    "object_text": "grapefruit",
                    "assertion_kind": "preference",
                    "speaker_role": "user",
                    "source_type": "chat_message",
                    "source_id": "assistant-1",
                },
            )

    def test_chat_sync_preserves_suggestions_and_answers_current_and_as_of_state(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.temporal_facts import (
            query_temporal_facts,
            sync_chat_session_temporal_facts,
            temporal_fact_history,
        )

        self._message("user-old", "user", "I live in London.", "2025-01-01T10:00:00+00:00")
        self._message("assistant-1", "assistant", "You should try Paris.", "2025-02-01T10:00:00+00:00")
        self._message("user-new", "user", "I now live in Berlin.", "2025-03-01T10:00:00+00:00")

        with connect() as conn:
            messages = conn.execute(
                "SELECT * FROM chat_messages WHERE session_id = 'session-1' ORDER BY created_at"
            ).fetchall()
            first = sync_chat_session_temporal_facts(
                conn, vault_id="vault-1", session_id="session-1", messages=messages
            )
            second = sync_chat_session_temporal_facts(
                conn, vault_id="vault-1", session_id="session-1", messages=messages
            )
            current = query_temporal_facts(
                conn,
                vault_id="vault-1",
                subject_key="user",
                predicate_key="lives_in",
                as_of="2025-04-01T00:00:00+00:00",
            )
            historical = query_temporal_facts(
                conn,
                vault_id="vault-1",
                subject_key="user",
                predicate_key="lives_in",
                as_of="2025-02-15T00:00:00+00:00",
            )
            suggestions = query_temporal_facts(
                conn,
                vault_id="vault-1",
                subject_key="user",
                include_suggestions=True,
                as_of="2025-04-01T00:00:00+00:00",
            )
            history = temporal_fact_history(
                conn, vault_id="vault-1", supersession_key="user:lives_in"
            )

        self.assertEqual(first["retracted_count"], 0)
        self.assertEqual(second["retracted_count"], 0)
        self.assertEqual(first["fact_ids"], second["fact_ids"])
        self.assertEqual([item["object_text"] for item in current], ["Berlin"])
        self.assertEqual([item["object_text"] for item in historical], ["London"])
        self.assertEqual([item["object_text"] for item in history], ["London", "Berlin"])
        self.assertEqual(history[0]["status"], "superseded")
        self.assertEqual(history[0]["superseded_by_fact_id"], history[1]["id"])
        suggestion = next(item for item in suggestions if item["assertion_kind"] == "suggestion")
        self.assertEqual(suggestion["speaker_role"], "assistant")
        self.assertEqual(suggestion["object_text"], "try Paris")
        self.assertEqual(suggestion["citation_excerpt"], "You should try Paris.")
        self.assertFalse(any(item["assertion_kind"] == "action" for item in suggestions))

    def test_unrelated_preferences_do_not_supersede_each_other(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.temporal_facts import query_temporal_facts, sync_chat_session_temporal_facts

        self._message("user-tea", "user", "I prefer tea.", "2025-01-01T10:00:00+00:00")
        self._message("user-editor", "user", "I like Vim keybindings.", "2025-01-02T10:00:00+00:00")
        with connect() as conn:
            messages = conn.execute("SELECT * FROM chat_messages WHERE session_id = 'session-1'").fetchall()
            sync_chat_session_temporal_facts(
                conn, vault_id="vault-1", session_id="session-1", messages=messages
            )
            preferences = query_temporal_facts(
                conn,
                vault_id="vault-1",
                subject_key="user",
                predicate_key="prefers",
                as_of="2025-02-01T00:00:00+00:00",
            )

        self.assertEqual({item["object_text"] for item in preferences}, {"tea", "Vim keybindings"})

    def test_negated_state_closes_prior_value_without_erasing_history(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.temporal_facts import (
            query_temporal_facts,
            sync_chat_session_temporal_facts,
            temporal_fact_history,
        )

        self._message("user-old", "user", "I live in London.", "2025-01-01T10:00:00+00:00")
        self._message(
            "user-negated",
            "user",
            "I no longer live in London.",
            "2025-03-01T10:00:00+00:00",
        )
        with connect() as conn:
            messages = conn.execute(
                "SELECT * FROM chat_messages WHERE session_id = 'session-1' ORDER BY created_at"
            ).fetchall()
            sync_chat_session_temporal_facts(
                conn, vault_id="vault-1", session_id="session-1", messages=messages
            )
            current = query_temporal_facts(
                conn,
                vault_id="vault-1",
                predicate_key="lives_in",
                as_of="2025-04-01T00:00:00+00:00",
            )
            history = temporal_fact_history(
                conn, vault_id="vault-1", supersession_key="user:lives_in"
            )

        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["modality"], "negated")
        self.assertEqual([item["object_text"] for item in history], ["London", "London"])
        self.assertEqual([item["status"] for item in history], ["superseded", "current"])

    def test_preference_reversal_is_scoped_to_the_same_topic(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.temporal_facts import (
            query_temporal_facts,
            sync_chat_session_temporal_facts,
            temporal_fact_history,
        )

        self._message("user-like", "user", "I like tea.", "2025-01-01T10:00:00+00:00")
        self._message("user-dislike", "user", "I no longer like tea.", "2025-02-01T10:00:00+00:00")
        self._message("user-vim", "user", "I like Vim keybindings.", "2025-02-02T10:00:00+00:00")
        with connect() as conn:
            messages = conn.execute(
                "SELECT * FROM chat_messages WHERE session_id = 'session-1' ORDER BY created_at"
            ).fetchall()
            sync_chat_session_temporal_facts(
                conn, vault_id="vault-1", session_id="session-1", messages=messages
            )
            current = query_temporal_facts(
                conn,
                vault_id="vault-1",
                subject_key="user",
                as_of="2025-03-01T00:00:00+00:00",
            )
            tea_history = temporal_fact_history(
                conn, vault_id="vault-1", supersession_key="user:preference:tea"
            )

        self.assertEqual([item["predicate_key"] for item in tea_history], ["prefers", "avoids"])
        self.assertEqual([item["status"] for item in tea_history], ["superseded", "current"])
        self.assertEqual(
            {(item["predicate_key"], item["object_text"]) for item in current},
            {("avoids", "tea"), ("prefers", "Vim keybindings")},
        )

    def test_natural_language_as_of_dates_are_deterministic(self) -> None:
        from backend.app.core.temporal_facts import parse_as_of_query

        reference = "2025-04-15T12:00:00+00:00"
        self.assertEqual(
            parse_as_of_query("Where was I as of March 2, 2025?", reference_time=reference),
            "2025-03-02T23:59:59+00:00",
        )
        self.assertEqual(
            parse_as_of_query("What was true as of yesterday?", reference_time=reference),
            "2025-04-14T23:59:59+00:00",
        )
        self.assertEqual(
            parse_as_of_query("What is true now?", reference_time=reference),
            None,
        )

    def test_backfill_job_is_idempotent_and_reports_coverage(self) -> None:
        from backend.app.api.routes.jobs import backfill_temporal_facts, get_temporal_fact_status
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect
        from backend.app.schemas import TemporalFactBackfillRequest

        self._message("user-1", "user", "I live in London.", "2025-01-01T10:00:00+00:00")
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions (id, vault_id, title, created_at, updated_at)
                VALUES ('session-2', 'vault-1', 'Preferences', ?, ?)
                """,
                ("2025-01-02T00:00:00+00:00", "2025-01-02T00:00:00+00:00"),
            )
            conn.execute(
                """
                INSERT INTO chat_messages (
                    id, session_id, role, content, clusters_used, citations, warnings, created_at
                ) VALUES ('user-2', 'session-2', 'user', 'I prefer tea.', '[]', '[]', '[]', ?)
                """,
                ("2025-01-02T10:00:00+00:00",),
            )
            conn.execute(
                """
                INSERT INTO chat_sessions (id, vault_id, title, created_at, updated_at)
                VALUES ('session-3', 'vault-1', 'No durable facts', ?, ?)
                """,
                ("2025-01-03T00:00:00+00:00", "2025-01-03T00:00:00+00:00"),
            )
            conn.execute(
                """
                INSERT INTO chat_messages (
                    id, session_id, role, content, clusters_used, citations, warnings, created_at
                ) VALUES ('user-3', 'session-3', 'user', 'Thanks for the explanation.', '[]', '[]', '[]', ?)
                """,
                ("2025-01-03T10:00:00+00:00",),
            )

        request = TemporalFactBackfillRequest(vault_id="vault-1", batch_size=1)
        first = backfill_temporal_facts(request)
        duplicate = backfill_temporal_facts(request)
        self.assertEqual(first["id"], duplicate["id"])
        self.assertEqual(run_due_jobs_once(limit=1), 1)
        status = get_temporal_fact_status("vault-1")
        self.assertEqual(status["session_count"], 3)
        self.assertEqual(status["indexed_session_count"], 3)
        self.assertEqual(status["status_counts"], {"current": 2})
        with connect() as conn:
            job = conn.execute("SELECT * FROM app_jobs WHERE id = ?", (first["id"],)).fetchone()
            fact_count = conn.execute("SELECT COUNT(*) AS count FROM temporal_facts").fetchone()["count"]
            atomic_session_count = conn.execute(
                "SELECT COUNT(*) AS count FROM atomic_memory_session_state"
            ).fetchone()["count"]
            atomic_fact_count = conn.execute(
                "SELECT COUNT(*) AS count FROM atomic_memory_facts WHERE status = 'current'"
            ).fetchone()["count"]
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["status_detail"], "Temporal history is current for 3 chat sessions.")
        self.assertEqual(fact_count, 2)
        self.assertEqual(atomic_session_count, 3)
        self.assertGreater(atomic_fact_count, fact_count)

        second = backfill_temporal_facts(request)
        self.assertNotEqual(second["id"], first["id"])
        self.assertEqual(run_due_jobs_once(limit=1), 1)
        with connect() as conn:
            repeated_count = conn.execute("SELECT COUNT(*) AS count FROM temporal_facts").fetchone()["count"]
        self.assertEqual(repeated_count, 2)

    def test_startup_reconciliation_queues_backfill_only_for_stale_sessions(self) -> None:
        from backend.app.core.background_jobs import (
            enqueue_startup_reconciliation_jobs,
            run_due_jobs_once,
        )
        from backend.app.core.database import connect

        self._message("user-1", "user", "I prefer tea.", "2025-01-01T10:00:00+00:00")
        enqueue_startup_reconciliation_jobs()
        with connect() as conn:
            jobs = conn.execute(
                """
                SELECT job_type, payload, user_initiated FROM app_jobs
                WHERE job_type = 'temporal_fact_backfill'
                """
            ).fetchall()
        self.assertEqual(len(jobs), 1)
        self.assertIn('"vault_id":"vault-1"', jobs[0]["payload"])
        self.assertEqual(jobs[0]["user_initiated"], 0)

        # Keep this focused test independent of the embedding runtime used by the
        # separate startup vector-reconciliation job.
        with connect() as conn:
            conn.execute("DELETE FROM app_jobs WHERE job_type = 'vector_reconcile_incremental'")
        self.assertEqual(run_due_jobs_once(limit=1), 1)
        enqueue_startup_reconciliation_jobs()
        with connect() as conn:
            backfill_count = conn.execute(
                "SELECT COUNT(*) AS count FROM app_jobs WHERE job_type = 'temporal_fact_backfill'"
            ).fetchone()["count"]
        self.assertEqual(backfill_count, 1)

    def test_provenance_columns_are_immutable(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.temporal_facts import record_temporal_fact

        self._message("user-1", "user", "I prefer tea.", "2025-01-01T10:00:00+00:00")
        with connect() as conn:
            fact = record_temporal_fact(
                conn,
                {
                    "vault_id": "vault-1",
                    "subject_key": "user",
                    "predicate_key": "prefers",
                    "object_text": "tea",
                    "assertion_kind": "preference",
                    "speaker_role": "user",
                    "source_type": "chat_message",
                    "source_id": "user-1",
                    "citation_excerpt": "I prefer tea.",
                },
            )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "temporal_fact_provenance_is_immutable"):
                conn.execute(
                    "UPDATE temporal_facts SET speaker_role = 'assistant' WHERE id = ?",
                    (fact["id"],),
                )

    def test_grounded_memory_uses_current_and_explicit_as_of_fact(self) -> None:
        from backend.app.core.context_memory import get_context_memory
        from backend.app.core.database import connect
        from backend.app.core.temporal_facts import sync_chat_session_temporal_facts

        self._message("user-old", "user", "I live in London.", "2025-01-01T10:00:00+00:00")
        self._message("user-new", "user", "I now live in Berlin.", "2025-03-01T10:00:00+00:00")
        with connect() as conn:
            messages = conn.execute(
                "SELECT * FROM chat_messages WHERE session_id = 'session-1' ORDER BY created_at"
            ).fetchall()
            sync_chat_session_temporal_facts(
                conn, vault_id="vault-1", session_id="session-1", messages=messages
            )
            current, _ = get_context_memory(
                conn,
                vault_id="vault-1",
                cluster_id=None,
                query="Where do I live now?",
            )
            historical, _ = get_context_memory(
                conn,
                vault_id="vault-1",
                cluster_id=None,
                query="Where did I live as of 2025-02-01?",
            )

        self.assertEqual(current[0]["summary"], "user lives in Berlin")
        self.assertEqual(historical[0]["summary"], "user lives in London")

    def test_state_history_query_preserves_old_and_current_values(self) -> None:
        from backend.app.core.context_memory import get_context_memory
        from backend.app.core.database import connect
        from backend.app.core.temporal_facts import sync_chat_session_temporal_facts

        self._message("user-old", "user", "I live in London.", "2025-01-01T10:00:00+00:00")
        with connect() as conn:
            conn.execute(
                """INSERT INTO chat_sessions (id, vault_id, title, created_at, updated_at)
                VALUES ('session-2', 'vault-1', 'New home', ?, ?)""",
                ("2025-03-01T00:00:00+00:00", "2025-03-01T00:00:00+00:00"),
            )
            conn.execute(
                """INSERT INTO chat_messages
                (id, session_id, role, content, clusters_used, citations, warnings, created_at)
                VALUES ('user-new', 'session-2', 'user', 'I now live in Berlin.', '[]', '[]', '[]', ?)""",
                ("2025-03-01T10:00:00+00:00",),
            )
            for session_id in ("session-1", "session-2"):
                messages = conn.execute(
                    "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at",
                    (session_id,),
                ).fetchall()
                sync_chat_session_temporal_facts(
                    conn, vault_id="vault-1", session_id=session_id, messages=messages
                )
            items, _ = get_context_memory(
                conn,
                vault_id="vault-1",
                cluster_id=None,
                query="Where did I live before, and where do I live now?",
            )

        self.assertEqual(items[0]["kind"], "temporal_consolidation")
        self.assertIn("State history", items[0]["summary"])
        self.assertIn("London", items[0]["detail_text"])
        self.assertIn("Berlin", items[0]["detail_text"])

    def test_resolved_action_date_is_not_reapplied_from_relative_citation(self) -> None:
        from backend.app.core.context_memory import get_context_memory
        from backend.app.core.database import connect
        from backend.app.core.temporal_facts import sync_chat_session_temporal_facts

        self._message(
            "user-visit",
            "user",
            "I visited Jaipur yesterday.",
            "2025-06-11T12:00:00+00:00",
        )
        with connect() as conn:
            messages = conn.execute(
                "SELECT * FROM chat_messages WHERE session_id = 'session-1' ORDER BY created_at"
            ).fetchall()
            sync_chat_session_temporal_facts(
                conn, vault_id="vault-1", session_id="session-1", messages=messages
            )
            items, _ = get_context_memory(
                conn,
                vault_id="vault-1",
                cluster_id=None,
                query="On what date did I visit Jaipur?",
            )

        visit = next(item for item in items if "Jaipur" in item["summary"])
        self.assertIn("2025-06-10", visit["detail_text"])
        self.assertNotIn("yesterday", visit["detail_text"].casefold())
        self.assertEqual(visit["citation_excerpt"], "I visited Jaipur yesterday.")

    def test_imported_dialogue_attributes_first_person_claim_to_named_speaker(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.temporal_facts import sync_chat_session_temporal_facts

        self._message(
            "user-imported",
            "user",
            'Caroline said, "My favorite editor is Vim."',
            "2025-06-11T12:00:00+00:00",
        )
        with connect() as conn:
            messages = conn.execute(
                "SELECT * FROM chat_messages WHERE session_id = 'session-1' ORDER BY created_at"
            ).fetchall()
            sync_chat_session_temporal_facts(
                conn, vault_id="vault-1", session_id="session-1", messages=messages
            )
            fact = conn.execute(
                "SELECT subject_key, citation_excerpt, metadata_json FROM temporal_facts"
            ).fetchone()

        self.assertEqual(fact["subject_key"], "caroline")
        self.assertEqual(fact["citation_excerpt"], "My favorite editor is Vim.")
        self.assertEqual(json.loads(fact["metadata_json"])["attributed_speaker"], "Caroline")

    def test_preference_consolidation_preserves_cross_session_citations(self) -> None:
        from backend.app.core.context_memory import get_context_memory
        from backend.app.core.database import connect
        from backend.app.core.temporal_facts import sync_chat_session_temporal_facts

        self._message("user-tea", "user", "I prefer tea.", "2025-01-01T10:00:00+00:00")
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions (id, vault_id, title, created_at, updated_at)
                VALUES ('session-2', 'vault-1', 'More preferences', ?, ?)
                """,
                ("2025-02-01T00:00:00+00:00", "2025-02-01T00:00:00+00:00"),
            )
            conn.execute(
                """
                INSERT INTO chat_messages (
                    id, session_id, role, content, clusters_used, citations, warnings, created_at
                ) VALUES ('user-coffee', 'session-2', 'user', 'I avoid coffee.', '[]', '[]', '[]', ?)
                """,
                ("2025-02-01T10:00:00+00:00",),
            )
            first = conn.execute(
                "SELECT * FROM chat_messages WHERE session_id = 'session-1' ORDER BY created_at"
            ).fetchall()
            second = conn.execute(
                "SELECT * FROM chat_messages WHERE session_id = 'session-2' ORDER BY created_at"
            ).fetchall()
            sync_chat_session_temporal_facts(
                conn, vault_id="vault-1", session_id="session-1", messages=first
            )
            sync_chat_session_temporal_facts(
                conn, vault_id="vault-1", session_id="session-2", messages=second
            )
            items, _ = get_context_memory(
                conn,
                vault_id="vault-1",
                cluster_id=None,
                query="What are my current preferences?",
            )

        consolidated = items[0]
        self.assertEqual(consolidated["kind"], "temporal_consolidation")
        self.assertEqual(set(consolidated["session_ids"]), {"session-1", "session-2"})
        self.assertEqual(len(consolidated["citations"]), 2)
        self.assertIn("user prefers tea", consolidated["summary"])
        self.assertIn("user avoids coffee", consolidated["summary"])
        self.assertTrue(consolidated["authoritative_source_claims_preserved"])

    def test_bounded_favorite_question_excludes_unrelated_cross_session_preferences(self) -> None:
        from backend.app.core.cluster_bundle import build_cluster_bundle_context
        from backend.app.core.context_memory import get_context_memory
        from backend.app.core.database import connect
        from backend.app.core.temporal_facts import sync_chat_session_temporal_facts

        self._message("user-tea", "user", "I prefer tea.", "2025-01-01T10:00:00+00:00")
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions (id, vault_id, title, created_at, updated_at)
                VALUES ('session-2', 'vault-1', 'More preferences', ?, ?)
                """,
                ("2025-02-01T00:00:00+00:00", "2025-02-01T00:00:00+00:00"),
            )
            conn.execute(
                """
                INSERT INTO chat_messages (
                    id, session_id, role, content, clusters_used, citations, warnings, created_at
                ) VALUES ('user-coffee', 'session-2', 'user', 'I avoid coffee.', '[]', '[]', '[]', ?)
                """,
                ("2025-02-01T10:00:00+00:00",),
            )
            for session_id in ("session-1", "session-2"):
                messages = conn.execute(
                    "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at",
                    (session_id,),
                ).fetchall()
                sync_chat_session_temporal_facts(
                    conn, vault_id="vault-1", session_id=session_id, messages=messages
                )
            items, _ = get_context_memory(
                conn,
                vault_id="vault-1",
                cluster_id=None,
                query="What was Melanie's favorite childhood book?",
            )
        bundle = build_cluster_bundle_context(
            vault_id="vault-1",
            query="What was Melanie's favorite childhood book?",
            search_func=lambda _payload: {"results": []},
        )

        self.assertEqual(items, [])
        self.assertEqual(bundle["memory_items"], [])

    def test_aggregate_preference_topic_miss_excludes_unrelated_memory_items(self) -> None:
        from backend.app.core.context_memory import get_context_memory
        from backend.app.core.database import connect
        from backend.app.core.temporal_facts import sync_chat_session_temporal_facts

        self._message("user-tea", "user", "I prefer tea.", "2025-01-01T10:00:00+00:00")
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions (id, vault_id, title, created_at, updated_at)
                VALUES ('session-2', 'vault-1', 'More preferences', ?, ?)
                """,
                ("2025-02-01T00:00:00+00:00", "2025-02-01T00:00:00+00:00"),
            )
            conn.execute(
                """
                INSERT INTO chat_messages (
                    id, session_id, role, content, clusters_used, citations, warnings, created_at
                ) VALUES ('user-coffee', 'session-2', 'user', 'I avoid coffee.', '[]', '[]', '[]', ?)
                """,
                ("2025-02-01T10:00:00+00:00",),
            )
            for session_id in ("session-1", "session-2"):
                messages = conn.execute(
                    "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at",
                    (session_id,),
                ).fetchall()
                sync_chat_session_temporal_facts(
                    conn, vault_id="vault-1", session_id=session_id, messages=messages
                )
            items, _ = get_context_memory(
                conn,
                vault_id="vault-1",
                cluster_id=None,
                query="What is my favorite editor now?",
            )

        self.assertEqual(items, [])

    def test_bounded_favorite_question_leaves_matching_fact_to_ordinary_retrieval(self) -> None:
        from backend.app.core.context_memory import get_context_memory
        from backend.app.core.database import connect
        from backend.app.core.temporal_facts import sync_chat_session_temporal_facts

        self._message(
            "user-book",
            "user",
            'Melanie said, "My favorite childhood book is The Hobbit."',
            "2025-01-01T10:00:00+00:00",
        )
        with connect() as conn:
            messages = conn.execute(
                "SELECT * FROM chat_messages WHERE session_id = 'session-1' ORDER BY created_at"
            ).fetchall()
            sync_chat_session_temporal_facts(
                conn, vault_id="vault-1", session_id="session-1", messages=messages
            )
            items, _ = get_context_memory(
                conn,
                vault_id="vault-1",
                cluster_id=None,
                query="What was Melanie's favorite childhood book?",
            )

        self.assertEqual(items, [])

    def test_edit_retracts_obsolete_fact_without_deleting_history(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.temporal_facts import sync_chat_session_temporal_facts

        self._message("user-1", "user", "I prefer tea.", "2025-01-01T10:00:00+00:00")
        with connect() as conn:
            messages = conn.execute("SELECT * FROM chat_messages WHERE session_id = 'session-1'").fetchall()
            sync_chat_session_temporal_facts(
                conn, vault_id="vault-1", session_id="session-1", messages=messages
            )
            conn.execute("UPDATE chat_messages SET content = 'No preference stated.' WHERE id = 'user-1'")
            messages = conn.execute("SELECT * FROM chat_messages WHERE session_id = 'session-1'").fetchall()
            result = sync_chat_session_temporal_facts(
                conn, vault_id="vault-1", session_id="session-1", messages=messages
            )
            row = conn.execute("SELECT status FROM temporal_facts WHERE source_id = 'user-1'").fetchone()

        self.assertEqual(result["retracted_count"], 1)
        self.assertEqual(row["status"], "retracted")

    def test_v3_extractor_captures_multiple_explicit_fact_families(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.temporal_facts import sync_chat_session_temporal_facts

        self._message(
            "user-profile",
            "user",
            "My name is Priya. I work as a product designer. My timezone is Asia/Kolkata. Remember that my passport expires in 2028.",
            "2025-01-01T10:00:00+00:00",
        )
        with connect() as conn:
            messages = conn.execute("SELECT * FROM chat_messages WHERE session_id = 'session-1'").fetchall()
            sync_chat_session_temporal_facts(
                conn, vault_id="vault-1", session_id="session-1", messages=messages
            )
            rows = conn.execute(
                "SELECT predicate_key, object_text, metadata_json FROM temporal_facts ORDER BY predicate_key"
            ).fetchall()
            state = conn.execute(
                "SELECT extractor_version FROM temporal_fact_session_state WHERE session_id = 'session-1'"
            ).fetchone()

        self.assertEqual(
            {(row["predicate_key"], row["object_text"]) for row in rows},
            {
                ("name", "Priya"),
                ("role", "product designer"),
                ("timezone", "Asia/Kolkata"),
                ("stated_fact", "my passport expires in 2028"),
            },
        )
        self.assertEqual(state["extractor_version"], "chat-facts-v3")

    def test_v3_extractor_splits_compound_preferences_without_inference(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.temporal_facts import sync_chat_session_temporal_facts

        self._message(
            "user-compound",
            "user",
            "I love hiking, but I hate crowded trails. My favorite editor is VS Code.",
            "2025-01-01T10:00:00+00:00",
        )
        with connect() as conn:
            messages = conn.execute("SELECT * FROM chat_messages WHERE session_id = 'session-1'").fetchall()
            sync_chat_session_temporal_facts(
                conn, vault_id="vault-1", session_id="session-1", messages=messages
            )
            rows = conn.execute(
                """
                SELECT predicate_key, object_text, citation_excerpt, supersession_key
                FROM temporal_facts ORDER BY object_text
                """
            ).fetchall()

        self.assertEqual(
            {(row["predicate_key"], row["object_text"]) for row in rows},
            {
                ("avoids", "crowded trails"),
                ("prefers", "hiking"),
                ("prefers", "VS Code"),
            },
        )
        source_text = "I love hiking, but I hate crowded trails. My favorite editor is VS Code."
        self.assertTrue(all(row["citation_excerpt"] in source_text for row in rows))
        favorite = next(row for row in rows if row["object_text"] == "VS Code")
        self.assertEqual(favorite["supersession_key"], "user:preference:favorite:editor")

    def test_v3_resolves_safe_action_dates_without_backdating_current_state(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.temporal_facts import sync_chat_session_temporal_facts

        self._message(
            "user-dates",
            "user",
            "I visited Kyoto yesterday. I moved to Berlin last week.",
            "2025-05-15T18:30:00+00:00",
        )
        with connect() as conn:
            messages = conn.execute("SELECT * FROM chat_messages WHERE session_id = 'session-1'").fetchall()
            sync_chat_session_temporal_facts(
                conn, vault_id="vault-1", session_id="session-1", messages=messages
            )
            rows = conn.execute(
                "SELECT assertion_kind, object_text, valid_from, metadata_json FROM temporal_facts"
            ).fetchall()

        by_kind = {row["assertion_kind"]: row for row in rows}
        action = by_kind["action"]
        state = by_kind["state"]
        self.assertEqual(action["object_text"], "visited Kyoto")
        self.assertEqual(action["valid_from"], "2025-05-14T00:00:00+00:00")
        self.assertEqual(json.loads(action["metadata_json"])["event_time_precision"], "day")
        self.assertEqual(state["object_text"], "Berlin")
        self.assertEqual(state["valid_from"], "2025-05-15T18:30:00+00:00")
        state_metadata = json.loads(state["metadata_json"])
        self.assertEqual(state_metadata["event_time_precision"], "week")
        self.assertIn("event_time_start", state_metadata)

    def test_user_correction_and_retraction_are_auditable(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.temporal_facts import (
            correct_temporal_fact,
            list_reviewable_temporal_facts,
            retract_temporal_fact,
            sync_chat_session_temporal_facts,
        )

        self._message("user-1", "user", "I live in London.", "2025-01-01T10:00:00+00:00")
        with connect() as conn:
            messages = conn.execute("SELECT * FROM chat_messages WHERE session_id = 'session-1'").fetchall()
            sync_chat_session_temporal_facts(
                conn, vault_id="vault-1", session_id="session-1", messages=messages
            )
            original = list_reviewable_temporal_facts(conn, vault_id="vault-1")[0]
            corrected = correct_temporal_fact(
                conn,
                vault_id="vault-1",
                fact_id=original["id"],
                object_text="Bengaluru",
                note="I moved before this conversation.",
            )
            retract_temporal_fact(
                conn,
                vault_id="vault-1",
                fact_id=corrected["id"],
                note="Do not use this location.",
            )
            reviews = conn.execute(
                "SELECT action, fact_id, replacement_fact_id FROM temporal_fact_reviews ORDER BY created_at, rowid"
            ).fetchall()
            original_status = conn.execute(
                "SELECT status FROM temporal_facts WHERE id = ?", (original["id"],)
            ).fetchone()["status"]

        self.assertEqual(corrected["object_text"], "Bengaluru")
        self.assertEqual(corrected["source_type"], "manual")
        self.assertEqual(original_status, "superseded")
        self.assertEqual([row["action"] for row in reviews], ["corrected", "retracted"])
        self.assertEqual(reviews[0]["replacement_fact_id"], corrected["id"])

    def test_retrieval_packing_reports_real_context_reduction(self) -> None:
        from backend.app.core.context_reduction import build_context_reduction_plan
        from backend.app.core.database import connect
        from backend.app.core.retrieval_telemetry import retrieval_packing_diagnostics

        plan = build_context_reduction_plan(
            prompt="What changed in the release plan?",
            citations=[
                {
                    "source_id": f"source-{index}",
                    "source_title": f"Release note {index}",
                    "snippet": ("The release plan changed after testing. " * 80) + str(index),
                    "score": 1 - index / 20,
                }
                for index in range(12)
            ],
            recent_turns=[],
            memory_items=[],
            working_memory={},
            token_budget=700,
        )
        diagnostics = plan["diagnostics"]
        self.assertGreater(diagnostics["raw_context_tokens"], diagnostics["final_context_tokens"])
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_messages (
                    id, session_id, role, content, clusters_used, citations, warnings, created_at
                ) VALUES ('message-1', 'session-1', 'assistant', 'Answer', '[]', '[]', '[]',
                          '2025-01-01T00:00:00+00:00')
                """
            )
            conn.execute(
                """
                INSERT INTO retrieval_snapshots (
                    id, message_id, session_id, vault_id, query, retrieval_mode,
                    context_strategy, candidate_citation_count, selected_citation_count,
                    raw_context_tokens_estimate, final_context_tokens_estimate,
                    raw_candidate_tokens_estimate, evidence_tokens_estimate, created_at
                ) VALUES ('snapshot-telemetry', 'message-1', 'session-1', 'vault-1', 'query', 'semantic',
                          'salient_dedupe_v1', 12, 3, ?, ?, ?, ?, '2025-01-01T00:00:00+00:00')
                """,
                (
                    diagnostics["raw_context_tokens"],
                    diagnostics["final_context_tokens"],
                    diagnostics["raw_candidate_tokens"],
                    plan["evidence_tokens_estimate"],
                ),
            )
            result = retrieval_packing_diagnostics(conn, vault_id="vault-1")

        self.assertEqual(result["query_count"], 1)
        self.assertEqual(result["candidate_citation_count"], 12)
        self.assertEqual(result["selected_citation_count"], 3)
        self.assertGreater(result["context_tokens_avoided"], 0)
        self.assertGreater(result["context_reduction_percent"], 0)


if __name__ == "__main__":
    unittest.main()
