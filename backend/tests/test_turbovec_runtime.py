import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient


class FakeIdMapIndex:
    def __init__(self, dim: int, bit_width: int) -> None:
        self.dim = int(dim)
        self.bit_width = int(bit_width)
        self._vectors: dict[int, np.ndarray] = {}

    def add_with_ids(self, vectors: np.ndarray, ids: np.ndarray) -> None:
        for vector, value in zip(vectors, ids, strict=False):
            self._vectors[int(value)] = np.array(vector, dtype=np.float32)

    def prepare(self) -> None:
        return None

    def remove(self, value: int) -> bool:
        key = int(value)
        existed = key in self._vectors
        self._vectors.pop(key, None)
        return existed

    def write(self, path: str) -> None:
        payload = {
            "dim": self.dim,
            "bit_width": self.bit_width,
            "ids": list(self._vectors.keys()),
            "vectors": [vector.tolist() for vector in self._vectors.values()],
        }
        Path(path).write_text(json.dumps(payload), encoding="utf-8")

    @classmethod
    def load(cls, path: str) -> "FakeIdMapIndex":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        index = cls(dim=int(payload["dim"]), bit_width=int(payload["bit_width"]))
        for value, vector in zip(payload["ids"], payload["vectors"], strict=False):
            index._vectors[int(value)] = np.array(vector, dtype=np.float32)
        return index

    def search(self, query: np.ndarray, k: int, allowlist: np.ndarray | None = None):
        allowed = {int(value) for value in allowlist.tolist()} if allowlist is not None else None
        candidates = []
        query_vector = np.array(query[0], dtype=np.float32)
        for value, vector in self._vectors.items():
            if allowed is not None and value not in allowed:
                continue
            score = float(np.dot(query_vector, vector))
            candidates.append((score, value))
        candidates.sort(key=lambda item: item[0], reverse=True)
        top = candidates[: max(0, int(k))]
        scores = np.array([[score for score, _ in top]], dtype=np.float32)
        ids = np.array([[value for _, value in top]], dtype=np.uint64)
        if not top:
            scores = np.empty((1, 0), dtype=np.float32)
            ids = np.empty((1, 0), dtype=np.uint64)
        return scores, ids

    def __len__(self) -> int:
        return len(self._vectors)


class TurbovecRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.data_dir = Path(self.tmp.name) / "data"
        self.vault_dir = Path(self.tmp.name) / "vault"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "test.sqlite3"
        os.environ["CML_DATA_DIR"] = str(self.data_dir)
        os.environ["CML_DATABASE_PATH"] = str(self.db_path)
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"
        os.environ["CML_ALLOW_UNAUTHENTICATED_API"] = "1"
        os.environ["CML_VECTOR_SEARCH_BACKEND"] = "turbovec"

        from backend.app.core.config import get_settings
        from backend.app.core.database import init_db

        get_settings.cache_clear()
        init_db()

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        for key in (
            "CML_DATA_DIR",
            "CML_DATABASE_PATH",
            "CML_EMBEDDING_PROVIDER",
            "CML_ALLOW_HASH_EMBEDDINGS",
            "CML_ALLOW_UNAUTHENTICATED_API",
            "CML_VECTOR_SEARCH_BACKEND",
            "CML_TURBOVEC_MIN_CHUNK_COUNT",
        ):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def test_semantic_search_route_uses_turbovec_backend_when_sidecar_is_published(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.core.database import connect, dict_from_row, utc_now
        from backend.app.core.embeddings import reindex_source_chunks
        from backend.app.schemas import SourceCreate
        import backend.app.core.turbovec_runtime as turbovec_runtime

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.vault_dir), now, now),
            )

        source_a = create_source(
            SourceCreate(vault_id="vault-1", title="Alpha", source_type="note", raw_text="alpha beta gamma delta")
        )
        source_b = create_source(
            SourceCreate(vault_id="vault-1", title="Bridge", source_type="note", raw_text="bridge approval token flow")
        )
        with connect() as conn:
            row_a = conn.execute("SELECT * FROM sources WHERE id = ?", (source_a["id"],)).fetchone()
            row_b = conn.execute("SELECT * FROM sources WHERE id = ?", (source_b["id"],)).fetchone()
            reindex_source_chunks(conn, dict_from_row(row_a))
            reindex_source_chunks(conn, dict_from_row(row_b))

        with patch.object(turbovec_runtime, "IdMapIndex", FakeIdMapIndex):
            built = turbovec_runtime.build_turbovec_sidecar("vault-1", rebuild_reason="test")
            self.assertEqual(built["status"], "published")
            client = self._client()
            try:
                response = client.post(
                    "/api/v1/search/semantic",
                    json={"vault_id": "vault-1", "query": "alpha beta gamma delta", "limit": 3},
                )
            finally:
                client.close()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["backend"], "turbovec")
        self.assertGreaterEqual(payload["eligible_count"], 2)
        self.assertEqual(payload["results"][0]["source_title"], "Alpha")

    def test_unclustered_semantic_scope_excludes_clustered_sources(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.core.database import connect, dict_from_row, utc_now
        from backend.app.core.embeddings import reindex_source_chunks
        from backend.app.schemas import SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.vault_dir), now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (id, vault_id, name, description, created_at, updated_at)
                VALUES ('cluster-1', 'vault-1', 'Grouped', '', ?, ?)
                """,
                (now, now),
            )
        loose = create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Loose Alpha",
                source_type="note",
                raw_text="alpha loose context",
            )
        )
        grouped = create_source(
            SourceCreate(
                vault_id="vault-1",
                cluster_id="cluster-1",
                title="Grouped Alpha",
                source_type="note",
                raw_text="alpha grouped context",
            )
        )
        with connect() as conn:
            for source_id in (loose["id"], grouped["id"]):
                row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
                reindex_source_chunks(conn, dict_from_row(row))

        client = self._client()
        try:
            response = client.post(
                "/api/v1/search/semantic",
                json={
                    "vault_id": "vault-1",
                    "query": "alpha context",
                    "unclustered_only": True,
                    "limit": 5,
                },
            )
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        titles = {item["source_title"] for item in response.json()["results"]}
        self.assertIn("Loose Alpha", titles)
        self.assertNotIn("Grouped Alpha", titles)

    def test_corrupt_manifest_path_falls_back_to_exact_and_reports_corrupt_status(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.core.database import connect, dict_from_row, utc_now
        from backend.app.core.embeddings import reindex_source_chunks
        from backend.app.schemas import SourceCreate
        import backend.app.core.turbovec_runtime as turbovec_runtime

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.vault_dir), now, now),
            )

        source = create_source(
            SourceCreate(vault_id="vault-1", title="Alpha", source_type="note", raw_text="alpha beta gamma delta")
        )
        with connect() as conn:
            row = conn.execute("SELECT * FROM sources WHERE id = ?", (source["id"],)).fetchone()
            reindex_source_chunks(conn, dict_from_row(row))

        with patch.object(turbovec_runtime, "IdMapIndex", FakeIdMapIndex):
            built = turbovec_runtime.build_turbovec_sidecar("vault-1", rebuild_reason="test")
            manifest_path = Path(built["tvim_path"]).with_name("manifest.json")
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload["tvim_path"] = str((self.vault_dir / "escaped.tvim").resolve())
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")

            status = turbovec_runtime.turbovec_sidecar_status("vault-1")
            client = self._client()
            try:
                response = client.post(
                    "/api/v1/search/semantic",
                    json={"vault_id": "vault-1", "query": "alpha beta gamma delta", "limit": 3},
                )
            finally:
                client.close()

        self.assertEqual(status["status"], "corrupt")
        self.assertIn("outside_epoch_dir", status["last_error"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["backend"], "exact")

    def test_startup_repair_summary_rebuilds_missing_sidecar_when_requested(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.core.database import connect, dict_from_row, utc_now
        from backend.app.core.embeddings import reindex_source_chunks
        from backend.app.core.startup_repair import startup_repair_summary
        from backend.app.schemas import SourceCreate
        import backend.app.core.turbovec_runtime as turbovec_runtime

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.vault_dir), now, now),
            )

        source = create_source(
            SourceCreate(vault_id="vault-1", title="Alpha", source_type="note", raw_text="alpha beta gamma delta")
        )
        with connect() as conn:
            row = conn.execute("SELECT * FROM sources WHERE id = ?", (source["id"],)).fetchone()
            reindex_source_chunks(conn, dict_from_row(row))

        with patch.object(turbovec_runtime, "IdMapIndex", FakeIdMapIndex):
            built = turbovec_runtime.build_turbovec_sidecar("vault-1", rebuild_reason="test")
            index_path = Path(built["tvim_path"])
            index_path.unlink()

            planned = startup_repair_summary(apply_recovery=False)
            repaired = startup_repair_summary(apply_recovery=True)
            status = turbovec_runtime.turbovec_sidecar_status("vault-1")

        self.assertTrue(planned["turbovec_sidecars"]["vaults"][0]["needs_rebuild"])
        self.assertEqual(planned["turbovec_sidecars"]["vaults"][0]["status"], "corrupt")
        self.assertEqual(len(repaired["turbovec_sidecars"]["rebuilt_vaults"]), 1)
        self.assertEqual(status["status"], "published")

    def test_sidecar_management_routes_build_status_and_repair(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.core.database import connect, dict_from_row, utc_now
        from backend.app.core.embeddings import reindex_source_chunks
        from backend.app.schemas import SourceCreate
        import backend.app.core.turbovec_runtime as turbovec_runtime

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.vault_dir), now, now),
            )

        source = create_source(
            SourceCreate(vault_id="vault-1", title="Alpha", source_type="note", raw_text="alpha beta gamma delta")
        )
        with connect() as conn:
            row = conn.execute("SELECT * FROM sources WHERE id = ?", (source["id"],)).fetchone()
            reindex_source_chunks(conn, dict_from_row(row))

        with patch.object(turbovec_runtime, "IdMapIndex", FakeIdMapIndex):
            client = self._client()
            try:
                built = client.post("/api/v1/search/vectors/sidecar/build?vault_id=vault-1&rebuild_reason=test")
                status = client.get("/api/v1/search/vectors/sidecar/status?vault_id=vault-1")
                repair_plan = client.get("/api/v1/search/vectors/sidecar/repair-plan?vault_id=vault-1")
                index_path = Path(built.json()["tvim_path"])
                index_path.unlink()
                repaired = client.post("/api/v1/search/vectors/sidecar/repair?vault_id=vault-1")
            finally:
                client.close()

        self.assertEqual(built.status_code, 200)
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["status"], "published")
        self.assertEqual(repair_plan.status_code, 200)
        self.assertEqual(repair_plan.json()["vaults"][0]["status"], "published")
        self.assertEqual(repaired.status_code, 200)
        self.assertEqual(len(repaired.json()["rebuilt_vaults"]), 1)

    def test_epoch_change_marks_old_sidecar_missing_for_active_tuple_and_rebuilds_new_epoch(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.core.database import connect, dict_from_row, utc_now
        from backend.app.core.embeddings import reindex_source_chunks
        from backend.app.schemas import SourceCreate
        import backend.app.core.turbovec_runtime as turbovec_runtime

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.vault_dir), now, now),
            )

        source = create_source(
            SourceCreate(vault_id="vault-1", title="Alpha", source_type="note", raw_text="alpha beta gamma delta")
        )
        with connect() as conn:
            row = conn.execute("SELECT * FROM sources WHERE id = ?", (source["id"],)).fetchone()
            reindex_source_chunks(conn, dict_from_row(row))

        with patch.object(turbovec_runtime, "IdMapIndex", FakeIdMapIndex):
            built = turbovec_runtime.build_turbovec_sidecar("vault-1", rebuild_reason="epoch-1")
            with connect() as conn:
                conn.execute(
                    """
                    INSERT INTO vault_security_metadata (
                        vault_id, security_version, kdf_algorithm, kdf_params_json,
                        passphrase_salt, passphrase_wrapped_vmk, recovery_salt, recovery_wrapped_vmk,
                        unlock_mode, pin_enabled, pin_salt, pin_wrapped_unlock_secret,
                        active_derived_state_tuple, previous_verified_tuple, created_at, updated_at
                    )
                    VALUES (?, 1, 'argon2id', '{}', '', '', '', '', 'convenience', 0, '', '', ?, '{}', ?, ?)
                    ON CONFLICT(vault_id) DO UPDATE SET active_derived_state_tuple = excluded.active_derived_state_tuple, updated_at = excluded.updated_at
                    """,
                    (
                        "vault-1",
                        json.dumps(
                            {
                                "embedding_model_id": "hash-dev",
                                "index_version": "v1",
                                "normalization_version": "norm-v1",
                                "extraction_version": "extract-v1",
                                "epoch": 2,
                            }
                        ),
                        now,
                        now,
                    ),
                )
            status_before = turbovec_runtime.turbovec_sidecar_status("vault-1")
            repaired = turbovec_runtime.repair_turbovec_sidecars("vault-1")
            status_after = turbovec_runtime.turbovec_sidecar_status("vault-1")

        self.assertEqual(built["derived_state_epoch"], 1)
        self.assertEqual(status_before["derived_state_epoch"], 2)
        self.assertEqual(status_before["status"], "missing")
        self.assertEqual(len(repaired["rebuilt_vaults"]), 1)
        self.assertEqual(repaired["rebuilt_vaults"][0]["derived_state_epoch"], 2)
        self.assertEqual(status_after["status"], "published")
        self.assertEqual(status_after["derived_state_epoch"], 2)

    def test_delete_source_removes_chunk_from_published_sidecar(self) -> None:
        from backend.app.api.routes.sources import create_source, delete_source
        from backend.app.core.database import connect, dict_from_row, utc_now
        from backend.app.core.embeddings import reindex_source_chunks
        from backend.app.schemas import SourceCreate
        import backend.app.core.turbovec_runtime as turbovec_runtime

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.vault_dir), now, now),
            )

        source_a = create_source(
            SourceCreate(vault_id="vault-1", title="Alpha", source_type="note", raw_text="alpha beta gamma delta")
        )
        source_b = create_source(
            SourceCreate(vault_id="vault-1", title="Bridge", source_type="note", raw_text="bridge approval token flow")
        )
        with connect() as conn:
            row_a = conn.execute("SELECT * FROM sources WHERE id = ?", (source_a["id"],)).fetchone()
            row_b = conn.execute("SELECT * FROM sources WHERE id = ?", (source_b["id"],)).fetchone()
            reindex_source_chunks(conn, dict_from_row(row_a))
            reindex_source_chunks(conn, dict_from_row(row_b))

        with patch.object(turbovec_runtime, "IdMapIndex", FakeIdMapIndex):
            built = turbovec_runtime.build_turbovec_sidecar("vault-1", rebuild_reason="test")
            before = turbovec_runtime.turbovec_sidecar_status("vault-1")
            delete_source(source_a["id"])
            after = turbovec_runtime.turbovec_sidecar_status("vault-1")
            client = self._client()
            try:
                response = client.post(
                    "/api/v1/search/semantic",
                    json={"vault_id": "vault-1", "query": "alpha beta gamma delta", "limit": 3},
                )
            finally:
                client.close()

        self.assertEqual(before["status"], "published")
        self.assertEqual(before["chunk_count"], 2)
        self.assertEqual(after["status"], "published")
        self.assertEqual(after["chunk_count"], 1)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["backend"], "turbovec")
        titles = [item["source_title"] for item in response.json()["results"]]
        self.assertNotIn("Alpha", titles)
        self.assertTrue(Path(built["tvim_path"]).exists())

    def test_auto_backend_requires_phase_c_approval_before_using_turbovec(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.core.database import connect, dict_from_row, utc_now
        from backend.app.core.embeddings import reindex_source_chunks
        from backend.app.schemas import SourceCreate
        import backend.app.core.turbovec_runtime as turbovec_runtime
        import backend.app.core.turbovec_benchmark as turbovec_benchmark

        os.environ["CML_VECTOR_SEARCH_BACKEND"] = "auto"
        os.environ["CML_TURBOVEC_MIN_CHUNK_COUNT"] = "1"

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", str(self.vault_dir), now, now),
            )

        source_a = create_source(
            SourceCreate(vault_id="vault-1", title="Alpha", source_type="note", raw_text="alpha beta gamma delta")
        )
        source_b = create_source(
            SourceCreate(vault_id="vault-1", title="Bridge", source_type="note", raw_text="bridge approval token flow")
        )
        with connect() as conn:
            row_a = conn.execute("SELECT * FROM sources WHERE id = ?", (source_a["id"],)).fetchone()
            row_b = conn.execute("SELECT * FROM sources WHERE id = ?", (source_b["id"],)).fetchone()
            reindex_source_chunks(conn, dict_from_row(row_a))
            reindex_source_chunks(conn, dict_from_row(row_b))

        exact_report = {
            "engine": "current_scan",
            "query_count": 1,
            "search_latency_ms": {"min": 8.0, "median": 8.0, "max": 8.0, "avg": 8.0},
            "total_latency_ms": {"min": 9.0, "median": 9.0, "max": 9.0, "avg": 9.0},
            "embedding_latency_ms": {"min": 1.0, "median": 1.0, "max": 1.0, "avg": 1.0},
            "results": [{"query": "alpha beta gamma delta", "top_chunk_ids": ["chunk-a"]}],
        }
        turbovec_report = {
            "engine": "turbovec",
            "query_count": 1,
            "search_latency_ms": {"min": 1.0, "median": 1.0, "max": 1.0, "avg": 1.0},
            "total_latency_ms": {"min": 2.0, "median": 2.0, "max": 2.0, "avg": 2.0},
            "embedding_latency_ms": {"min": 1.0, "median": 1.0, "max": 1.0, "avg": 1.0},
            "results": [{"query": "alpha beta gamma delta", "top_chunk_ids": ["chunk-a"]}],
        }
        sidecar_status = {
            "vault_id": "vault-1",
            "derived_state_epoch": 1,
            "status": "published",
            "manifest_path": str(self.vault_dir / "manifest.json"),
            "tvim_path": str(self.vault_dir / "index.tvim"),
            "chunk_count": 2,
            "allocated_slot_count": 2,
            "cold_load_seconds": 0.25,
            "tvim_size_bytes": 128,
            "last_error": "",
            "last_error_at": "",
        }

        with patch.object(turbovec_runtime, "IdMapIndex", FakeIdMapIndex):
            turbovec_runtime.build_turbovec_sidecar("vault-1", rebuild_reason="test")
            client = self._client()
            try:
                before = client.post(
                    "/api/v1/search/semantic",
                    json={"vault_id": "vault-1", "query": "alpha beta gamma delta", "limit": 3},
                )
                with (
                    patch.object(turbovec_benchmark, "sampled_queries", return_value=["alpha beta gamma delta"]),
                    patch.object(turbovec_benchmark, "benchmark_current_scan", return_value=exact_report),
                    patch.object(turbovec_benchmark, "benchmark_turbovec_scan", return_value=turbovec_report),
                    patch.object(turbovec_benchmark, "corpus_stats", return_value={"total_embedding_bytes": 1024}),
                    patch.object(turbovec_runtime, "_sidecar_status_for_snapshot", return_value=sidecar_status),
                ):
                    benchmark = client.post("/api/v1/search/vectors/phase-c/benchmark?vault_id=vault-1&query_limit=1&top_k=1")
                    status = client.get("/api/v1/search/vectors/phase-c/status?vault_id=vault-1")
                after = client.post(
                    "/api/v1/search/semantic",
                    json={"vault_id": "vault-1", "query": "alpha beta gamma delta", "limit": 3},
                )
            finally:
                client.close()

        self.assertEqual(before.status_code, 200)
        self.assertEqual(before.json()["backend"], "exact")
        self.assertEqual(benchmark.status_code, 200)
        self.assertTrue(benchmark.json()["approved"])
        self.assertEqual(status.status_code, 200)
        self.assertTrue(status.json()["approved"])
        self.assertEqual(after.status_code, 200)
        self.assertEqual(after.json()["backend"], "turbovec")

    def test_exact_search_reuses_cached_snapshot_and_only_hydrates_top_hits(self) -> None:
        from backend.app.core.database import connect
        import backend.app.core.turbovec_runtime as turbovec_runtime

        turbovec_runtime._EXACT_SEARCH_CACHE.clear()
        snapshot = {
            "epoch": 1,
            "embedding_model_id": "hash",
            "index_version": "v1",
            "normalization_version": "norm-v1",
            "extraction_version": "extract-v1",
        }
        cached_snapshot = turbovec_runtime.ExactSearchSnapshot(
            chunk_ids=["chunk-a", "chunk-b", "chunk-c"],
            vectors=np.array(
                [
                    [1.0, 0.0, 0.0],
                    [0.8, 0.0, 0.0],
                    [0.1, 0.0, 0.0],
                ],
                dtype=np.float32,
            ),
            trust_weights=np.array([1.0, 1.0, 1.0], dtype=np.float32),
        )
        build_calls: list[str] = []
        hydrate_calls: list[list[str]] = []

        def fake_build(_conn, _vault_id, *, snapshot, cluster_id, expected_dim):
            build_calls.append(f"{snapshot['epoch']}:{cluster_id or ''}")
            self.assertEqual(expected_dim, 3)
            return cached_snapshot

        def fake_hydrate(_conn, _vault_id, *, snapshot, cluster_id, chunk_ids):
            hydrate_calls.append(list(chunk_ids or []))
            rows = {
                "chunk-a": {
                    "chunk_id": "chunk-a",
                    "source_id": "source-a",
                    "source_title": "Alpha",
                    "source_type": "note",
                    "cluster_id": None,
                    "page_id": None,
                    "page_number": None,
                    "chunk_index": 0,
                    "text": "alpha",
                    "provenance": "local",
                    "trust_tier": "trusted_local",
                    "security_labels": "[]",
                },
                "chunk-b": {
                    "chunk_id": "chunk-b",
                    "source_id": "source-b",
                    "source_title": "Beta",
                    "source_type": "note",
                    "cluster_id": None,
                    "page_id": None,
                    "page_number": None,
                    "chunk_index": 1,
                    "text": "beta",
                    "provenance": "local",
                    "trust_tier": "trusted_local",
                    "security_labels": "[]",
                },
            }
            return [rows[chunk_id] for chunk_id in reversed(chunk_ids or []) if chunk_id in rows]

        with (
            patch.object(turbovec_runtime, "_build_exact_search_snapshot", side_effect=fake_build),
            patch.object(turbovec_runtime, "_hydrate_candidate_rows", side_effect=fake_hydrate),
            connect() as conn,
        ):
            first = turbovec_runtime._semantic_search_exact(
                conn,
                "vault-1",
                [1.0, 0.0, 0.0],
                snapshot=snapshot,
                cluster_id=None,
                limit=2,
            )
            second = turbovec_runtime._semantic_search_exact(
                conn,
                "vault-1",
                [1.0, 0.0, 0.0],
                snapshot=snapshot,
                cluster_id=None,
                limit=2,
            )

        self.assertEqual(build_calls, ["1:"])
        self.assertEqual(hydrate_calls, [["chunk-a", "chunk-b"], ["chunk-a", "chunk-b"]])
        self.assertEqual([item["chunk_id"] for item in first], ["chunk-a", "chunk-b"])
        self.assertEqual([item["chunk_id"] for item in second], ["chunk-a", "chunk-b"])

    def _client(self) -> TestClient:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        import backend.app.main as main_module

        main_module = importlib.reload(main_module)
        return TestClient(main_module.app)


if __name__ == "__main__":
    unittest.main()
