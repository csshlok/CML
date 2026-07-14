from __future__ import annotations

import os
import tempfile
import time
import tracemalloc
from pathlib import Path

import pytest

from backend.app.core.projects import discover_project


@pytest.mark.skipif(os.getenv("ODIN_RUN_SCALE_TESTS") != "1", reason="Run explicitly for the Odin release scale gate.")
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
