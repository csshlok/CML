import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ChatMemoryIncrementalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        os.environ["CML_DATABASE_PATH"] = str(Path(self.tmp.name) / "chat-memory.sqlite3")
        os.environ["CML_DATA_DIR"] = self.tmp.name
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"
        from backend.app.core.config import get_settings
        from backend.app.core.database import init_db

        get_settings.cache_clear()
        init_db()

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

    def test_long_transcript_indexes_a_bounded_window_and_skips_unchanged_generation(self) -> None:
        import backend.app.core.chat_memory as chat_memory
        from backend.app.core.database import connect, utc_now
        from backend.app.core.encrypted_storage import source_from_encrypted_row

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )
            conn.execute(
                "INSERT INTO chat_sessions (id, vault_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("session-1", "vault-1", "Long chat", now, now),
            )
            conn.executemany(
                """
                INSERT INTO chat_messages (
                    id, session_id, role, content, clusters_used, citations, warnings, created_at
                ) VALUES (?, 'session-1', ?, ?, '[]', '[]', '[]', ?)
                """,
                [
                    (
                        f"message-{index}",
                        "user" if index % 2 == 0 else "assistant",
                        f"message body {index} " + ("detail " * 30),
                        f"2026-01-01T00:{index // 60:02d}:{index % 60:02d}+00:00",
                    )
                    for index in range(120)
                ],
            )

            with patch.object(
                chat_memory,
                "reindex_source_chunks",
                wraps=chat_memory.reindex_source_chunks,
            ) as reindex:
                chat_memory.upsert_chat_transcript_sources(
                    conn, vault_id="vault-1", session_id="session-1"
                )
                first_calls = reindex.call_count
                chat_memory.upsert_chat_transcript_sources(
                    conn, vault_id="vault-1", session_id="session-1"
                )
                self.assertEqual(reindex.call_count, first_calls)

                conn.execute(
                    """
                    INSERT INTO chat_messages (
                        id, session_id, role, content, clusters_used, citations, warnings, created_at
                    ) VALUES ('message-120', 'session-1', 'user', 'new tail fact', '[]', '[]', '[]', ?)
                    """,
                    ("2026-01-01T00:02:00+00:00",),
                )
                chat_memory.upsert_chat_transcript_sources(
                    conn, vault_id="vault-1", session_id="session-1"
                )
                self.assertGreater(reindex.call_count, first_calls)

            source_row = conn.execute(
                "SELECT * FROM sources WHERE source_type = 'chat_transcript' LIMIT 1"
            ).fetchone()
            source = source_from_encrypted_row(conn, source_row)
            state = conn.execute(
                "SELECT * FROM chat_transcript_memory_state WHERE session_id = 'session-1'"
            ).fetchone()

        self.assertIn("Recent 40 of 121 messages", source["raw_text"])
        self.assertIn("new tail fact", source["raw_text"])
        self.assertLessEqual(len(source["raw_text"]), chat_memory.TRANSCRIPT_INDEX_MAX_CHARS)
        self.assertLessEqual(len(source["summary"]), chat_memory.TRANSCRIPT_SUMMARY_MAX_CHARS)
        self.assertEqual(state["source_message_count"], 121)


if __name__ == "__main__":
    unittest.main()
