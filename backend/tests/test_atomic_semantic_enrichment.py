from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class AtomicSemanticEnrichmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["CML_DATABASE_PATH"] = str(Path(self.tmp.name) / "semantic.sqlite3")
        os.environ["CML_DATA_DIR"] = self.tmp.name
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"
        os.environ["CML_LLM_PROVIDER"] = "openai-compatible"
        os.environ["CML_LLM_BASE_URL"] = "http://127.0.0.1:8084/v1"
        os.environ["CML_LLM_MODEL"] = "test-local"
        os.environ["CML_ATOMIC_SEMANTIC_ENRICHMENT_ENABLED"] = "1"

        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        from backend.app.core.database import connect, init_db

        init_db()
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO vaults (id, name, path, created_at, updated_at)
                VALUES ('vault-1', 'Test', ?, ?, ?)
                """,
                (self.tmp.name, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
            )
            conn.execute(
                """
                INSERT INTO chat_sessions (id, vault_id, title, created_at, updated_at)
                VALUES ('session-1', 'vault-1', 'Visit', ?, ?)
                """,
                ("2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
            )
            conn.execute(
                """
                INSERT INTO chat_messages (
                    id, session_id, role, content, clusters_used, citations, warnings, created_at
                ) VALUES ('message-1', 'session-1', 'user', ?, '[]', '[]', '[]', ?)
                """,
                ("I saw Dr. Lee today.", "2026-01-02T10:00:00+00:00"),
            )

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        for key in (
            "CML_DATABASE_PATH",
            "CML_DATA_DIR",
            "CML_EMBEDDING_PROVIDER",
            "CML_ALLOW_HASH_EMBEDDINGS",
            "CML_LLM_PROVIDER",
            "CML_LLM_BASE_URL",
            "CML_LLM_MODEL",
            "CML_ATOMIC_SEMANTIC_ENRICHMENT_ENABLED",
        ):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def test_job_persists_validated_local_facts_and_stales_them_on_edit(self) -> None:
        from backend.app.core.background_jobs import (
            _enqueue_atomic_semantic_enrichment,
            run_due_jobs_once,
        )
        from backend.app.core.atomic_memory_store import (
            atomic_memory_coverage_report,
            load_atomic_facts_for_sessions,
        )
        from backend.app.core.database import connect
        from backend.app.core.llm_runtime import LLMResult
        from backend.app.core.temporal_facts import sync_chat_session_temporal_facts

        response = {
            "sessions": [
                {
                    "session_id": "session-1",
                    "facts": [
                        {
                            "fact_id": "semantic-visit",
                            "citation": {
                                "turn_index": 0,
                                "excerpt": "I saw Dr. Lee today.",
                            },
                            "subject": "user",
                            "predicate": "visited",
                            "object_text": "Dr. Lee",
                            "fact_kind": "event",
                            "confidence": 0.95,
                        },
                        {
                            "fact_id": "invalid-citation",
                            "citation": {"turn_index": 0, "excerpt": "Dr. Patel"},
                            "subject": "user",
                            "predicate": "visited",
                            "object_text": "Dr. Patel",
                            "fact_kind": "event",
                            "confidence": 0.95,
                        },
                    ],
                }
            ]
        }
        with connect() as conn:
            messages = conn.execute(
                "SELECT * FROM chat_messages WHERE session_id = 'session-1'"
            ).fetchall()
            sync_chat_session_temporal_facts(
                conn, vault_id="vault-1", session_id="session-1", messages=messages
            )
            job = _enqueue_atomic_semantic_enrichment(
                conn, vault_id="vault-1", session_id="session-1"
            )
        self.assertIsNotNone(job)

        with (
            patch(
                "backend.app.core.llm_runtime.runtime_status",
                return_value={"available": True, "state": "ready"},
            ),
            patch(
                "backend.app.core.llm_runtime.generate_local_structured_json",
                return_value=LLMResult(
                    text=json.dumps(response),
                    provider="openai-compatible",
                    model="test-local",
                ),
            ),
        ):
            self.assertEqual(run_due_jobs_once(limit=1), 1)

        with connect() as conn:
            state = conn.execute(
                "SELECT * FROM atomic_memory_semantic_state WHERE session_id = 'session-1'"
            ).fetchone()
            facts = load_atomic_facts_for_sessions(
                conn, vault_id="vault-1", session_ids=["session-1"]
            )
            coverage = atomic_memory_coverage_report(conn, vault_id="vault-1")
            duplicate = _enqueue_atomic_semantic_enrichment(
                conn, vault_id="vault-1", session_id="session-1"
            )
            conn.execute(
                "UPDATE chat_messages SET content = 'I stayed home today.' WHERE id = 'message-1'"
            )
            messages = conn.execute(
                "SELECT * FROM chat_messages WHERE session_id = 'session-1'"
            ).fetchall()
            sync_chat_session_temporal_facts(
                conn, vault_id="vault-1", session_id="session-1", messages=messages
            )
            stale = conn.execute(
                "SELECT status FROM atomic_memory_semantic_state WHERE session_id = 'session-1'"
            ).fetchone()
            refreshed = _enqueue_atomic_semantic_enrichment(
                conn, vault_id="vault-1", session_id="session-1"
            )

        self.assertEqual(state["status"], "current")
        self.assertEqual(state["fact_count"], 1)
        self.assertEqual(state["invalid_fact_count"], 1)
        self.assertTrue(
            any(
                fact.predicate == "visited" and fact.object_text == "Dr. Lee"
                for fact in facts
            )
        )
        self.assertEqual(coverage["semantic_current_session_count"], 1)
        self.assertEqual(coverage["semantic_fact_count"], 1)
        self.assertEqual(coverage["semantic_invalid_fact_count"], 1)
        self.assertIsNone(duplicate)
        self.assertEqual(stale["status"], "stale")
        self.assertIsNotNone(refreshed)

    def test_structured_runtime_rejects_non_loopback_endpoint(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.llm_runtime import (
            LLMRuntimeError,
            generate_local_structured_json,
        )

        os.environ["CML_LLM_BASE_URL"] = "https://api.example.com/v1"
        get_settings.cache_clear()
        with patch("backend.app.core.llm_runtime._openai_post") as request:
            with self.assertRaisesRegex(LLMRuntimeError, "loopback-only"):
                generate_local_structured_json(system_prompt="system", user_prompt="user")
        request.assert_not_called()

    def test_structured_runtime_sends_bounded_llamacpp_schema(self) -> None:
        from backend.app.core.llm_runtime import generate_local_structured_json

        schema = {
            "type": "object",
            "properties": {"sessions": {"type": "array"}},
            "required": ["sessions"],
        }
        with patch(
            "backend.app.core.llm_runtime._openai_post",
            return_value={"choices": [{"message": {"content": '{"sessions":[]}'}}]},
        ) as request:
            result = generate_local_structured_json(
                system_prompt="system",
                user_prompt="user",
                max_tokens=256,
                json_schema=schema,
            )

        payload = request.call_args.args[1]
        self.assertEqual(result.text, '{"sessions":[]}')
        self.assertEqual(payload["max_tokens"], 256)
        self.assertEqual(
            payload["response_format"],
            {"type": "json_object", "schema": schema},
        )
        self.assertEqual(
            payload["chat_template_kwargs"],
            {"enable_thinking": False},
        )
