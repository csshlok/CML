from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch


def _load_soak_module():
    script = Path(__file__).resolve().parents[2] / "scripts" / "backend" / "soak-remediation.py"
    spec = importlib.util.spec_from_file_location("remediation_soak", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_matching_file_bytes_ignores_transient_sqlite_sidecar(tmp_path: Path) -> None:
    soak = _load_soak_module()
    database = tmp_path / "cml.sqlite3"
    sidecar = tmp_path / "cml.sqlite3-shm"
    database.write_bytes(b"database")
    sidecar.write_bytes(b"sidecar")
    original_stat = Path.stat

    def transient_stat(path: Path, *args, **kwargs):
        if path == sidecar:
            raise FileNotFoundError(path)
        return original_stat(path, *args, **kwargs)

    with patch.object(Path, "stat", transient_stat):
        assert soak.matching_file_bytes(tmp_path, "cml.sqlite3*") == len(b"database")


def test_matching_file_bytes_ignores_temporarily_locked_sidecar(tmp_path: Path) -> None:
    soak = _load_soak_module()
    database = tmp_path / "cml.sqlite3"
    sidecar = tmp_path / "cml.sqlite3-wal"
    database.write_bytes(b"database")
    sidecar.write_bytes(b"sidecar")
    original_is_file = Path.is_file

    def transient_is_file(path: Path) -> bool:
        if path == sidecar:
            raise PermissionError(path)
        return original_is_file(path)

    with patch.object(Path, "is_file", transient_is_file):
        assert soak.matching_file_bytes(tmp_path, "cml.sqlite3*") == len(b"database")
