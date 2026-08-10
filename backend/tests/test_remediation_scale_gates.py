from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

import psutil
import pytest


pytestmark = [
    pytest.mark.scale,
    pytest.mark.skipif(
        os.getenv("CML_RUN_REMEDIATION_SCALE") != "1",
        reason="Run explicitly for the stability remediation scale gate.",
    ),
    pytest.mark.timeout(300),
]


class _Rows:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict]:
        return self._rows


class _MillionChunkConnection:
    def __init__(self, count: int, dimensions: int) -> None:
        self.count = count
        self.dimensions = dimensions
        self.offset = 0
        self.embedding = json.dumps([1.0, *([0.0] * (dimensions - 1))])

    def execute(self, _query: str, params: list[object]) -> _Rows:
        requested = int(params[-1])
        start = self.offset
        stop = min(self.count, start + requested)
        self.offset = stop
        return _Rows(
            [
                {
                    "chunk_id": f"chunk-{index:07d}",
                    "created_at": f"2026-01-01T00:{index // 60 % 60:02d}:{index % 60:02d}+00:00",
                    "embedding": self.embedding,
                    "trust_tier": "trusted_local",
                    "security_labels": "[]",
                }
                for index in range(start, stop)
            ]
        )


def _sample_peak_rss(stop: threading.Event, samples: list[int]) -> None:
    process = psutil.Process()
    while not stop.wait(0.01):
        samples.append(process.memory_info().rss)
    samples.append(process.memory_info().rss)


def test_exact_fallback_streams_one_million_chunks_with_bounded_rss() -> None:
    from backend.app.core import turbovec_runtime

    connection = _MillionChunkConnection(1_000_000, 8)
    snapshot = {
        "embedding_model_id": "hash",
        "index_version": "v1",
        "normalization_version": "norm-v1",
        "extraction_version": "extract-v1",
        "epoch": 1,
    }
    stop = threading.Event()
    rss_samples = [psutil.Process().memory_info().rss]
    sampler = threading.Thread(target=_sample_peak_rss, args=(stop, rss_samples), daemon=True)
    sampler.start()
    started = time.perf_counter()
    try:
        with patch.object(
            turbovec_runtime,
            "_hydrate_scored_rows",
            side_effect=lambda _conn, _vault_id, **kwargs: kwargs["chunk_ids"],
        ):
            winners = turbovec_runtime._semantic_search_exact_streaming(
                connection,
                "vault-scale",
                [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                snapshot=snapshot,
                cluster_id=None,
                limit=25,
            )
    finally:
        stop.set()
        sampler.join(timeout=2)
    elapsed = time.perf_counter() - started
    peak_delta = max(rss_samples) - min(rss_samples)

    assert connection.offset == 1_000_000
    assert len(winners) == 25
    assert peak_delta < 96 * 1024 * 1024
    print(
        "exact_fallback_1m "
        f"elapsed_seconds={elapsed:.3f} peak_rss_delta_mib={peak_delta / 1024 / 1024:.1f}"
    )


def test_root_scoped_reconcile_stays_bounded_in_a_100k_source_vault(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database_path = tmp_path / "root-scope-scale.sqlite3"
    monkeypatch.setenv("CML_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("CML_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CML_EMBEDDING_PROVIDER", "hash")
    monkeypatch.setenv("CML_ALLOW_HASH_EMBEDDINGS", "1")

    from backend.app.core.config import get_settings

    get_settings.cache_clear()
    try:
        from backend.app.api.routes.integrations import _reconcile_import_sources
        from backend.app.core.database import connect, init_db

        init_db()
        watched_root = tmp_path / "watched"
        watched_root.mkdir()
        other_root = tmp_path / "other"
        other_root.mkdir()
        watched_root_text = str(watched_root.resolve())
        other_root_text = str(other_root.resolve())
        now = "2026-08-10T00:00:00+00:00"
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-scale", "Scale", str(tmp_path), now, now),
            )
            conn.execute(
                """
                INSERT INTO integration_imports (
                    id, vault_id, integration_type, root_path, status, supported_count,
                    skipped_count, truncated, last_scan_at, created_at, updated_at
                ) VALUES ('import-scale', 'vault-scale', 'local_folder', ?, 'scanned', 0, 0, 0, ?, ?, ?)
                """,
                (watched_root_text, now, now, now),
            )
            conn.executemany(
                """
                INSERT INTO sources (
                    id, vault_id, title, source_type, state, original_path, import_root_path,
                    checksum, created_at, updated_at
                ) VALUES (?, 'vault-scale', ?, 'note', 'indexed', ?, ?, ?, ?, ?)
                """,
                (
                    (
                        f"outside-{index:06d}",
                        f"Outside {index}",
                        str(other_root / f"outside-{index:06d}.md"),
                        other_root_text,
                        f"outside-checksum-{index:06d}",
                        now,
                        now,
                    )
                    for index in range(99_900)
                ),
            )
            conn.executemany(
                """
                INSERT INTO sources (
                    id, vault_id, title, source_type, state, original_path, import_root_path,
                    checksum, created_at, updated_at
                ) VALUES (?, 'vault-scale', ?, 'note', 'indexed', ?, ?, ?, ?, ?)
                """,
                (
                    (
                        f"inside-{index:04d}",
                        f"Inside {index}",
                        str(watched_root / f"inside-{index:04d}.md"),
                        watched_root_text,
                        f"inside-checksum-{index:04d}",
                        now,
                        now,
                    )
                    for index in range(100)
                ),
            )

        supported = [str(watched_root / f"inside-{index:04d}.md") for index in range(100)]
        checksum_by_path = {
            path: f"inside-checksum-{index:04d}" for index, path in enumerate(supported)
        }
        start_rss = psutil.Process().memory_info().rss
        started = time.perf_counter()
        with patch(
            "backend.app.api.routes.integrations.file_checksum",
            side_effect=lambda path: checksum_by_path[str(path)],
        ), patch(
            "backend.app.api.routes.integrations._reconcile_single_supported_file",
            return_value={"action": "unchanged", "source_id": None, "detail": {}},
        ):
            result = _reconcile_import_sources(
                vault_id="vault-scale",
                import_id="import-scale",
                run_id=None,
                root_path=watched_root_text,
                supported_files=supported,
                tombstone_missing=False,
                scan_cycle_id="scale-cycle",
                scan_complete=True,
            )
        elapsed = time.perf_counter() - started
        rss_delta = max(0, psutil.Process().memory_info().rss - start_rss)

        assert result["unchanged_count"] == 100
        assert result["continuation_required"] is False
        assert rss_delta < 64 * 1024 * 1024
        assert elapsed < 10
        print(
            "root_scoped_reconcile_100k "
            f"elapsed_seconds={elapsed:.3f} rss_delta_mib={rss_delta / 1024 / 1024:.1f}"
        )
    finally:
        get_settings.cache_clear()


def test_watched_discovery_checkpoints_all_5000_files_with_bounded_rss(tmp_path: Path) -> None:
    from backend.app.core.local_integrations import scan_local_folder

    watched_root = tmp_path / "five-thousand-watch"
    watched_root.mkdir()
    for group in range(50):
        folder = watched_root / f"group-{group:02d}"
        folder.mkdir()
        for index in range(100):
            (folder / f"note-{index:03d}.md").write_text("scale note", encoding="utf-8")

    cursor = ""
    discovered: set[str] = set()
    batch_sizes: list[int] = []
    start_rss = psutil.Process().memory_info().rss
    started = time.perf_counter()
    while True:
        result = scan_local_folder(str(watched_root), 250, cursor=cursor)
        batch_sizes.append(result["supported_count"])
        batch = set(result["supported_files"])
        assert not discovered.intersection(batch)
        discovered.update(batch)
        if result["scan_complete"]:
            break
        assert result["scan_cursor"] and result["scan_cursor"] != cursor
        cursor = result["scan_cursor"]
    elapsed = time.perf_counter() - started
    rss_delta = max(0, psutil.Process().memory_info().rss - start_rss)

    assert len(discovered) == 5_000
    assert len(batch_sizes) == 20
    assert max(batch_sizes) == 250
    assert rss_delta < 64 * 1024 * 1024
    print(
        "watched_discovery_5k "
        f"elapsed_seconds={elapsed:.3f} rss_delta_mib={rss_delta / 1024 / 1024:.1f}"
    )
