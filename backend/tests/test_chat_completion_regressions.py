import os
import tempfile
import unittest
from pathlib import Path


class ChatCompletionRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["CML_DATABASE_PATH"] = str(Path(self.tmp.name) / "test.sqlite3")
        os.environ["CML_DATA_DIR"] = self.tmp.name
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"

        from backend.app.core.config import get_settings
        from backend.app.core.database import connect, init_db, utc_now

        get_settings.cache_clear()
        init_db()
        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-chat", "Chat", self.tmp.name, now, now),
            )

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        for key in (
            "CML_DATABASE_PATH",
            "CML_DATA_DIR",
            "CML_EMBEDDING_PROVIDER",
            "CML_ALLOW_HASH_EMBEDDINGS",
        ):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def test_completed_answer_is_recent_and_updates_memory_history_immediately(self) -> None:
        from backend.app.api.routes.chat import (
            _complete_chat_generation,
            _start_chat_generation,
            list_recent_chat_generations,
        )
        from backend.app.core.database import connect

        generation = _start_chat_generation(
            vault_id="vault-chat",
            session_id=None,
            cluster_id=None,
            prompt="I live in Pune.",
        )
        _complete_chat_generation(
            generation_id=generation["generation_id"],
            session_id=generation["session_id"],
            assistant_message_id=generation["assistant_message_id"],
            vault_id="vault-chat",
            prompt="I live in Pune.",
            answer="I will remember that you live in Pune.",
            clusters_used=[],
            citations=[],
            token_budget=256,
            warnings=[],
        )

        recent = list_recent_chat_generations("vault-chat")
        self.assertEqual(recent["items"][0]["id"], generation["generation_id"])
        self.assertEqual(recent["items"][0]["state"], "completed")

        with connect() as conn:
            state = conn.execute(
                """
                SELECT source_message_count, fact_count
                FROM temporal_fact_session_state
                WHERE session_id = ?
                """,
                (generation["session_id"],),
            ).fetchone()
            fact = conn.execute(
                """
                SELECT object_text
                FROM temporal_facts
                WHERE session_id = ? AND predicate_key = 'lives_in' AND status = 'current'
                """,
                (generation["session_id"],),
            ).fetchone()

        self.assertEqual(state["source_message_count"], 2)
        self.assertGreaterEqual(state["fact_count"], 1)
        self.assertEqual(fact["object_text"], "Pune")

    def test_chat_message_hydration_returns_attachment_names_without_rewriting_prompt(self) -> None:
        from backend.app.api.routes.chat import _messages_from_rows, _start_chat_generation
        from backend.app.core.database import connect, utc_now

        generation = _start_chat_generation(
            vault_id="vault-chat",
            session_id=None,
            cluster_id=None,
            prompt="Summarize this file.",
        )
        now = utc_now()
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO sources (
                    id, vault_id, title, source_type, state, raw_text, extracted_text,
                    summary, tags, created_at, updated_at
                ) VALUES (?, ?, ?, 'file', 'indexed', ?, ?, ?, '[]', ?, ?)
                """,
                (
                    "source-attachment",
                    "vault-chat",
                    "Syllabus for Python.pdf",
                    "Course outline",
                    "Course outline",
                    "Course outline",
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO chat_attachments (
                    id, session_id, message_id, source_id, file_name, original_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "attachment-1",
                    generation["session_id"],
                    generation["user_message_id"],
                    "source-attachment",
                    "Syllabus+for+Python.pdf",
                    "C:\\Docs\\Syllabus+for+Python.pdf",
                    now,
                ),
            )
            rows = conn.execute(
                "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at, rowid",
                (generation["session_id"],),
            ).fetchall()
            messages = _messages_from_rows(conn, rows)

        self.assertEqual(messages[0]["content"], "Summarize this file.")
        self.assertEqual(messages[0]["attachments"], ["Syllabus+for+Python.pdf"])


if __name__ == "__main__":
    unittest.main()
