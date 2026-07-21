from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path


class AtomicMemoryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["CML_DATABASE_PATH"] = str(Path(self.tmp.name) / "atomic-store.sqlite3")
        os.environ["CML_DATA_DIR"] = self.tmp.name

        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        from backend.app.core.database import connect, init_db

        init_db()
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO vaults (id, name, path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "vault-1",
                    "Test",
                    self.tmp.name,
                    "2025-01-01T00:00:00+00:00",
                    "2025-01-01T00:00:00+00:00",
                ),
            )
            conn.execute(
                """
                INSERT INTO chat_sessions (id, vault_id, title, created_at, updated_at)
                VALUES ('session-1', 'vault-1', 'History', ?, ?)
                """,
                ("2025-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"),
            )
            conn.execute(
                """
                INSERT INTO chat_messages (
                    id, session_id, role, content, clusters_used, citations, warnings, created_at
                ) VALUES ('message-1', 'session-1', 'user', ?, '[]', '[]', '[]', ?)
                """,
                ("I now have three aquariums. Two contain fish.", "2025-01-02T10:00:00+00:00"),
            )

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        os.environ.pop("CML_DATABASE_PATH", None)
        os.environ.pop("CML_DATA_DIR", None)
        self.tmp.cleanup()

    def test_production_sync_persists_loads_and_retracts_atomic_memory(self) -> None:
        from backend.app.core.atomic_memory_store import load_atomic_facts_for_sessions
        from backend.app.core.database import connect
        from backend.app.core.temporal_facts import sync_chat_session_temporal_facts

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
            facts = load_atomic_facts_for_sessions(
                conn, vault_id="vault-1", session_ids=["session-1"]
            )
            current_count = conn.execute(
                "SELECT COUNT(*) AS count FROM atomic_memory_facts WHERE status = 'current'"
            ).fetchone()["count"]
            state = conn.execute(
                "SELECT * FROM atomic_memory_session_state WHERE session_id = 'session-1'"
            ).fetchone()

            conn.execute(
                """
                UPDATE chat_messages SET content = 'I now have four aquariums.'
                WHERE id = 'message-1'
                """
            )
            changed_messages = conn.execute(
                "SELECT * FROM chat_messages WHERE session_id = 'session-1' ORDER BY created_at"
            ).fetchall()
            sync_chat_session_temporal_facts(
                conn,
                vault_id="vault-1",
                session_id="session-1",
                messages=changed_messages,
            )
            retracted_count = conn.execute(
                "SELECT COUNT(*) AS count FROM atomic_memory_facts WHERE status = 'retracted'"
            ).fetchone()["count"]

        self.assertGreater(first["atomic_memory"]["fact_count"], 0)
        self.assertTrue(first["atomic_memory"]["source_coverage_complete"])
        self.assertEqual(first["atomic_memory"], second["atomic_memory"])
        self.assertEqual(len(facts), current_count)
        self.assertEqual(state["source_unit_count"], state["covered_source_unit_count"])
        self.assertGreater(retracted_count, 0)
