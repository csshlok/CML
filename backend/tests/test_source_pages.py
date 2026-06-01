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
        os.environ.pop("CML_ALLOW_LORA_TEST_TRAINER", None)
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

    def test_delete_source_tombstones_retrieval_items_before_page_chunk_cleanup(self) -> None:
        from backend.app.api.routes.sources import create_source, delete_source
        from backend.app.core.background_jobs import run_due_jobs_once
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
                title="Tombstone note",
                source_type="note",
                raw_text="retrieval tombstone chunk page cleanup " * 120,
            )
        )
        run_due_jobs_once(limit=1)
        with connect() as conn:
            page = conn.execute("SELECT id FROM source_pages WHERE source_id = ?", (source["id"],)).fetchone()
            chunk = conn.execute("SELECT id FROM source_chunks WHERE source_id = ?", (source["id"],)).fetchone()
            conn.execute(
                """
                INSERT INTO chat_sessions (
                    id, vault_id, title, scope_cluster_id, saved, memory_status,
                    memory_updated_at, created_at, updated_at
                )
                VALUES ('chat-1', 'vault-1', 'Chat', NULL, 0, 'idle', NULL, ?, ?)
                """,
                (now, now),
            )
            conn.execute(
                "INSERT INTO chat_messages (id, session_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                ("message-1", "chat-1", "assistant", "answer", now),
            )
            conn.execute(
                """
                INSERT INTO retrieval_snapshots (
                    id, message_id, session_id, vault_id, query, retrieval_mode,
                    embedding_model_id, token_budget, created_at
                )
                VALUES ('snapshot-1', 'message-1', 'chat-1', 'vault-1', 'query', 'semantic', 'hash-dev', NULL, ?)
                """,
                (now,),
            )
            conn.execute(
                """
                INSERT INTO retrieval_snapshot_items (
                    id, snapshot_id, source_id, chunk_id, page_id,
                    source_title_at_answer_time, page_number, snippet_hash,
                    short_snippet_excerpt, relevance_score, item_rank, state, created_at
                )
                VALUES (
                    'item-1', 'snapshot-1', ?, ?, ?, 'Tombstone note', 1,
                    'hash', 'excerpt', 1.0, 1, 'current', ?
                )
                """,
                (source["id"], chunk["id"], page["id"], now),
            )

        delete_source(source["id"])

        with connect() as conn:
            item = conn.execute("SELECT * FROM retrieval_snapshot_items LIMIT 1").fetchone()
            queued_cleanup = conn.execute(
                "SELECT * FROM app_jobs WHERE job_type = 'delete_source_cleanup' AND scope_id = ?",
                (source["id"],),
            ).fetchone()
        self.assertEqual(item["state"], "source_deleted")
        self.assertIsNone(item["source_id"])
        self.assertIsNone(item["chunk_id"])
        self.assertIsNone(item["page_id"])
        self.assertIsNotNone(queued_cleanup)

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

    def test_scanned_pdf_ocr_prefers_ocrmypdf_and_falls_back_to_tesseract_render(self) -> None:
        from unittest.mock import patch

        from backend.app.core.ocr import OCRError, ocr_pdf_pages, ocr_runtime_status

        pdf_path = Path(self.tmp.name) / "scan.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")
        tesseract_path = Path(self.tmp.name) / "tesseract.exe"

        with (
            patch("backend.app.core.ocr._require_tesseract", return_value=tesseract_path),
            patch(
                "backend.app.core.ocr._ocr_pdf_with_ocrmypdf",
                return_value=["page one from ocrmypdf"],
            ) as ocrmypdf,
            patch("backend.app.core.ocr._ocr_pdf_pages_with_tesseract_render") as fallback,
        ):
            self.assertEqual(ocr_pdf_pages(pdf_path), ["page one from ocrmypdf"])
            ocrmypdf.assert_called_once()
            fallback.assert_not_called()

        with (
            patch("backend.app.core.ocr._require_tesseract", return_value=tesseract_path),
            patch(
                "backend.app.core.ocr._ocr_pdf_with_ocrmypdf",
                side_effect=OCRError("missing qpdf"),
            ),
            patch(
                "backend.app.core.ocr._ocr_pdf_pages_with_tesseract_render",
                return_value=["page one from fallback"],
            ) as fallback,
        ):
            self.assertEqual(ocr_pdf_pages(pdf_path), ["page one from fallback"])
            fallback.assert_called_once()

        with patch("backend.app.core.ocr._tesseract_executable", return_value=None):
            status = ocr_runtime_status()
        self.assertFalse(status["available"])
        self.assertIn("tesseract", status["missing"])

    def test_dynamic_link_extraction_uses_browser_text_when_static_text_is_thin(self) -> None:
        from unittest.mock import patch

        from backend.app.core.extraction import extract_text_from_url

        class FakeHeaders(dict):
            def get(self, key, default=None):
                return super().get(key, default)

        class FakeResponse:
            headers = FakeHeaders({"content-type": "text/html"})

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return b"<html><head><title>Thin</title></head><body><div id='root'></div><script></script><script></script><script></script></body></html>"

            def geturl(self):
                return "https://example.com/app"

        with (
            patch("backend.app.core.extraction._safe_open", return_value=(FakeResponse(), "https://example.com/app")),
            patch("backend.app.core.extraction.validate_public_http_url"),
            patch(
                "backend.app.core.extraction._extract_dynamic_text_from_url",
                return_value=("Rendered", "Rendered application text " * 40, None),
            ) as dynamic,
        ):
            title, text, _cover = extract_text_from_url("https://example.com/app")

        self.assertEqual(title, "Rendered")
        self.assertIn("Rendered application text", text)
        dynamic.assert_called_once()

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
        with connect() as conn:
            job = conn.execute(
                "SELECT * FROM app_jobs WHERE job_type = 'expanded_analysis'"
            ).fetchone()
        self.assertIsNotNone(job)

    def test_expanded_analysis_job_writes_evidence_packets(self) -> None:
        from backend.app.api.routes.chat import build_chat_context
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ChatContextRequest, SourceCreate
        from backend.app.api.routes.sources import create_source

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )
        create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Evidence source",
                source_type="note",
                raw_text="expanded evidence packet context " * 100,
            )
        )
        run_due_jobs_once(limit=1)
        build_chat_context(
            ChatContextRequest(
                vault_id="vault-1",
                prompt="expanded evidence packet context",
                expanded_analysis=True,
            )
        )
        run_due_jobs_once(limit=2)

        with connect() as conn:
            packets = conn.execute("SELECT * FROM analysis_evidence_packets").fetchall()
        self.assertGreaterEqual(len(packets), 1)
        self.assertEqual(packets[0]["status"], "ready")

    def test_vault_safety_status_can_create_backup(self) -> None:
        from backend.app.core.vault_safety import vault_safety_status

        result = vault_safety_status(create_backup=True)

        self.assertTrue(result["integrity_ok"])
        self.assertTrue(result["backup_path"])
        self.assertTrue(Path(result["backup_path"]).exists())

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

    def test_bridge_requires_explicit_allowed_vault_when_vault_omitted(self) -> None:
        from fastapi import HTTPException

        from backend.app.api.routes.bridge import build_context, update_bridge_settings
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import BridgeContextRequest, BridgeSettingsUpdate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )

        status = update_bridge_settings(BridgeSettingsUpdate(enabled=True, rotate_token=True))

        with self.assertRaises(HTTPException) as raised:
            build_context(
                BridgeContextRequest(query="find context", client_name="test-client"),
                x_cml_bridge_token=status["bridge_token"],
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail, "no_active_vault")

    def test_bridge_token_rotation_history_is_recorded(self) -> None:
        from backend.app.api.routes.bridge import list_bridge_token_rotations, update_bridge_settings
        from backend.app.schemas import BridgeSettingsUpdate

        update_bridge_settings(BridgeSettingsUpdate(rotate_token=True))
        rotations = list_bridge_token_rotations()

        self.assertGreaterEqual(len(rotations), 1)
        self.assertEqual(rotations[0]["reason"], "manual_rotation")

    def test_delete_source_marks_existing_citation_snapshot_deleted(self) -> None:
        from backend.app.api.routes.chat import build_chat_context, get_chat_session
        from backend.app.api.routes.sources import create_source, delete_source
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ChatContextRequest, SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )

        source = create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Citation note",
                source_type="note",
                raw_text="citation deletion evidence " * 120,
            )
        )
        run_due_jobs_once(limit=1)
        response = build_chat_context(
            ChatContextRequest(vault_id="vault-1", prompt="What evidence mentions citation deletion?")
        )

        delete_source(source["id"])
        session = get_chat_session(response["session_id"])
        assistant = [message for message in session["messages"] if message["role"] == "assistant"][0]

        self.assertTrue(assistant["citations"])
        self.assertEqual(assistant["citations"][0]["state"], "source_deleted")

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

    def test_diagnostic_bundle_excludes_source_text_and_redacts_logs(self) -> None:
        from pathlib import Path
        from zipfile import ZipFile

        from backend.app.api.routes.diagnostics import create_diagnostic_bundle
        from backend.app.api.routes.sources import create_source
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceCreate

        now = utc_now()
        secret = "my_secret_password_12345"
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Test vault", str(self.db_path.parent), now, now),
            )
        create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Secret note",
                source_type="note",
                raw_text=f"diagnostic redaction {secret}",
            )
        )
        log_dir = Path(self.tmp.name) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "backend.log").write_text(
            f"authorization: Bearer abc.def\npassword={secret}\nC:\\Users\\alice\\vault\\file.txt",
            encoding="utf-8",
        )

        response = create_diagnostic_bundle()

        with ZipFile(response["bundle_path"]) as bundle:
            payload = "\n".join(bundle.read(name).decode("utf-8") for name in bundle.namelist())
        self.assertNotIn(secret, payload)
        self.assertNotIn("abc.def", payload)
        self.assertNotIn("alice", payload)
        self.assertIn("[redacted]", payload)

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
            user_version = conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(row["version"], 1)
        self.assertEqual(row["status"], "succeeded")
        self.assertEqual(user_version, 1)

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

    def test_embedding_download_reports_missing_runtime_without_network(self) -> None:
        import time
        from unittest.mock import patch

        from backend.app.core.embeddings import embedding_download_status, start_embedding_model_download

        with patch("importlib.util.find_spec", return_value=None):
            state = start_embedding_model_download(str(Path(self.tmp.name) / "embeddings"))
            self.assertIn(state["status"], {"queued", "downloading"})
            for _ in range(50):
                current = embedding_download_status()
                if current["status"] == "failed":
                    break
                time.sleep(0.01)

        self.assertEqual(embedding_download_status()["status"], "failed")
        self.assertIn("SentenceTransformers is not installed", embedding_download_status()["error"])

    def test_bridge_client_token_has_independent_permissions(self) -> None:
        from fastapi import HTTPException

        from backend.app.api.routes.bridge import (
            build_context,
            create_bridge_client,
            update_bridge_settings,
        )
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import BridgeClientCreate, BridgeContextRequest, BridgeSettingsUpdate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Allowed", str(self.db_path.parent), now, now),
            )
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-2", "Denied", str(self.db_path.parent), now, now),
            )

        update_bridge_settings(BridgeSettingsUpdate(enabled=True, allowed_vault_ids=["vault-2"]))
        client = create_bridge_client(
            BridgeClientCreate(name="Scoped client", allowed_vault_ids=["vault-1"])
        )

        response = build_context(
            BridgeContextRequest(query="anything", client_name="test-client"),
            x_cml_bridge_token=client["token"],
        )
        self.assertEqual(response["query"], "anything")

        with self.assertRaises(HTTPException) as raised:
            build_context(
                BridgeContextRequest(vault_id="vault-2", query="anything", client_name="test-client"),
                x_cml_bridge_token=client["token"],
            )
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.detail, "vault_not_allowed")

    def test_deleting_chat_session_removes_transcript_sources_and_chunks(self) -> None:
        from backend.app.api.routes.chat import build_chat_context, delete_chat_session
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
            conn.execute(
                """
                INSERT INTO clusters (
                    id, vault_id, name, description, color, expert_status, created_at, updated_at
                )
                VALUES ('cluster-1', 'vault-1', 'Research', '', 'sage', 'setting-up', ?, ?)
                """,
                (now, now),
            )
        create_source(
            SourceCreate(
                vault_id="vault-1",
                cluster_id="cluster-1",
                title="Original note",
                source_type="note",
                raw_text="transcript memory cleanup evidence " * 120,
            )
        )
        run_due_jobs_once(limit=1)
        response = build_chat_context(
            ChatContextRequest(
                vault_id="vault-1",
                cluster_id="cluster-1",
                prompt="What mentions transcript memory cleanup evidence?",
            )
        )
        run_due_jobs_once(limit=1)

        delete_chat_session(response["session_id"])

        with connect() as conn:
            transcript_sources = conn.execute(
                "SELECT COUNT(*) AS count FROM sources WHERE id LIKE ?",
                (f"chat-source-{response['session_id']}-%",),
            ).fetchone()["count"]
            transcript_chunks = conn.execute(
                "SELECT COUNT(*) AS count FROM source_chunks WHERE source_id LIKE ?",
                (f"chat-source-{response['session_id']}-%",),
            ).fetchone()["count"]
            messages = conn.execute(
                "SELECT COUNT(*) AS count FROM chat_messages WHERE session_id = ?",
                (response["session_id"],),
            ).fetchone()["count"]

        self.assertEqual(transcript_sources, 0)
        self.assertEqual(transcript_chunks, 0)
        self.assertEqual(messages, 0)

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
        from backend.app.api.routes.integrations import (
            list_integration_imports,
            refresh_integration_import,
            scan_local_folder_integration,
        )
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
        listed = list_integration_imports("vault-1")
        self.assertEqual(listed[0]["id"], result["import_id"])
        self.assertFalse(listed[0]["truncated"])
        (folder / "second.md").write_text("another synced note", encoding="utf-8")
        refreshed = refresh_integration_import(result["import_id"])
        self.assertEqual(refreshed["supported_count"], 2)

    def test_extension_capture_creates_source_and_capture_record(self) -> None:
        from backend.app.api.routes.extension import (
            capture_from_extension,
            create_extension_client,
            list_extension_captures,
            list_extension_clients,
            revoke_extension_client,
            update_extension_client,
        )
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ExtensionCaptureRequest, ExtensionClientCreate, ExtensionClientUpdate

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
        self.assertEqual(len(list_extension_clients()), 1)
        self.assertEqual(list_extension_captures("vault-1")[0]["id"], response["capture_id"])
        updated = update_extension_client(
            client["id"],
            ExtensionClientUpdate(allowed_vault_ids=["other-vault"]),
        )
        self.assertEqual(updated["allowed_vault_ids"], ["other-vault"])
        with self.assertRaises(Exception):
            capture_from_extension(
                ExtensionCaptureRequest(
                    vault_id="vault-1",
                    capture_type="selection",
                    title="Blocked thought",
                    text="blocked by extension permission",
                ),
                x_cml_extension_token=client["token"],
            )
        revoke_extension_client(client["id"])
        self.assertFalse(list_extension_clients()[0]["enabled"])

    def test_expert_retrain_queues_adapter_job_or_hardware_gate(self) -> None:
        from backend.app.api.routes.clusters import list_expert_artifacts, queue_expert_retrain
        from backend.app.core.background_jobs import run_due_jobs_once
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
            run_due_jobs_once(limit=1)
            artifacts = list_expert_artifacts("cluster-1")
            self.assertGreaterEqual(len(artifacts), 1)

    def test_verified_lora_training_creates_active_adapter_with_metrics(self) -> None:
        from unittest.mock import patch

        from backend.app.api.routes.clusters import (
            get_expert_graduation_contract,
            list_expert_artifacts,
            queue_expert_retrain,
        )
        from backend.app.api.routes.sources import create_source
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.config import get_settings
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceCreate

        os.environ["CML_ALLOW_LORA_TEST_TRAINER"] = "1"
        get_settings.cache_clear()
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
                VALUES ('cluster-1', 'vault-1', 'Research', '', 'sage', 'retrieval_ready', ?, ?)
                """,
                (now, now),
            )
        create_source(
            SourceCreate(
                vault_id="vault-1",
                cluster_id="cluster-1",
                title="LoRA source",
                source_type="note",
                raw_text="verified lora adapter training evidence " * 320,
                summary="A sufficiently descriptive local source summary for adapter training.",
            )
        )

        hardware = {
            "training_supported": True,
            "hardware_tier": "cpu_minimum_spec",
            "detail": "test hardware",
        }
        with (
            patch("backend.app.core.expert_lifecycle.hardware_status", return_value=hardware),
            patch("backend.app.core.hardware.hardware_status", return_value=hardware),
        ):
            contract = get_expert_graduation_contract("cluster-1")
            expert_job = queue_expert_retrain("cluster-1")
            processed = run_due_jobs_once(limit=2)

        self.assertIn("training_ready", contract["supported_statuses"])
        self.assertEqual(expert_job["status"], "queued")
        self.assertGreaterEqual(processed, 1)
        artifacts = list_expert_artifacts("cluster-1")
        self.assertEqual(len(artifacts), 1)
        artifact = artifacts[0]
        self.assertEqual(artifact["artifact_type"], "lora_adapter")
        self.assertEqual(artifact["status"], "ready")
        self.assertTrue(artifact["active"])
        self.assertTrue(artifact["dataset_hash"])
        self.assertTrue(artifact["training_config_hash"])
        self.assertGreaterEqual(artifact["quality_score"], 60)
        self.assertTrue((Path(artifact["local_path"]) / "adapter_config.json").exists())
        self.assertTrue((Path(artifact["local_path"]) / "adapter_model.safetensors").exists())
        with connect() as conn:
            cluster = conn.execute("SELECT expert_status FROM clusters WHERE id = 'cluster-1'").fetchone()
            job = conn.execute("SELECT status, failure_code, detail FROM cluster_expert_jobs WHERE id = ?", (expert_job["id"],)).fetchone()
        self.assertEqual(cluster["expert_status"], "training_ready")
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["failure_code"], "")

    def test_lora_adapter_rollback_and_delete_guardrails(self) -> None:
        from backend.app.api.routes.clusters import (
            activate_expert_artifact,
            delete_expert_artifact,
            rollback_expert_artifact,
        )
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        adapter_a = Path(self.tmp.name) / "adapter-a"
        adapter_b = Path(self.tmp.name) / "adapter-b"
        for path in (adapter_a, adapter_b):
            path.mkdir()
            (path / "adapter_config.json").write_text("{}", encoding="utf-8")
            (path / "adapter_model.safetensors").write_bytes(b"adapter")
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
                VALUES ('cluster-1', 'vault-1', 'Research', '', 'sage', 'training_ready', ?, ?)
                """,
                (now, now),
            )
            for artifact_id, path, active in (("artifact-a", adapter_a, 0), ("artifact-b", adapter_b, 1)):
                conn.execute(
                    """
                    INSERT INTO expert_artifacts (
                        id, cluster_id, vault_id, artifact_type, status, local_path,
                        base_model, hardware_tier, quality_score, active,
                        created_at, updated_at
                    )
                    VALUES (?, 'cluster-1', 'vault-1', 'lora_adapter', 'ready', ?, 'base', 'cpu', 80, ?, ?, ?)
                    """,
                    (artifact_id, str(path), active, now, now),
                )

        with self.assertRaises(Exception):
            delete_expert_artifact("cluster-1", "artifact-b")
        rolled_back = rollback_expert_artifact("cluster-1")
        self.assertEqual(rolled_back["id"], "artifact-a")
        self.assertTrue(rolled_back["active"])
        deleted = activate_expert_artifact("cluster-1", "artifact-b")
        self.assertTrue(deleted["active"])
        delete_expert_artifact("cluster-1", "artifact-a")
        with connect() as conn:
            artifact_a = conn.execute("SELECT deleted_at FROM expert_artifacts WHERE id = 'artifact-a'").fetchone()
        self.assertIsNotNone(artifact_a["deleted_at"])

    def test_vault_lock_audit_records_events(self) -> None:
        from backend.app.api.routes.system import list_vault_lock_audit
        from backend.app.core.database import connect
        from backend.app.core.vault_lock import acquire_vault_lock, release_vault_lock

        acquire_vault_lock()
        release_vault_lock()

        with connect() as conn:
            rows = conn.execute("SELECT event_type FROM vault_lock_audit ORDER BY created_at").fetchall()
        event_types = [row["event_type"] for row in rows]
        self.assertIn("acquired", event_types)
        self.assertIn("released", event_types)
        self.assertGreaterEqual(len(list_vault_lock_audit()), 2)

    def test_cancellable_job_can_be_cancelled(self) -> None:
        from backend.app.api.routes.jobs import cancel_app_job
        from backend.app.core.background_jobs import enqueue_job
        from backend.app.core.database import connect

        with connect() as conn:
            job = enqueue_job(
                conn,
                job_type="reindex_source",
                payload={"source_id": "source-1"},
                dedupe_key="cancel-test",
                scope_id="source-1",
                user_initiated=True,
            )

        cancelled = cancel_app_job(job["id"])

        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["status_detail"], "Cancelled by user.")


if __name__ == "__main__":
    unittest.main()
