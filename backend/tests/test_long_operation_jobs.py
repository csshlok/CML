import json
from pathlib import Path

import pytest


@pytest.fixture()
def job_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("CML_DATA_DIR", str(data_dir))
    monkeypatch.setenv("CML_DATABASE_PATH", str(tmp_path / "jobs.sqlite3"))
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


def test_model_discovery_job_is_deduplicated_and_persists_result(
    job_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api.routes.models import queue_model_discovery
    from backend.app.core.background_jobs import run_due_jobs_once
    from backend.app.core.database import connect
    from backend.app.schemas import ModelDiscoveryJobRequest

    progress_events: list[dict] = []

    def discover(**kwargs):
        kwargs["progress_callback"]({"phase": "scanning", "completed": 2, "total": 4})
        kwargs["cancellation_callback"]()
        progress_events.append(kwargs)
        return {
            "models": [{"id": "local-model", "name": "Local model"}],
            "roots": [str(job_runtime / "models")],
            "truncated": False,
        }

    monkeypatch.setattr("backend.app.core.model_registry.discover_installed_models", discover)
    request = ModelDiscoveryJobRequest(
        max_results=25,
        include_rejected=False,
        idempotency_key="model-discovery-test-key",
    )
    first = queue_model_discovery(request)
    second = queue_model_discovery(request)
    assert second["id"] == first["id"]
    assert run_due_jobs_once(limit=1) == 1

    with connect() as conn:
        completed = dict(conn.execute("SELECT * FROM app_jobs WHERE id = ?", (first["id"],)).fetchone())
    result = json.loads(completed["result_json"])
    assert completed["status"] == "succeeded"
    assert completed["status_detail"] == "Found 1 compatible local models."
    assert result["models"][0]["id"] == "local-model"
    assert progress_events and progress_events[0]["refresh"] is True


def test_diagnostic_bundle_job_returns_a_redacted_durable_artifact(job_runtime: Path) -> None:
    from backend.app.api.routes.diagnostics import queue_diagnostic_bundle
    from backend.app.core.background_jobs import run_due_jobs_once
    from backend.app.core.database import connect
    from backend.app.schemas import DiagnosticBundleJobRequest

    queued = queue_diagnostic_bundle(
        DiagnosticBundleJobRequest(idempotency_key="diagnostic-bundle-test-key")
    )
    duplicate = queue_diagnostic_bundle(
        DiagnosticBundleJobRequest(idempotency_key="diagnostic-bundle-test-key")
    )
    assert duplicate["id"] == queued["id"]
    assert run_due_jobs_once(limit=1) == 1

    with connect() as conn:
        completed = dict(conn.execute("SELECT * FROM app_jobs WHERE id = ?", (queued["id"],)).fetchone())
    result = json.loads(completed["result_json"])
    bundle = Path(result["bundle_path"])
    assert completed["status"] == "succeeded"
    assert completed["status_detail"] == "Diagnostic bundle is ready."
    assert bundle.is_file()
    assert bundle.parent == job_runtime / "diagnostics"
    assert "manifest.json" in result["included_files"]
