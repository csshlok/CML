import json
from pathlib import Path

import pytest


@pytest.fixture()
def security_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("CML_DATA_DIR", str(data_dir))
    monkeypatch.setenv("CML_DATABASE_PATH", str(tmp_path / "vault.sqlite3"))
    monkeypatch.setenv("CML_EMBEDDING_PROVIDER", "hash")
    monkeypatch.setenv("CML_ALLOW_HASH_EMBEDDINGS", "1")
    from backend.app.core.config import get_settings

    get_settings.cache_clear()
    from backend.app.core.database import init_db
    from backend.app.core.migrations import run_migrations

    init_db()
    run_migrations()
    yield data_dir
    get_settings.cache_clear()


def test_security_schedule_defaults_to_full_check_every_30_days(security_runtime: Path) -> None:
    from backend.app.core.security_scans import security_scan_status

    status = security_scan_status()
    assert status["enabled"] is True
    assert status["interval_days"] == 30
    assert status["last_status"] == "never_run"
    assert status["next_run_at"]


def test_security_schedule_can_be_changed_and_disabled(security_runtime: Path) -> None:
    from backend.app.core.security_scans import update_security_scan_schedule

    changed = update_security_scan_schedule(enabled=True, interval_days=45)
    assert changed["enabled"] is True
    assert changed["interval_days"] == 45
    assert changed["next_run_at"]

    disabled = update_security_scan_schedule(enabled=False, interval_days=None)
    assert disabled["enabled"] is False
    assert disabled["interval_days"] == 45
    assert disabled["next_run_at"] is None


def test_manual_full_check_runs_as_a_durable_job(
    security_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api.routes.diagnostics import queue_security_scan
    from backend.app.core.background_jobs import run_due_jobs_once
    from backend.app.core.database import connect
    from backend.app.schemas import SecurityScanRequest

    monkeypatch.setattr(
        "backend.app.core.security_scans._run_antivirus_scan",
        lambda: {
            "id": "antivirus",
            "label": "Microsoft Defender antivirus",
            "status": "passed",
            "detail": "Test scan passed.",
        },
    )
    queued = queue_security_scan(SecurityScanRequest(scan_type="full"))
    duplicate = queue_security_scan(SecurityScanRequest(scan_type="full"))
    assert duplicate["id"] == queued["id"]
    assert run_due_jobs_once(limit=1) == 1

    with connect() as conn:
        completed = dict(conn.execute("SELECT * FROM app_jobs WHERE id = ?", (queued["id"],)).fetchone())
    result = json.loads(completed["result_json"])
    assert completed["status"] == "succeeded"
    assert result["scan_type"] == "full"
    assert result["status"] == "passed"
    assert {check["id"] for check in result["checks"]} >= {
        "antivirus",
        "database_integrity",
        "encrypted_storage",
        "client_scopes",
    }


def test_due_schedule_enqueues_exactly_one_full_check(security_runtime: Path) -> None:
    from backend.app.core.database import connect, utc_now
    from backend.app.core.security_scans import enqueue_due_security_scan, security_scan_status

    security_scan_status()
    with connect() as conn:
        conn.execute(
            "UPDATE security_scan_settings SET next_run_at = '2000-01-01T00:00:00Z', updated_at = ?",
            (utc_now(),),
        )
    first = enqueue_due_security_scan()
    second = enqueue_due_security_scan()
    assert first is not None
    assert second is None
    with connect() as conn:
        jobs = conn.execute(
            "SELECT payload FROM app_jobs WHERE job_type = 'security_scan'"
        ).fetchall()
    assert len(jobs) == 1
    assert json.loads(jobs[0]["payload"]) == {
        "scan_type": "full",
        "trigger": "scheduled",
    }


def test_deduped_active_scan_does_not_advance_due_schedule(security_runtime: Path) -> None:
    from backend.app.core.database import connect, utc_now
    from backend.app.core.security_scans import enqueue_due_security_scan, security_scan_status

    security_scan_status()
    due = "2000-01-01T00:00:00Z"
    with connect() as conn:
        conn.execute(
            "UPDATE security_scan_settings SET next_run_at = ?, updated_at = ? WHERE id = 'default'",
            (due, utc_now()),
        )
    assert enqueue_due_security_scan() is not None
    assert enqueue_due_security_scan() is None
    with connect() as conn:
        stored = conn.execute(
            "SELECT next_run_at FROM security_scan_settings WHERE id = 'default'"
        ).fetchone()
    assert stored["next_run_at"] == due
