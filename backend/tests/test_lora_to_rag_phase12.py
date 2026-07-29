import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


class LoraToRagPhase12Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["CML_DATABASE_PATH"] = str(Path(self.tmp.name) / "test.sqlite3")
        os.environ["CML_DATA_DIR"] = self.tmp.name
        os.environ["CML_MODELS_DIR"] = str(Path(self.tmp.name) / "models")
        os.environ["CML_ALLOW_UNAUTHENTICATED_API"] = "1"
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"
        from backend.app.core.config import get_settings
        from backend.app.core.database import init_db

        get_settings.cache_clear()
        init_db()

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.model_recommender.benchmark_store import invalidate_internal_benchmark_bundle_cache

        invalidate_internal_benchmark_bundle_cache()
        get_settings.cache_clear()
        for key in [
            "CML_DATABASE_PATH",
            "CML_DATA_DIR",
            "CML_MODELS_DIR",
            "CML_ALLOW_UNAUTHENTICATED_API",
            "CML_EMBEDDING_PROVIDER",
            "CML_ALLOW_HASH_EMBEDDINGS",
            "CML_MODEL_SCAN_ROOTS",
            "CML_MODEL_RECOMMENDER_BENCHMARK_BUNDLE",
        ]:
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def _write_fake_local_transformers_model(self, model_name: str, *, model_type: str, repo_hint: str) -> Path:
        model_root = Path(self.tmp.name) / "transformers-models"
        model_dir = model_root / model_name
        model_dir.mkdir(parents=True, exist_ok=True)
        (model_dir / "config.json").write_text(
            json.dumps({"model_type": model_type, "_name_or_path": repo_hint}),
            encoding="utf-8",
        )
        (model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
        return model_dir

    def _write_fake_gguf(self, file_name: str) -> Path:
        model_root = Path(self.tmp.name) / "gguf-models"
        model_root.mkdir(parents=True, exist_ok=True)
        model_path = model_root / file_name
        model_path.write_bytes(b"GGUF fixture")
        return model_path

    def test_first_run_readiness_is_chat_only(self) -> None:
        from backend.app.core.setup_readiness import first_run_readiness

        with patch(
            "backend.app.core.setup_readiness.embedding_status",
            return_value={"available": True, "provider": "sentence-transformers", "detail": "Configured."},
        ), patch(
            "backend.app.core.setup_readiness.ocr_runtime_status",
            return_value={"image_ocr_available": True, "pdf_ocr_available": True, "detail": "Configured."},
        ), patch(
            "backend.app.core.setup_readiness.model_integrity_manifest_status",
            return_value={"available": True, "model_count": 1},
        ), patch(
            "backend.app.core.setup_readiness.list_models",
            return_value=[{"id": "qwen3-4b-q4_k_m", "installed": True}],
        ), patch(
            "backend.app.core.setup_readiness.discover_installed_models",
            return_value={"compatible_model_count": 0},
        ), patch(
            "backend.app.core.setup_readiness.active_chat_model_status",
            return_value={"id": "qwen3-4b-q4_k_m", "compatibility": {"chat_role_accepted": True, "detail": "Accepted."}},
        ), patch(
            "backend.app.core.setup_readiness.runtime_status",
            return_value={"state": "ready", "model": "qwen3-4b-q4_k_m", "detail": "Ready."},
        ), patch(
            "backend.app.core.setup_readiness.model_recommendations",
            return_value={"recommended_chat_model_id": "qwen3-4b-q4_k_m", "detail": "Use the default chat model."},
        ), patch(
            "backend.app.core.setup_readiness.validate_startup_phase_registry",
            return_value={"ok": True},
        ):
            readiness = first_run_readiness()

        self.assertTrue(readiness["ready"])
        self.assertEqual(readiness["status"], "ready")
        self.assertEqual(readiness["recommended_setup"]["recommended_chat_model_id"], "qwen3-4b-q4_k_m")
        check_ids = {check["id"] for check in readiness["checks"]}
        self.assertNotIn("expert_model", check_ids)
        self.assertNotIn("approved_model_pair", check_ids)

    def test_import_model_checkpoint_does_not_auto_activate_chat_role(self) -> None:
        from backend.app.core.model_registry import active_chat_model_status, import_model_checkpoint

        imported = import_model_checkpoint(
            self._write_fake_gguf("custom-qwen-q4_k_m.gguf"),
            name="Custom Qwen",
        )

        self.assertEqual(imported["source_kind"], "custom_import")
        self.assertIsNone(active_chat_model_status())

    def test_importing_same_checkpoint_under_another_name_reuses_managed_copy(self) -> None:
        from backend.app.core.model_registry import import_model_checkpoint, imported_model_statuses

        source = self._write_fake_gguf("same-qwen-q4_k_m.gguf")
        first = import_model_checkpoint(source, name="Qwen first")
        second = import_model_checkpoint(source, name="Qwen second")

        self.assertEqual(second["id"], first["id"])
        self.assertEqual(len(imported_model_statuses()), 1)
        imported_dirs = [
            item
            for item in (Path(self.tmp.name) / "models" / "imported").iterdir()
            if item.is_dir() and not item.name.startswith(".")
        ]
        self.assertEqual(len(imported_dirs), 1)

    def test_importing_identical_checkpoint_copy_reuses_content_match(self) -> None:
        from backend.app.core.model_registry import import_model_checkpoint, imported_model_statuses

        first_source = self._write_fake_gguf("first-qwen-q4_k_m.gguf")
        second_source = self._write_fake_gguf("second-qwen-q4_k_m.gguf")
        first = import_model_checkpoint(first_source, name="First Qwen")
        second = import_model_checkpoint(second_source, name="Second Qwen")

        self.assertEqual(second["id"], first["id"])
        self.assertEqual(len(imported_model_statuses()), 1)

    def test_changed_checkpoint_at_same_path_creates_a_distinct_import(self) -> None:
        from backend.app.core.model_registry import import_model_checkpoint, imported_model_statuses

        source = self._write_fake_gguf("changed-qwen-q4_k_m.gguf")
        first = import_model_checkpoint(source, name="Original Qwen")
        source.write_bytes(b"GGUF changed")
        stat = source.stat()
        os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
        second = import_model_checkpoint(source, name="Updated Qwen")

        self.assertNotEqual(second["id"], first["id"])
        self.assertEqual(len(imported_model_statuses()), 2)

    def test_discovery_marks_original_checkpoint_as_already_imported(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.model_registry import discover_installed_models, import_model_checkpoint

        source = self._write_fake_gguf("discovered-qwen-q4_k_m.gguf")
        import_model_checkpoint(source, name="Discovered Qwen")
        os.environ["CML_MODEL_SCAN_ROOTS"] = str(source.parent)
        get_settings.cache_clear()

        discovery = discover_installed_models(max_results=10, refresh=True)
        discovered = next(
            row
            for row in discovery["models"]
            if Path(row["local_path"]).resolve() == source.resolve()
        )

        self.assertTrue(discovered["already_imported"])

    def test_legacy_duplicate_imports_render_as_one_active_model(self) -> None:
        from backend.app.core.model_registry import imported_model_statuses, registry_state_path

        source = self._write_fake_gguf("legacy-qwen-q4_k_m.gguf")
        imported_root = Path(self.tmp.name) / "models" / "imported"
        first_local_path: Path | None = None
        for model_id, folder_name in (
            ("custom-qwen-one", "qwen-one"),
            ("custom-qwen-two", "qwen-two"),
        ):
            folder = imported_root / folder_name
            folder.mkdir(parents=True)
            local_path = folder / source.name
            local_path.write_bytes(source.read_bytes())
            (folder / "cml-model.json").write_text(
                json.dumps(
                    {
                        "id": model_id,
                        "name": model_id,
                        "family": "qwen",
                        "local_path": str(local_path),
                        "source_path": str(first_local_path or source),
                    }
                ),
                encoding="utf-8",
            )
            first_local_path = first_local_path or local_path
        registry_state_path().write_text(
            json.dumps({"active_chat_model_id": "custom-qwen-two"}),
            encoding="utf-8",
        )

        rows = imported_model_statuses()

        self.assertEqual([row["id"] for row in rows], ["custom-qwen-two"])
        self.assertTrue(rows[0]["active_chat"])

    def test_active_chat_setup_status_accepts_single_chat_model_in_rag_only_mode(self) -> None:
        from backend.app.core.model_registry import active_chat_setup_status, set_active_model

        managed_dir = Path(self.tmp.name) / "models" / "qwen3-4b-q4_k_m"
        managed_dir.mkdir(parents=True, exist_ok=True)
        (managed_dir / "qwen3-4b-q4_k_m.gguf").write_bytes(b"gguf")

        set_active_model("qwen3-4b-q4_k_m", role="chat")
        status = active_chat_setup_status()

        self.assertTrue(status["accepted"])
        self.assertEqual(status["chat_model_id"], "qwen3-4b-q4_k_m")
        self.assertIn("RAG-only mode", status["detail"])

    def test_registry_state_no_longer_persists_active_expert_model_id(self) -> None:
        from backend.app.core.model_registry import registry_state, registry_state_path

        registry_state_path().write_text(json.dumps({"active_model_id": "legacy-chat"}), encoding="utf-8")
        state = registry_state()

        self.assertEqual(state["active_chat_model_id"], "legacy-chat")
        self.assertNotIn("active_expert_model_id", state)

    def test_cluster_create_paths_write_rag_lifecycle_defaults(self) -> None:
        from backend.app.api.routes.clusters import create_cluster
        from backend.app.core.chat_memory import _ensure_chats_cluster
        from backend.app.core.database import connect, utc_now
        from backend.app.core.clustering import assign_or_create_cluster
        from backend.app.schemas import ClusterCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )

        created = create_cluster(
            ClusterCreate(vault_id="vault-1", name="Manual", description="Manual cluster", color="sage")
        )
        with connect() as conn:
            auto_cluster_id = assign_or_create_cluster(conn, vault_id="vault-1", title="Quarterly Plan", text="Roadmap and milestones")
            chats = _ensure_chats_cluster(conn, "vault-1")
            rows = conn.execute(
                """
                SELECT
                    id,
                    index_status,
                    profile_status,
                    cluster_summary,
                    cluster_glossary,
                    profile_updated_at,
                    profile_source_hash,
                    indexed_source_count
                FROM clusters
                WHERE id IN (?, ?)
                """,
                (created["id"], chats["id"]),
            ).fetchall()

        self.assertIsNone(auto_cluster_id)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row["index_status"], "empty")
            self.assertEqual(row["profile_status"], "missing")
            self.assertEqual(row["cluster_summary"], "")
            self.assertEqual(row["cluster_glossary"], "[]")
            self.assertIsNone(row["profile_updated_at"])
            self.assertEqual(row["profile_source_hash"], "")
            self.assertEqual(row["indexed_source_count"], 0)

    def test_mark_cluster_needs_update_sets_rag_lifecycle_from_source_state(self) -> None:
        from backend.app.core.database import connect, utc_now
        from backend.app.core.cluster_lifecycle import mark_cluster_needs_update

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (
                    id, vault_id, name, description, color, index_status, profile_status,
                    cluster_summary, cluster_glossary, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "cluster-1",
                    "vault-1",
                    "Cluster",
                    "",
                    "sage",
                    "empty",
                    "missing",
                    "",
                    "[]",
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO sources (
                    id, vault_id, cluster_id, title, source_type, state, provenance, trust_tier,
                    security_labels, parser_security_json, raw_text, extracted_text, summary, tags,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "source-1",
                    "vault-1",
                    "cluster-1",
                    "Doc",
                    "text",
                    "indexed",
                    "local_import",
                    "trusted_local",
                    "[]",
                    "{}",
                    "Body",
                    "Body",
                    "",
                    "[]",
                    now,
                    now,
                ),
            )

            mark_cluster_needs_update(conn, "cluster-1", "Source changed.")
            row = conn.execute(
                "SELECT index_status, profile_status FROM clusters WHERE id = ?",
                ("cluster-1",),
            ).fetchone()

        self.assertEqual(row["index_status"], "ready")
        self.assertEqual(row["profile_status"], "stale")

    def test_cluster_profile_refresh_job_populates_cached_summary_and_glossary(self) -> None:
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect, utc_now
        from backend.app.core.cluster_lifecycle import mark_cluster_needs_update

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (
                    id, vault_id, name, description, color, index_status, profile_status,
                    cluster_summary, cluster_glossary, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "cluster-1",
                    "vault-1",
                    "Planning",
                    "Internal planning knowledge.",
                    "sage",
                    "empty",
                    "missing",
                    "",
                    "[]",
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO sources (
                    id, vault_id, cluster_id, title, source_type, state, provenance, trust_tier,
                    security_labels, parser_security_json, raw_text, extracted_text, summary, tags,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "source-1",
                    "vault-1",
                    "cluster-1",
                    "Quarterly Roadmap",
                    "text",
                    "indexed",
                    "local_import",
                    "trusted_local",
                    "[]",
                    "{}",
                    "Roadmap milestones and launch dates.",
                    "Roadmap milestones and launch dates.",
                    "Roadmap milestones and launch dates.",
                    "[]",
                    now,
                    now,
                ),
            )
            mark_cluster_needs_update(conn, "cluster-1", "Source changed.")

        processed = run_due_jobs_once(limit=5)

        with connect() as conn:
            row = conn.execute(
                """
                SELECT
                    profile_status,
                    cluster_summary,
                    cluster_glossary,
                    profile_updated_at,
                    profile_source_hash,
                    indexed_source_count
                FROM clusters
                WHERE id = ?
                """,
                ("cluster-1",),
            ).fetchone()
            job = conn.execute(
                "SELECT status FROM app_jobs WHERE dedupe_key = ?",
                ("refresh-cluster-profile:cluster-1",),
            ).fetchone()

        self.assertGreaterEqual(processed, 1)
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(row["profile_status"], "ready")
        self.assertIn("Quarterly Roadmap", row["cluster_summary"])
        self.assertIn("Roadmap", row["cluster_glossary"])
        self.assertIsNotNone(row["profile_updated_at"])
        self.assertTrue(row["profile_source_hash"])
        self.assertEqual(row["indexed_source_count"], 1)

    def test_cluster_profile_refresh_reads_secured_source_content(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.core import vault_crypto
        from backend.app.core.cluster_lifecycle import mark_cluster_needs_update, refresh_cluster_profile
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-secured", "Secured", self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (
                    id, vault_id, name, description, color, index_status, profile_status,
                    cluster_summary, cluster_glossary, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "cluster-secured",
                    "vault-secured",
                    "Secure cluster",
                    "Protected notes.",
                    "sage",
                    "empty",
                    "missing",
                    "",
                    "[]",
                    now,
                    now,
                ),
            )
        vault_crypto.initialize_vault_security(
            "vault-secured",
            "phase12-secure-passphrase",
            kdf_params=vault_crypto.TEST_KDF_PARAMS,
        )
        create_source(
            SourceCreate(
                vault_id="vault-secured",
                cluster_id="cluster-secured",
                title="Protected note",
                source_type="note",
                raw_text="NebulaSequence secure concept appears only inside encrypted content.",
                summary="",
            )
        )
        with connect() as conn:
            mark_cluster_needs_update(conn, "cluster-secured", "Source changed.")
            result = refresh_cluster_profile(conn, "cluster-secured")

        with connect() as conn:
            row = conn.execute(
                "SELECT cluster_glossary, cluster_summary, profile_status FROM clusters WHERE id = ?",
                ("cluster-secured",),
            ).fetchone()

        self.assertEqual(result["profile_status"], "ready")
        self.assertEqual(row["profile_status"], "ready")
        self.assertIn("NebulaSequence", row["cluster_glossary"])
        self.assertIn("Protected note", row["cluster_summary"])

    def test_source_patch_accepts_legacy_extracting_alias_and_queues_reindex(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceCreate
        from backend.app.main import app

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )

        source = create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Needs reindex",
                source_type="note",
                raw_text="Reindex me.",
            )
        )

        client = TestClient(app)
        try:
            response = client.patch(f"/api/v1/sources/{source['id']}", json={"state": "extracting"})
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "processing")
        with connect() as conn:
            job = conn.execute(
                "SELECT job_type, status FROM app_jobs WHERE dedupe_key = ? ORDER BY created_at DESC LIMIT 1",
                (f"reindex-source:{source['id']}",),
            ).fetchone()
        self.assertIsNotNone(job)
        self.assertEqual(job["job_type"], "reindex_source")
        self.assertEqual(job["status"], "queued")

    def test_sources_list_omits_heavy_content_by_default_but_detail_route_keeps_it(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceCreate
        from backend.app.main import app

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )

        source = create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Verbose note",
                source_type="note",
                raw_text="Important detail " * 40,
            )
        )

        client = TestClient(app)
        try:
            list_response = client.get("/api/v1/sources", params={"vault_id": "vault-1"})
            detail_response = client.get(f"/api/v1/sources/{source['id']}")
        finally:
            client.close()

        self.assertEqual(list_response.status_code, 200)
        listed = list_response.json()[0]
        self.assertEqual(listed["raw_text"], "")
        self.assertEqual(listed["extracted_text"], "")
        self.assertTrue(listed["summary"])
        self.assertEqual(detail_response.status_code, 200)
        self.assertTrue(detail_response.json()["raw_text"].startswith("Important detail"))

    def test_storage_accounting_drops_expert_artifact_category(self) -> None:
        from backend.app.core.database import connect, utc_now
        from backend.app.core.storage_accounting import storage_accounting

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (
                    id, vault_id, name, description, color, index_status, profile_status,
                    cluster_summary, cluster_glossary, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "cluster-1",
                    "vault-1",
                    "Cluster",
                    "",
                    "sage",
                    "ready",
                    "ready",
                    "",
                    "[]",
                    now,
                    now,
                ),
            )

        accounting = storage_accounting("vault-1")
        self.assertNotIn("expert_artifacts", accounting)

    def test_installed_model_scan_roots_uses_explicit_roots_without_expert_runtime_dependency(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.model_registry import discover_installed_models, installed_model_scan_roots

        model_file = self._write_fake_gguf("detected-qwen-q4_k_m.gguf")
        os.environ["CML_MODEL_SCAN_ROOTS"] = str(model_file.parent)
        get_settings.cache_clear()

        roots = installed_model_scan_roots()
        discovery = discover_installed_models(max_results=10, refresh=True)

        self.assertIn(
            model_file.parent.resolve(),
            {path.resolve() for path in roots},
        )
        self.assertGreaterEqual(discovery["compatible_model_count"], 1)
        self.assertTrue(any(item["local_path"] == str(model_file.resolve()) for item in discovery["models"]))

    def test_approved_model_scan_root_is_persisted_and_discovered(self) -> None:
        from backend.app.core.model_registry import (
            approve_model_scan_root,
            discover_installed_models,
            installed_model_scan_roots,
            registry_state,
        )

        model_file = self._write_fake_gguf("approved-qwen-q4_k_m.gguf")
        approval = approve_model_scan_root(model_file.parent)
        roots = installed_model_scan_roots()
        discovery = discover_installed_models(max_results=10, refresh=True)

        self.assertTrue(approval["approved"])
        self.assertIn(str(model_file.parent.resolve()), registry_state()["approved_scan_roots"])
        self.assertIn(
            model_file.parent.resolve(),
            {path.resolve() for path in roots},
        )
        self.assertTrue(any(item["local_path"] == str(model_file.resolve()) for item in discovery["models"]))

    def test_default_model_scan_does_not_include_drive_roots(self) -> None:
        from backend.app.core.model_registry import installed_model_scan_roots

        roots = installed_model_scan_roots()

        self.assertFalse(any(path.parent == path for path in roots))

    def test_model_import_job_copies_checkpoint_and_records_result(self) -> None:
        from backend.app.core.background_jobs import enqueue_job, run_due_jobs_once
        from backend.app.core.database import connect

        model_file = self._write_fake_gguf("job-qwen-q4_k_m.gguf")
        with connect() as conn:
            job = enqueue_job(
                conn,
                job_type="model_import",
                payload={"path": str(model_file), "name": "Job Qwen"},
                dedupe_key="model-import:test",
                scope_id="test-model",
                user_initiated=True,
            )

        self.assertEqual(run_due_jobs_once(limit=1), 1)
        with connect() as conn:
            completed = conn.execute(
                "SELECT status, status_detail FROM app_jobs WHERE id = ?",
                (job["id"],),
            ).fetchone()

        detail = json.loads(completed["status_detail"])
        self.assertEqual(completed["status"], "succeeded")
        self.assertEqual(detail["phase"], "complete")
        self.assertEqual(detail["progress_percent"], 100.0)
        self.assertTrue(Path(detail["local_path"]).is_file())

    def test_legacy_train_cluster_adapter_jobs_fall_back_to_unsupported_job_handling(self) -> None:
        from backend.app.core.background_jobs import enqueue_job, run_due_jobs_once
        from backend.app.core.database import connect

        with connect() as conn:
            job = enqueue_job(
                conn,
                job_type="train_cluster_adapter",
                payload={"cluster_id": "cluster-1", "vault_id": "vault-1"},
            )

        processed = run_due_jobs_once(limit=1)

        with connect() as conn:
            row = conn.execute("SELECT status, last_error FROM app_jobs WHERE id = ?", (job["id"],)).fetchone()

        self.assertEqual(processed, 1)
        self.assertEqual(row["status"], "manual_review")
        self.assertIn("Unsupported job type", row["last_error"])
        self.assertIn("train_cluster_adapter", row["last_error"])

    def test_init_db_rebuilds_legacy_cluster_and_bridge_schema(self) -> None:
        from backend.app.core.config import get_settings
        from backend.app.core.database import connect, init_db

        get_settings.cache_clear()
        db_path = Path(self.tmp.name) / "test.sqlite3"
        if db_path.exists():
            db_path.unlink()
        legacy = sqlite3.connect(db_path)
        try:
            legacy.executescript(
                """
                PRAGMA foreign_keys = OFF;
                CREATE TABLE vaults (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE clusters (
                    id TEXT PRIMARY KEY,
                    vault_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    color TEXT NOT NULL DEFAULT 'sage',
                    expert_status TEXT NOT NULL DEFAULT 'setting-up',
                    index_status TEXT NOT NULL DEFAULT 'empty',
                    profile_status TEXT NOT NULL DEFAULT 'missing',
                    cluster_summary TEXT NOT NULL DEFAULT '',
                    cluster_glossary TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE bridge_settings (
                    id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    allowed_vault_ids TEXT NOT NULL DEFAULT '[]',
                    allowed_cluster_ids TEXT NOT NULL DEFAULT '[]',
                    allow_raw_snippets INTEGER NOT NULL DEFAULT 0,
                    allow_style_profile INTEGER NOT NULL DEFAULT 0,
                    allow_expert_calls INTEGER NOT NULL DEFAULT 0,
                    bridge_token TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE bridge_clients (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    token_hash TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    approval_vault_id TEXT,
                    allowed_vault_ids TEXT NOT NULL DEFAULT '[]',
                    allowed_cluster_ids TEXT NOT NULL DEFAULT '[]',
                    allow_raw_snippets INTEGER NOT NULL DEFAULT 0,
                    allow_style_profile INTEGER NOT NULL DEFAULT 0,
                    allow_expert_calls INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    approval_request_id TEXT,
                    approved_at TEXT,
                    revoked_at TEXT,
                    last_request_at TEXT,
                    request_count_total INTEGER NOT NULL DEFAULT 0,
                    response_bytes_total INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE cluster_expert_jobs (
                    id TEXT PRIMARY KEY,
                    cluster_id TEXT NOT NULL,
                    vault_id TEXT NOT NULL,
                    status TEXT NOT NULL
                );
                CREATE TABLE expert_artifacts (
                    id TEXT PRIMARY KEY,
                    cluster_id TEXT NOT NULL,
                    vault_id TEXT NOT NULL,
                    status TEXT NOT NULL
                );
                CREATE TABLE sources (
                    id TEXT PRIMARY KEY,
                    vault_id TEXT NOT NULL,
                    cluster_id TEXT,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'waiting',
                    original_path TEXT,
                    url TEXT,
                    checksum TEXT,
                    provenance TEXT NOT NULL DEFAULT 'local_import',
                    trust_tier TEXT NOT NULL DEFAULT 'trusted_local',
                    security_labels TEXT NOT NULL DEFAULT '[]',
                    parser_security_json TEXT NOT NULL DEFAULT '{}',
                    raw_text TEXT NOT NULL DEFAULT '',
                    extracted_text TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '[]',
                    cover_image_url TEXT,
                    deleted_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE,
                    FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE SET NULL
                );
                CREATE TABLE bridge_requests (
                    id TEXT PRIMARY KEY,
                    client_id TEXT,
                    client_name TEXT NOT NULL DEFAULT 'unknown',
                    query TEXT NOT NULL,
                    mode TEXT NOT NULL DEFAULT 'context',
                    decision TEXT NOT NULL DEFAULT 'allowed',
                    source_count INTEGER NOT NULL DEFAULT 0,
                    response_bytes INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (client_id) REFERENCES bridge_clients(id) ON DELETE SET NULL
                );
                """
            )
            legacy.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
            )
            legacy.execute(
                """
                INSERT INTO clusters (
                    id, vault_id, name, description, color, expert_status, index_status, profile_status,
                    cluster_summary, cluster_glossary, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "cluster-1",
                    "vault-1",
                    "Legacy cluster",
                    "Legacy description",
                    "sage",
                    "expert_compression_ready",
                    "ready",
                    "stale",
                    "",
                    "[]",
                    "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:00+00:00",
                ),
            )
            legacy.execute(
                """
                INSERT INTO bridge_settings (
                    id, enabled, allowed_vault_ids, allowed_cluster_ids, allow_raw_snippets,
                    allow_style_profile, allow_expert_calls, bridge_token, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "bridge-settings",
                    1,
                    '["vault-1"]',
                    '["cluster-1"]',
                    1,
                    1,
                    1,
                    "token",
                    "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:00+00:00",
                ),
            )
            legacy.execute(
                """
                INSERT INTO bridge_clients (
                    id, name, token_hash, enabled, approval_vault_id, allowed_vault_ids, allowed_cluster_ids,
                    allow_raw_snippets, allow_style_profile, allow_expert_calls, metadata_json,
                    approval_request_id, approved_at, revoked_at, last_request_at,
                    request_count_total, response_bytes_total, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "bridge-client-1",
                    "Legacy client",
                    "hash",
                    1,
                    "vault-1",
                    '["vault-1"]',
                    '["cluster-1"]',
                    1,
                    1,
                    1,
                    "{}",
                    None,
                    None,
                    None,
                    None,
                    0,
                    0,
                    "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:00+00:00",
                ),
            )
            legacy.execute(
                """
                INSERT INTO sources (
                    id, vault_id, cluster_id, title, source_type, state, provenance, trust_tier,
                    security_labels, parser_security_json, raw_text, extracted_text, summary, tags,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "source-1",
                    "vault-1",
                    "cluster-1",
                    "Legacy roadmap",
                    "text",
                    "indexed",
                    "local_import",
                    "trusted_local",
                    "[]",
                    "{}",
                    "Legacy roadmap body",
                    "Legacy roadmap body",
                    "Legacy roadmap body",
                    "[]",
                    "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:00+00:00",
                ),
            )
            legacy.commit()
        finally:
            legacy.close()

        init_db()

        with connect() as conn:
            cluster_columns = {
                item["name"]
                for item in conn.execute("PRAGMA table_info(clusters)").fetchall()
            }
            bridge_settings_columns = {
                item["name"]
                for item in conn.execute("PRAGMA table_info(bridge_settings)").fetchall()
            }
            bridge_clients_columns = {
                item["name"]
                for item in conn.execute("PRAGMA table_info(bridge_clients)").fetchall()
            }
            source_foreign_keys = conn.execute("PRAGMA foreign_key_list(sources)").fetchall()
            bridge_request_foreign_keys = conn.execute("PRAGMA foreign_key_list(bridge_requests)").fetchall()
            expert_jobs = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'cluster_expert_jobs'"
            ).fetchone()
            expert_artifacts = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'expert_artifacts'"
            ).fetchone()
            cluster = conn.execute(
                """
                SELECT
                    index_status,
                    profile_status,
                    indexed_source_count,
                    profile_source_hash
                FROM clusters
                WHERE id = ?
                """,
                ("cluster-1",),
            ).fetchone()

        self.assertNotIn("expert_status", cluster_columns)
        self.assertIn("profile_updated_at", cluster_columns)
        self.assertIn("profile_source_hash", cluster_columns)
        self.assertIn("indexed_source_count", cluster_columns)
        self.assertNotIn("allow_expert_calls", bridge_settings_columns)
        self.assertNotIn("allow_expert_calls", bridge_clients_columns)
        self.assertIn("clusters", {row["table"] for row in source_foreign_keys})
        self.assertIn("bridge_clients", {row["table"] for row in bridge_request_foreign_keys})
        self.assertIsNone(expert_jobs)
        self.assertIsNone(expert_artifacts)
        self.assertEqual(cluster["index_status"], "ready")
        self.assertEqual(cluster["profile_status"], "missing")
        self.assertEqual(cluster["indexed_source_count"], 1)
        self.assertEqual(cluster["profile_source_hash"], "")

    def test_removed_expert_and_lora_routes_return_not_found(self) -> None:
        import backend.app.main as main_module

        client = TestClient(main_module.app)
        try:
            responses = [
                client.get("/api/v1/system/lora-trainer"),
                client.get("/api/v1/clusters/cluster-1/expert/status"),
                client.get("/api/v1/clusters/cluster-1/expert/jobs"),
                client.post("/api/v1/clusters/cluster-1/expert/retrain"),
            ]
        finally:
            client.close()

        for response in responses:
            self.assertEqual(response.status_code, 404)

    def test_refresh_profile_route_marks_cluster_refreshing_and_enqueues_job(self) -> None:
        import backend.app.main as main_module
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (
                    id, vault_id, name, description, color, index_status, profile_status,
                    cluster_summary, cluster_glossary, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "cluster-1",
                    "vault-1",
                    "Cluster",
                    "",
                    "sage",
                    "ready",
                    "stale",
                    "",
                    "[]",
                    now,
                    now,
                ),
            )

        client = TestClient(main_module.app)
        try:
            response = client.post("/api/v1/clusters/cluster-1/refresh-profile")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["profile_status"], "refreshing")
        with connect() as conn:
            row = conn.execute(
                "SELECT status FROM app_jobs WHERE dedupe_key = ?",
                ("refresh-cluster-profile:cluster-1",),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "queued")


if __name__ == "__main__":
    unittest.main()
