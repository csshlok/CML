from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch


def _clear_settings() -> None:
    from backend.app.core.config import get_settings

    get_settings.cache_clear()


def _configure(tmp_path: Path, *, retrieval: bool = True) -> None:
    os.environ["CML_DATABASE_PATH"] = str(tmp_path / "v2-production.sqlite3")
    os.environ["CML_DATA_DIR"] = str(tmp_path)
    os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
    os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"
    os.environ["CML_LLM_PROVIDER"] = "openai-compatible"
    os.environ["CML_LLM_BASE_URL"] = "http://127.0.0.1:8084/v1"
    os.environ["CML_LLM_MODEL"] = "chat-model"
    os.environ["CML_ATOMIC_EXTRACTOR_MODEL"] = "extractor-model"
    os.environ["CML_ATOMIC_SEMANTIC_ENRICHMENT_ENABLED"] = "1"
    os.environ["CML_ATOMIC_SEMANTIC_EXTRACTOR_CONTRACT"] = "v2_evidence"
    os.environ["CML_ATOMIC_V2_RETRIEVAL_ENABLED"] = "1" if retrieval else "0"
    _clear_settings()


def _seed() -> None:
    from backend.app.core.database import connect, init_db

    init_db()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO vaults (id, name, path, created_at, updated_at)
            VALUES ('vault-1', 'Test', 'test', ?, ?)
            """,
            ("2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
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
            (
                "I visited cardiologist Dr. Lee on January 2.",
                "2026-01-02T10:00:00+00:00",
            ),
        )


def _response() -> str:
    return json.dumps(
        {
            "session_id": "session-1",
            "spans": [
                {
                    "span_id": "memory-1",
                    "citation": {
                        "turn_index": 0,
                        "excerpt": "I visited cardiologist Dr. Lee on January 2.",
                    },
                    "memory_text": "The user visited cardiologist Dr. Lee on January 2.",
                    "attributed_to": "user",
                    "evidence_kinds": ["entity", "event"],
                    "confidence": 0.96,
                },
                {
                    "span_id": "bad-citation",
                    "citation": {
                        "turn_index": 0,
                        "excerpt": "The user visited Dr. Patel.",
                    },
                    "memory_text": "The user visited Dr. Patel.",
                    "attributed_to": "user",
                    "evidence_kinds": ["entity", "event"],
                    "confidence": 0.95,
                },
            ],
        }
    )


def test_v2_production_job_uses_dedicated_model_and_retrieval_reads_fact() -> None:
    from backend.app.core.llm_runtime import LLMResult

    with tempfile.TemporaryDirectory() as directory:
        tmp_path = Path(directory)
        _configure(tmp_path)
        _seed()

        from backend.app.core.background_jobs import (
            _enqueue_atomic_semantic_enrichment,
            run_due_jobs_once,
        )
        from backend.app.core.context_memory import get_context_memory
        from backend.app.core.database import connect

        with connect() as conn:
            job = _enqueue_atomic_semantic_enrichment(
                conn, vault_id="vault-1", session_id="session-1"
            )
        assert job is not None

        with (
            patch(
                "backend.app.core.llm_runtime.runtime_status",
                return_value={"available": True, "state": "ready"},
            ),
            patch(
                "backend.app.core.llm_runtime.generate_local_structured_json",
                return_value=LLMResult(
                    text=_response(),
                    provider="openai-compatible",
                    model="extractor-model",
                ),
            ) as generate,
        ):
            assert run_due_jobs_once(limit=1) == 1

        assert generate.call_args.kwargs["model"] == "extractor-model"
        with connect() as conn:
            state = conn.execute(
                """
                SELECT extractor_version, model, fact_count, invalid_fact_count, status
                FROM atomic_memory_semantic_state
                WHERE session_id = 'session-1'
                """
            ).fetchone()
            items, _ = get_context_memory(
                conn,
                vault_id="vault-1",
                cluster_id=None,
                query="Which cardiologist did I visit?",
                limit=8,
            )

        assert state["extractor_version"] == "atomic-memory-v2-evidence-prod-v1"
        assert state["model"] == "extractor-model"
        assert state["fact_count"] == 1
        assert state["invalid_fact_count"] == 1
        assert state["status"] == "current"
        assert any(
            item["kind"] == "atomic_v2" and "Dr. Lee" in item["summary"]
            for item in items
        )
        assert not any("Dr. Patel" in item.get("summary", "") for item in items)


def test_v2_retrieval_flag_preserves_existing_production_output() -> None:
    from backend.app.core.llm_runtime import LLMResult

    with tempfile.TemporaryDirectory() as directory:
        tmp_path = Path(directory)
        _configure(tmp_path, retrieval=False)
        _seed()

        from backend.app.core.background_jobs import (
            _enqueue_atomic_semantic_enrichment,
            run_due_jobs_once,
        )
        from backend.app.core.context_memory import get_context_memory
        from backend.app.core.database import connect

        with connect() as conn:
            _enqueue_atomic_semantic_enrichment(
                conn, vault_id="vault-1", session_id="session-1"
            )
        with (
            patch(
                "backend.app.core.llm_runtime.runtime_status",
                return_value={"available": True, "state": "ready"},
            ),
            patch(
                "backend.app.core.llm_runtime.generate_local_structured_json",
                return_value=LLMResult(
                    text=_response(),
                    provider="openai-compatible",
                    model="extractor-model",
                ),
            ),
        ):
            assert run_due_jobs_once(limit=1) == 1
        with connect() as conn:
            items, _ = get_context_memory(
                conn,
                vault_id="vault-1",
                cluster_id=None,
                query="Which cardiologist did I visit?",
                limit=8,
            )
        assert not any(item.get("kind") == "atomic_v2" for item in items)


def test_v2_window_merge_restores_global_turn_provenance() -> None:
    from backend.app.core.atomic_memory_v2 import (
        AtomicMemoryV2EvidencePassResponse,
        atomic_memory_v2_session_windows,
        compile_atomic_memory_v2_evidence,
        merge_atomic_memory_v2_evidence_windows,
    )

    first = "A" * 400
    second = "The user moved to Lisbon. " + ("B" * 375)
    session = {
        "session_id": "session-windowed",
        "date": "2026-01-02",
        "turns": [
            {"role": "user", "content": first},
            {"role": "user", "content": second},
        ],
    }
    windows = atomic_memory_v2_session_windows(session, max_source_chars=512)
    assert len(windows) == 2
    response = AtomicMemoryV2EvidencePassResponse.model_validate(
        {
            "session_id": "session-windowed",
            "spans": [
                {
                    "span_id": "moved",
                    "citation": {
                        "turn_index": 0,
                        "excerpt": "The user moved to Lisbon.",
                    },
                    "memory_text": "The user moved to Lisbon.",
                    "attributed_to": "user",
                    "evidence_kinds": ["event"],
                    "confidence": 0.98,
                }
            ],
        }
    )
    extraction, invalid = compile_atomic_memory_v2_evidence(windows[1], response)
    merged, merged_invalid = merge_atomic_memory_v2_evidence_windows(
        session, [(windows[1], extraction, invalid)]
    )

    assert merged_invalid == {}
    assert len(merged.facts) == 1
    assert merged.facts[0].citation.turn_index == 1
    assert merged.source_units[1].status == "facts_extracted"


def teardown_module() -> None:
    for key in (
        "CML_DATABASE_PATH",
        "CML_DATA_DIR",
        "CML_EMBEDDING_PROVIDER",
        "CML_ALLOW_HASH_EMBEDDINGS",
        "CML_LLM_PROVIDER",
        "CML_LLM_BASE_URL",
        "CML_LLM_MODEL",
        "CML_ATOMIC_EXTRACTOR_MODEL",
        "CML_ATOMIC_SEMANTIC_ENRICHMENT_ENABLED",
        "CML_ATOMIC_SEMANTIC_EXTRACTOR_CONTRACT",
        "CML_ATOMIC_V2_RETRIEVAL_ENABLED",
    ):
        os.environ.pop(key, None)
    _clear_settings()
