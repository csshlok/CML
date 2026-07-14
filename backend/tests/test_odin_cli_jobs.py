from __future__ import annotations

import pytest

from backend.app.odin_cli import EXIT_CANCELLED, OdinClientError, _wait_for_project_run


class _RunClient:
    def __init__(self, runs: list[dict]):
        self.runs = list(runs)
        self.requests: list[tuple[str, str]] = []

    def request(self, method: str, path: str, payload=None):
        self.requests.append((method, path))
        if path.endswith("/cancel"):
            return {"id": "run-1", "status": "cancelled"}
        if "/runs/" in path:
            value = self.runs.pop(0)
            if isinstance(value, BaseException):
                raise value
            return value
        if path == "projects/project-1":
            return {"id": "project-1", "active_snapshot_id": "snapshot-new"}
        raise AssertionError(path)


def test_wait_for_project_run_returns_only_after_terminal_success(monkeypatch, capsys):
    monkeypatch.setenv("ODIN_RUN_POLL_SECONDS", "0.1")
    monkeypatch.setattr("backend.app.odin_cli.time.sleep", lambda _seconds: None)
    client = _RunClient([
        {"id": "run-1", "status": "running", "phase": "structure", "phase_completed_count": 1, "phase_total_count": 3},
        {"id": "run-1", "status": "succeeded", "phase": "activated", "phase_completed_count": 3, "phase_total_count": 3},
    ])

    result = _wait_for_project_run(client, {"id": "project-1"}, {"id": "run-1"})

    assert result["status"] == "succeeded"
    assert result["project"]["active_snapshot_id"] == "snapshot-new"
    lines = [line for line in capsys.readouterr().err.splitlines() if line]
    assert all('"type":"odin.project.progress"' in line for line in lines)


def test_ctrl_c_requests_cancellation_once_and_uses_cancelled_exit_code():
    client = _RunClient([KeyboardInterrupt()])

    with pytest.raises(OdinClientError) as cancelled:
        _wait_for_project_run(
            client,
            {"id": "project-1", "active_snapshot_id": "snapshot-old"},
            {"id": "run-1"},
        )

    assert cancelled.value.exit_code == EXIT_CANCELLED
    assert client.requests.count(("POST", "projects/project-1/cancel")) == 1
    assert "snapshot-old remains active" in str(cancelled.value)
