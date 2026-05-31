import os
import tempfile
import unittest
from pathlib import Path


class SourcePageIndexingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.sqlite3"
        os.environ["CML_DATABASE_PATH"] = str(self.db_path)
        os.environ["CML_DATA_DIR"] = self.tmp.name
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"

        from backend.app.core.config import get_settings

        get_settings.cache_clear()

        from backend.app.core.database import init_db

        init_db()

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        os.environ.pop("CML_DATABASE_PATH", None)
        os.environ.pop("CML_DATA_DIR", None)
        os.environ.pop("CML_EMBEDDING_PROVIDER", None)
        os.environ.pop("CML_ALLOW_HASH_EMBEDDINGS", None)
        self.tmp.cleanup()

    def test_text_source_creates_page_and_page_linked_chunks(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )

        text = " ".join(f"word{i}" for i in range(260))
        source = create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Long note",
                source_type="note",
                raw_text=text,
            )
        )
        run_due_jobs_once(limit=1)

        with connect() as conn:
            pages = conn.execute(
                "SELECT * FROM source_pages WHERE source_id = ?",
                (source["id"],),
            ).fetchall()
            chunks = conn.execute(
                "SELECT * FROM source_chunks WHERE source_id = ? ORDER BY chunk_index",
                (source["id"],),
            ).fetchall()

        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["page_number"], 1)
        self.assertTrue(pages[0]["content_hash"])
        self.assertGreaterEqual(len(chunks), 1)
        self.assertTrue(all(chunk["page_id"] == pages[0]["id"] for chunk in chunks))
        self.assertTrue(all(chunk["content_hash"] for chunk in chunks))
        self.assertTrue(all(chunk["embedding_model_id"] for chunk in chunks))
        self.assertTrue(all(chunk["indexed_at"] for chunk in chunks))

    def test_deleted_source_is_hidden_and_content_removed_immediately(self) -> None:
        from backend.app.api.routes.search import semantic_search
        from backend.app.api.routes.sources import create_source, delete_source
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SemanticSearchRequest, SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )

        source = create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Searchable note",
                source_type="note",
                raw_text="alpha beta gamma " * 120,
            )
        )
        run_due_jobs_once(limit=1)

        delete_source(source["id"])

        result = semantic_search(SemanticSearchRequest(vault_id="vault-1", query="alpha beta"))

        self.assertEqual(result["results"], [])
        with connect() as conn:
            chunks_after_delete = conn.execute(
                "SELECT COUNT(*) AS count FROM source_chunks WHERE source_id = ?",
                (source["id"],),
            ).fetchone()["count"]
            pages_after_delete = conn.execute(
                "SELECT COUNT(*) AS count FROM source_pages WHERE source_id = ?",
                (source["id"],),
            ).fetchone()["count"]
            deleted = conn.execute(
                "SELECT raw_text, extracted_text, summary, original_path, url, checksum FROM sources WHERE id = ?",
                (source["id"],),
            ).fetchone()
        self.assertEqual(chunks_after_delete, 0)
        self.assertEqual(pages_after_delete, 0)
        self.assertEqual(deleted["raw_text"], "")
        self.assertEqual(deleted["extracted_text"], "")
        self.assertEqual(deleted["summary"], "")
        self.assertIsNone(deleted["original_path"])
        self.assertIsNone(deleted["url"])
        self.assertIsNone(deleted["checksum"])

    def test_vector_reconciliation_queues_missing_source_chunks(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.core.background_jobs import _run_vector_reconcile_incremental
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )

        source = create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Needs chunks",
                source_type="note",
                raw_text="delta epsilon zeta " * 120,
            )
        )
        with connect() as conn:
            conn.execute("DELETE FROM app_jobs")
            conn.execute("DELETE FROM source_chunks WHERE source_id = ?", (source["id"],))

        _run_vector_reconcile_incremental({"vault_id": "vault-1"})

        with connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM app_jobs
                WHERE job_type = 'reindex_source' AND status = 'queued'
                """
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertIn(source["id"], row["payload"])

    def test_vector_reconciliation_queues_stale_embedding_model_chunks(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.core.background_jobs import _run_vector_reconcile_incremental, run_due_jobs_once
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )

        source = create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Stale chunks",
                source_type="note",
                raw_text="theta iota kappa " * 120,
            )
        )
        run_due_jobs_once(limit=1)
        with connect() as conn:
            conn.execute("DELETE FROM app_jobs")
            conn.execute(
                "UPDATE source_chunks SET embedding_model_id = 'old-model' WHERE source_id = ?",
                (source["id"],),
            )

        _run_vector_reconcile_incremental({"vault_id": "vault-1"})

        with connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM app_jobs
                WHERE job_type = 'reindex_source' AND status = 'queued'
                """
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertIn(source["id"], row["payload"])

    def test_duplicate_source_checksum_returns_existing_source(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )

        payload = SourceCreate(
            vault_id="vault-1",
            title="Duplicate candidate",
            source_type="note",
            raw_text="same source body " * 40,
        )
        first = create_source(payload)
        second = create_source(payload)

        with connect() as conn:
            source_count = conn.execute("SELECT COUNT(*) AS count FROM sources").fetchone()["count"]
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(source_count, 1)

    def test_code_and_media_files_are_ingestable(self) -> None:
        from backend.app.core.extraction import extract_pages_from_path

        code_path = Path(self.tmp.name) / "example.py"
        code_path.write_text("def hello():\n    return 'vault'\n", encoding="utf-8")
        media_path = Path(self.tmp.name) / "clip.mp4"
        media_path.write_bytes(b"not a real movie, but small media metadata is enough")

        code_title, code_pages = extract_pages_from_path(str(code_path))
        media_title, media_pages = extract_pages_from_path(str(media_path))

        self.assertEqual(code_title, "example.py")
        self.assertIn("Code file", code_pages[0])
        self.assertEqual(media_title, "clip.mp4")
        self.assertIn("Media file stored in vault metadata", media_pages[0])

    def test_chat_answer_writes_generation_and_retrieval_snapshot(self) -> None:
        from backend.app.api.routes.chat import build_chat_context
        from backend.app.api.routes.sources import create_source
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ChatContextRequest, SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )

        create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Runtime notes",
                source_type="note",
                raw_text="local runtime recovery citation snapshot durable retrieval " * 80,
            )
        )
        run_due_jobs_once(limit=1)

        response = build_chat_context(
            ChatContextRequest(vault_id="vault-1", prompt="runtime recovery citation snapshot")
        )

        with connect() as conn:
            generation = conn.execute(
                "SELECT * FROM chat_generations WHERE session_id = ?",
                (response["session_id"],),
            ).fetchone()
            snapshot = conn.execute(
                "SELECT * FROM retrieval_snapshots WHERE message_id = ?",
                (response["assistant_message_id"],),
            ).fetchone()
            items = conn.execute(
                "SELECT * FROM retrieval_snapshot_items WHERE snapshot_id = ?",
                (snapshot["id"],),
            ).fetchall()

        self.assertEqual(generation["state"], "completed")
        self.assertIsNotNone(snapshot)
        self.assertGreaterEqual(len(items), 1)
        self.assertTrue(items[0]["source_title_at_answer_time"])
        self.assertIsNotNone(response["coverage_ledger"])
        self.assertEqual(response["coverage_ledger"]["sources_considered"], 1)
        self.assertEqual(response["coverage_ledger"]["sources_analyzed"], 1)

    def test_chat_coverage_ledger_counts_low_relevance_sources(self) -> None:
        from backend.app.api.routes.chat import build_chat_context
        from backend.app.api.routes.sources import create_source
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ChatContextRequest, SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )

        create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Relevant note",
                source_type="note",
                raw_text="alpha beta complete scope evidence " * 80,
            )
        )
        create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Other note",
                source_type="note",
                raw_text="zebra orange unrelated archive " * 80,
            )
        )
        run_due_jobs_once(limit=2)

        response = build_chat_context(
            ChatContextRequest(vault_id="vault-1", prompt="what context has alpha beta", limit=1)
        )

        ledger = response["coverage_ledger"]
        self.assertEqual(ledger["sources_considered"], 2)
        self.assertEqual(ledger["sources_analyzed"], 1)
        self.assertEqual(ledger["sources_low_relevance"], 1)

    def test_chat_greeting_skips_retrieval_and_transcripts(self) -> None:
        from backend.app.api.routes.chat import build_chat_context
        from backend.app.api.routes.sources import create_source
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ChatContextRequest, SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )

        create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Chat transcript - old answer",
                source_type="note",
                raw_text="Chat transcript old semantic context that should not answer hello " * 80,
            )
        )
        run_due_jobs_once(limit=1)

        response = build_chat_context(ChatContextRequest(vault_id="vault-1", prompt="Hello"))

        self.assertIn("Hello", response["answer"])
        self.assertEqual(response["citations"], [])
        self.assertEqual(response["coverage_ledger"]["sources_analyzed"], 0)
        self.assertTrue(any("Answered directly" in warning for warning in response["warnings"]))

    def test_general_chat_without_runtime_is_degraded_not_retrieval(self) -> None:
        from backend.app.api.routes.chat import build_chat_context
        from backend.app.api.routes.sources import create_source
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ChatContextRequest, SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )
        create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Unrelated source",
                source_type="note",
                raw_text="this source should not be used for a general writing request " * 80,
            )
        )
        run_due_jobs_once(limit=1)

        response = build_chat_context(
            ChatContextRequest(vault_id="vault-1", prompt="write a short friendly email")
        )

        self.assertEqual(response["intent"], "general_chat")
        self.assertEqual(response["citations"], [])
        self.assertIn("local LLM runtime", response["answer"])

    def test_expanded_analysis_sets_intent_and_expands_analysis_set(self) -> None:
        from backend.app.api.routes.chat import build_chat_context
        from backend.app.api.routes.sources import create_source
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ChatContextRequest, SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )
        for index in range(3):
            create_source(
                SourceCreate(
                    vault_id="vault-1",
                    title=f"Context {index}",
                    source_type="note",
                    raw_text=f"complete analysis topic shared evidence {index} " * 80,
                )
            )
        run_due_jobs_once(limit=3)

        response = build_chat_context(
            ChatContextRequest(
                vault_id="vault-1",
                prompt="complete analysis topic",
                expanded_analysis=True,
            )
        )

        self.assertEqual(response["intent"], "expanded_analysis")
        self.assertEqual(response["coverage_ledger"]["sources_considered"], 3)
        self.assertGreaterEqual(response["coverage_ledger"]["sources_analyzed"], 1)

    def test_chat_attachment_is_ingested_as_cluster_source(self) -> None:
        from backend.app.api.routes.chat import build_chat_context
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ChatAttachmentInput, ChatContextRequest

        now = utc_now()
        attachment_path = Path(self.tmp.name) / "attached-note.txt"
        attachment_path.write_text("attached cluster evidence from chat upload " * 80, encoding="utf-8")
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (
                    id, vault_id, name, description, color, expert_status, created_at, updated_at
                )
                VALUES ('cluster-1', 'vault-1', 'Target', '', 'sage', 'setting-up', ?, ?)
                """,
                (now, now),
            )

        response = build_chat_context(
            ChatContextRequest(
                vault_id="vault-1",
                cluster_id="cluster-1",
                prompt="Read this attachment and store it in the target cluster",
                attachments=[ChatAttachmentInput(path=str(attachment_path))],
            )
        )

        with connect() as conn:
            source = conn.execute(
                "SELECT * FROM sources WHERE original_path = ?",
                (str(attachment_path),),
            ).fetchone()
            attachment = conn.execute(
                "SELECT * FROM chat_attachments WHERE source_id = ?",
                (source["id"],),
            ).fetchone()
            chunks = conn.execute(
                "SELECT COUNT(*) AS count FROM source_chunks WHERE source_id = ?",
                (source["id"],),
            ).fetchone()["count"]

        self.assertEqual(source["cluster_id"], "cluster-1")
        self.assertEqual(source["state"], "indexed")
        self.assertIsNotNone(attachment)
        self.assertGreater(chunks, 0)
        self.assertEqual(response["session_id"], attachment["session_id"])
        self.assertEqual(response["attachments_stored"][0]["source_id"], source["id"])

    def test_bridge_status_prunes_deleted_permission_ids(self) -> None:
        from backend.app.api.routes.bridge import bridge_status, update_bridge_settings
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import BridgeSettingsUpdate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )

        update_bridge_settings(
            BridgeSettingsUpdate(
                allowed_vault_ids=["vault-1", "deleted-vault"],
                allowed_cluster_ids=["deleted-cluster"],
            )
        )
        status = bridge_status()

        self.assertEqual(status["allowed_vault_ids"], ["vault-1"])
        self.assertEqual(status["allowed_cluster_ids"], [])
        self.assertTrue(status["last_refreshed_at"])

    def test_diagnostic_bundle_exports_redacted_support_zip(self) -> None:
        from pathlib import Path
        from zipfile import ZipFile

        from backend.app.api.routes.diagnostics import create_diagnostic_bundle
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )

        response = create_diagnostic_bundle()
        bundle_path = Path(response["bundle_path"])

        self.assertTrue(bundle_path.exists())
        self.assertIn("manifest.json", response["included_files"])
        with ZipFile(bundle_path) as bundle:
            self.assertIn("manifest.json", bundle.namelist())
            self.assertIn("database-summary.json", bundle.namelist())

    def test_startup_recovery_marks_in_flight_generations_retriable(self) -> None:
        from backend.app.core.database import connect, utc_now
        from backend.app.core.generation_recovery import recover_interrupted_generations

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )
            conn.execute(
                """
                INSERT INTO chat_sessions (
                    id, vault_id, title, scope_cluster_id, saved, memory_status,
                    memory_updated_at, created_at, updated_at
                )
                VALUES ('chat-1', 'vault-1', 'Recovery', NULL, 0, 'idle', NULL, ?, ?)
                """,
                (now, now),
            )
            conn.execute(
                """
                INSERT INTO chat_generations (
                    id, session_id, user_message_id, assistant_message_id, vault_id, prompt,
                    state, runtime_provider, runtime_model, error, heartbeat_at, created_at,
                    updated_at, completed_at
                )
                VALUES ('gen-1', 'chat-1', NULL, NULL, 'vault-1', 'hello', 'in_flight',
                    'none', '', '', ?, ?, ?, NULL)
                """,
                (now, now, now),
            )

        recovered = recover_interrupted_generations()

        with connect() as conn:
            row = conn.execute("SELECT state, error FROM chat_generations WHERE id = 'gen-1'").fetchone()
        self.assertEqual(recovered, 1)
        self.assertEqual(row["state"], "retriable")
        self.assertIn("interrupted", row["error"])

    def test_schema_migration_baseline_is_recorded(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.migrations import run_migrations

        run_migrations()

        with connect() as conn:
            row = conn.execute(
                "SELECT version, status FROM schema_migrations ORDER BY version DESC LIMIT 1"
            ).fetchone()
        self.assertEqual(row["version"], 1)
        self.assertEqual(row["status"], "succeeded")

    def test_disk_preflight_reports_available_space(self) -> None:
        from backend.app.core.preflight import disk_preflight

        result = disk_preflight(self.tmp.name, required_bytes=1)

        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["available_bytes"], 1)
        self.assertEqual(result["path"], self.tmp.name)

    def test_embedding_runtime_requires_local_model_path(self) -> None:
        from backend.app.core.embeddings import configure_embedding_runtime

        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "0"

        with self.assertRaises(ValueError):
            configure_embedding_runtime("sentence-transformers", None)

    def test_local_folder_scan_detects_obsidian_and_supported_files(self) -> None:
        from backend.app.core.local_integrations import scan_local_folder

        vault_path = Path(self.tmp.name) / "Notes"
        (vault_path / ".obsidian").mkdir(parents=True)
        (vault_path / "Research.md").write_text("local note", encoding="utf-8")
        (vault_path / "binary.exe").write_bytes(b"nope")

        result = scan_local_folder(str(vault_path), max_files=10)

        self.assertEqual(result["integration_type"], "obsidian")
        self.assertEqual(result["supported_count"], 1)
        self.assertTrue(result["supported_files"][0].endswith("Research.md"))
        self.assertEqual(result["skipped_count"], 1)

    def test_hardware_status_has_training_gate_fields(self) -> None:
        from backend.app.core.hardware import hardware_status

        result = hardware_status()

        self.assertIn("hardware_tier", result)
        self.assertIn("training_supported", result)
        self.assertIn(result["avx2"], {True, False, None})

    def test_integration_scan_records_import_history(self) -> None:
        from backend.app.api.routes.integrations import scan_local_folder_integration
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import LocalFolderScanRequest

        now = utc_now()
        folder = Path(self.tmp.name) / "Dropbox"
        folder.mkdir()
        (folder / "note.md").write_text("synced note", encoding="utf-8")
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )

        result = scan_local_folder_integration(
            LocalFolderScanRequest(vault_id="vault-1", path=str(folder), max_files=10)
        )

        self.assertIsNotNone(result["import_id"])
        with connect() as conn:
            row = conn.execute("SELECT * FROM integration_imports WHERE id = ?", (result["import_id"],)).fetchone()
        self.assertEqual(row["vault_id"], "vault-1")
        self.assertEqual(row["supported_count"], 1)

    def test_extension_capture_creates_source_and_capture_record(self) -> None:
        from backend.app.api.routes.extension import capture_from_extension, create_extension_client
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ExtensionCaptureRequest, ExtensionClientCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )
        client = create_extension_client(ExtensionClientCreate(name="Browser"))

        response = capture_from_extension(
            ExtensionCaptureRequest(
                vault_id="vault-1",
                capture_type="selection",
                title="Captured thought",
                url="https://example.com",
                text="browser extension captured local memory " * 40,
            ),
            x_cml_extension_token=client["token"],
        )
        run_due_jobs_once(limit=1)

        with connect() as conn:
            capture = conn.execute("SELECT * FROM extension_captures WHERE id = ?", (response["capture_id"],)).fetchone()
            source = conn.execute("SELECT * FROM sources WHERE id = ?", (response["source_id"],)).fetchone()
        self.assertEqual(capture["status"], "stored")
        self.assertEqual(source["source_type"], "extension_selection")

    def test_expert_retrain_queues_adapter_job_or_hardware_gate(self) -> None:
        from backend.app.api.routes.clusters import queue_expert_retrain
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (
                    id, vault_id, name, description, color, expert_status, created_at, updated_at
                )
                VALUES ('cluster-1', 'vault-1', 'Research', '', 'sage', 'setting-up', ?, ?)
                """,
                (now, now),
            )

        expert_job = queue_expert_retrain("cluster-1")

        with connect() as conn:
            adapter_job = conn.execute(
                "SELECT * FROM app_jobs WHERE job_type = 'train_cluster_adapter'"
            ).fetchone()
        if expert_job["failure_code"] == "hardware_unsupported":
            self.assertIsNone(adapter_job)
            self.assertEqual(expert_job["status"], "manual_review")
        else:
            self.assertIsNotNone(adapter_job)
            self.assertEqual(adapter_job["scope_id"], "cluster-1")

    def test_vault_lock_audit_records_events(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.vault_lock import acquire_vault_lock, release_vault_lock

        acquire_vault_lock()
        release_vault_lock()

        with connect() as conn:
            rows = conn.execute("SELECT event_type FROM vault_lock_audit ORDER BY created_at").fetchall()
        event_types = [row["event_type"] for row in rows]
        self.assertIn("acquired", event_types)
        self.assertIn("released", event_types)


if __name__ == "__main__":
    unittest.main()
