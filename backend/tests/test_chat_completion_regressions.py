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

    def test_new_chat_attachments_are_the_only_retrieval_scope_and_remain_available_for_follow_up(self) -> None:
        from backend.app.api.routes.chat import build_chat_context
        from backend.app.schemas import ChatAttachmentInput, ChatContextRequest

        syllabus = Path(self.tmp.name) / "Python syllabus.txt"
        pledge = Path(self.tmp.name) / "Course pledge.txt"
        syllabus.write_text(
            "The Python course covers variables, loops, functions, object-oriented programming, "
            "web development, APIs, data science, and automation. " * 20,
            encoding="utf-8",
        )
        pledge.write_text(
            "The learner pledges to practise daily, complete the exercises, and keep building "
            "through the one hundred day Python course. " * 20,
            encoding="utf-8",
        )

        first = build_chat_context(
            ChatContextRequest(
                vault_id="vault-chat",
                prompt="What are these documents about?",
                attachments=[
                    ChatAttachmentInput(path=str(syllabus)),
                    ChatAttachmentInput(path=str(pledge)),
                ],
            )
        )
        attached_ids = {item["source_id"] for item in first["attachments_stored"]}
        cited_ids = {item["source_id"] for item in first["citations"]}

        self.assertEqual(first["intent"], "attachment_question")
        self.assertEqual(len(attached_ids), 2)
        self.assertEqual(cited_ids, attached_ids)
        self.assertEqual(first["coverage_ledger"]["sources_considered"], 2)
        self.assertEqual(first["coverage_ledger"]["sources_analyzed"], 2)
        self.assertEqual(
            set(first["coverage_ledger"]["attachment_source_ids"]),
            attached_ids,
        )

        follow_up = build_chat_context(
            ChatContextRequest(
                vault_id="vault-chat",
                session_id=first["session_id"],
                prompt="Compare these documents and explain how they fit together.",
            )
        )
        follow_up_ids = {item["source_id"] for item in follow_up["citations"]}

        self.assertEqual(follow_up["intent"], "attachment_question")
        self.assertEqual(follow_up_ids, attached_ids)

        unrelated = build_chat_context(
            ChatContextRequest(
                vault_id="vault-chat",
                session_id=first["session_id"],
                prompt="How do decorators work in JavaScript?",
            )
        )
        self.assertEqual(unrelated["intent"], "general_chat")
        self.assertEqual(unrelated["citations"], [])

    def test_cluster_scope_does_not_capture_unrelated_general_questions(self) -> None:
        from backend.app.api.routes.chat import _classify_chat_route
        from backend.app.schemas import ChatContextRequest

        general = _classify_chat_route(
            ChatContextRequest(
                vault_id="vault-chat",
                cluster_id="cluster-one",
                prompt="How do Python decorators work?",
            ),
            source_count=20,
        )
        grounded = _classify_chat_route(
            ChatContextRequest(
                vault_id="vault-chat",
                cluster_id="cluster-one",
                prompt="What do the documents in this cluster say about decorators?",
            ),
            source_count=20,
        )

        self.assertEqual(general["intent"], "general_chat")
        self.assertEqual(general["reason"], "obvious_world_knowledge")
        self.assertEqual(grounded["intent"], "cluster_question")

    def test_two_thousand_message_chat_opens_as_bounded_cursor_pages(self) -> None:
        from backend.app.api.routes.chat import (
            get_chat_session_metadata,
            get_chat_timeline,
        )
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions (
                    id, vault_id, title, saved, created_at, updated_at
                )
                VALUES ('chat-long', 'vault-chat', 'Long chat', 0, ?, ?)
                """,
                (now, now),
            )
            conn.executemany(
                """
                INSERT INTO chat_messages (
                    id, session_id, role, content, clusters_used, citations,
                    warnings, saved, created_at
                )
                VALUES (?, 'chat-long', ?, ?, '[]', '[]', '[]', 0, ?)
                """,
                [
                    (
                        f"msg-{index:04d}",
                        "user" if index % 2 == 0 else "assistant",
                        f"Message {index}",
                        (
                            f"2026-01-{1 + index // 1440:02d}T"
                            f"{(index // 60) % 24:02d}:{index % 60:02d}:00.000000+00:00"
                        ),
                    )
                    for index in range(2000)
                ],
            )

        metadata = get_chat_session_metadata("chat-long")
        newest = get_chat_timeline("chat-long")
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_messages (
                    id, session_id, role, content, clusters_used, citations,
                    warnings, saved, created_at
                )
                VALUES (
                    'msg-2000', 'chat-long', 'assistant', 'Message 2000',
                    '[]', '[]', '[]', 0, '2026-01-02T09:20:00.000000+00:00'
                )
                """
            )
            # A retention pass may delete the exact row represented by an older
            # cursor. The timestamp-plus-ID boundary must still remain usable.
            conn.execute("DELETE FROM chat_messages WHERE id = 'msg-1920'")
        delta = get_chat_timeline(
            "chat-long",
            cursor=newest["latest_cursor"],
            direction="newer",
        )
        older = get_chat_timeline(
            "chat-long",
            cursor=newest["next_cursor"],
            direction="older",
        )

        self.assertEqual(metadata["messages"], [])
        self.assertEqual(len(newest["items"]), 80)
        self.assertTrue(newest["has_more"])
        self.assertEqual(newest["items"][0]["content"], "Message 1920")
        self.assertEqual(newest["items"][-1]["content"], "Message 1999")
        self.assertEqual([item["content"] for item in delta["items"]], ["Message 2000"])
        self.assertEqual(len(older["items"]), 80)
        self.assertEqual(older["items"][0]["content"], "Message 1840")
        self.assertEqual(older["items"][-1]["content"], "Message 1919")
        self.assertFalse(
            {item["id"] for item in newest["items"]}
            & {item["id"] for item in older["items"]}
        )


if __name__ == "__main__":
    unittest.main()
