from __future__ import annotations

import os
import tempfile
import time
import tracemalloc
from pathlib import Path

import pytest

from backend.app.core.projects import discover_project


@pytest.mark.skipif(os.getenv("ODIN_RUN_SCALE_TESTS") != "1", reason="Run explicitly for the Odin release scale gate.")
@pytest.mark.timeout(300)
def test_discovery_handles_50000_files_with_bounded_peak_memory() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        root = Path(directory)
        template = "value = 1\n"
        for group in range(100):
            folder = root / f"package_{group:03d}"
            folder.mkdir()
            for index in range(500):
                (folder / f"module_{index:03d}.py").write_text(template, encoding="utf-8")

        tracemalloc.start()
        started = time.perf_counter()
        result = discover_project(root)
        elapsed = time.perf_counter() - started
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        assert len(result.files) == 50_000
        assert peak < 350 * 1024 * 1024
        print(f"odin_discovery_50k elapsed_seconds={elapsed:.3f} peak_mib={peak / 1024 / 1024:.1f}")


def test_product_routes_remain_bounded_with_large_vault_metadata(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "product-scale.sqlite3"
    monkeypatch.setenv("CML_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("CML_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CML_EMBEDDING_PROVIDER", "hash")
    monkeypatch.setenv("CML_ALLOW_HASH_EMBEDDINGS", "1")

    from backend.app.core.config import get_settings

    get_settings.cache_clear()
    try:
        from backend.app.api.routes.activity import list_activity
        from backend.app.api.routes.chat import list_chat_sessions
        from backend.app.api.routes.clusters import list_clusters
        from backend.app.api.routes.sources import count_sources, list_sources
        from backend.app.core.background_jobs import job_queue_status
        from backend.app.core.database import connect, init_db

        init_db()
        now = "2026-07-25T00:00:00+00:00"
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-scale", "Scale vault", str(tmp_path), now, now),
            )
            conn.executemany(
                """
                INSERT INTO clusters (id, vault_id, name, created_at, updated_at)
                VALUES (?, 'vault-scale', ?, ?, ?)
                """,
                (
                    (f"cluster-{index:04d}", f"Cluster {index:04d}", now, f"2026-07-25T00:{index % 60:02d}:00+00:00")
                    for index in range(1_000)
                ),
            )
            conn.executemany(
                """
                INSERT INTO sources (
                    id, vault_id, cluster_id, title, source_type, state, summary,
                    created_at, updated_at
                )
                VALUES (?, 'vault-scale', ?, ?, 'note', 'indexed', ?, ?, ?)
                """,
                (
                    (
                        f"source-{index:05d}",
                        f"cluster-{index % 1_000:04d}",
                        f"Source {index:05d}",
                        "deep scale needle" if index == 9_999 else "",
                        now,
                        f"2026-07-25T{index % 24:02d}:{index % 60:02d}:00+00:00",
                    )
                    for index in range(10_000)
                ),
            )
            conn.executemany(
                """
                INSERT INTO chat_sessions (id, vault_id, title, created_at, updated_at)
                VALUES (?, 'vault-scale', ?, ?, ?)
                """,
                (
                    (
                        f"chat-{index:04d}",
                        f"Chat {index:04d}",
                        now,
                        f"2026-07-25T{index % 24:02d}:{index % 60:02d}:30+00:00",
                    )
                    for index in range(1_000)
                ),
            )
            conn.executemany(
                """
                INSERT INTO app_jobs (
                    id, job_type, status, payload, attempts, max_attempts,
                    last_error, created_at, updated_at
                )
                VALUES (?, 'reindex_source', ?, '{}', 0, 3, '', ?, ?)
                """,
                (
                    (
                        f"job-{index:05d}",
                        "queued" if index % 4 == 0 else "succeeded",
                        now,
                        f"2026-07-25T{index % 24:02d}:{index % 60:02d}:45+00:00",
                    )
                    for index in range(10_000)
                ),
            )

        started = time.perf_counter()
        source_count = count_sources(vault_id="vault-scale")
        source_match = list_sources(vault_id="vault-scale", q="deep scale needle", limit=50)
        chats_page = list_chat_sessions("vault-scale", limit=75, offset=925)
        clusters_page = list_clusters("vault-scale", limit=250, offset=750)
        activity_page = list_activity("vault-scale", limit=10_000, offset=11_900)
        jobs = job_queue_status()
        query_elapsed = time.perf_counter() - started

        assert source_count["total"] == 10_000
        assert [source["id"] for source in source_match] == ["source-09999"]
        assert len(chats_page) == 75
        assert len(clusters_page) == 250
        assert activity_page["total"] == 12_000
        assert activity_page["limit"] == 250
        assert len(activity_page["items"]) == 100
        assert jobs["queued"] == 2_500
        assert jobs["succeeded"] == 7_500
        assert len(jobs["latest"]) == 10
        assert len(jobs["running_jobs"]) == 0
        assert query_elapsed < 10
        print(f"product_metadata_scale query_seconds={query_elapsed:.3f}")
    finally:
        get_settings.cache_clear()
