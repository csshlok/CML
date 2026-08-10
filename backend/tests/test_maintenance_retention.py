from datetime import datetime, timezone
import sqlite3

from backend.app.core.maintenance import run_maintenance


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE app_jobs (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE chat_generations (
            id TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE cli_sessions (
            id TEXT PRIMARY KEY,
            expires_at TEXT NOT NULL,
            revoked_at TEXT
        );
        CREATE TABLE source_quarantine_records (
            id TEXT PRIMARY KEY,
            vault_id TEXT NOT NULL,
            source_id TEXT,
            encrypted_blob_id TEXT NOT NULL DEFAULT '',
            parser_status TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    return conn


def test_retention_is_bounded_and_never_deletes_active_or_retriable_rows() -> None:
    conn = _connection()
    old = "2025-01-01T00:00:00+00:00"
    conn.executemany(
        "INSERT INTO app_jobs VALUES (?, ?, ?)",
        [
            ("job-1", "succeeded", old),
            ("job-2", "cancelled", old),
            ("job-3", "succeeded", old),
            ("job-active", "running", old),
        ],
    )
    conn.executemany(
        "INSERT INTO chat_generations VALUES (?, ?, ?)",
        [
            ("generation-complete", "completed", old),
            ("generation-retriable", "retriable", old),
            ("generation-active", "in_flight", old),
        ],
    )

    report = run_maintenance(
        connection=conn,
        batch_size=2,
        now=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )

    remaining_jobs = {
        row["id"] for row in conn.execute("SELECT id FROM app_jobs").fetchall()
    }
    remaining_generations = {
        row["id"] for row in conn.execute("SELECT id FROM chat_generations").fetchall()
    }
    assert len(remaining_jobs & {"job-1", "job-2", "job-3"}) == 1
    assert "job-active" in remaining_jobs
    assert remaining_generations == {"generation-retriable", "generation-active"}
    assert report["policies"]["jobs_terminal"]["deleted"] == 2
    assert report["policies"]["jobs_terminal"]["batch_limited"] is True
    assert report["vacuum_run"] is False


def test_retention_dry_run_reports_without_mutating() -> None:
    conn = _connection()
    old = "2025-01-01T00:00:00+00:00"
    conn.execute("INSERT INTO app_jobs VALUES ('job-old', 'succeeded', ?)", (old,))
    conn.execute("INSERT INTO cli_sessions VALUES ('cli-old', ?, NULL)", (old,))

    report = run_maintenance(
        connection=conn,
        dry_run=True,
        batch_size=10,
        now=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )

    assert conn.execute("SELECT COUNT(*) FROM app_jobs").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM cli_sessions").fetchone()[0] == 1
    assert report["deleted"] == 0
    assert report["policies"]["jobs_terminal"]["eligible"] == 1
    assert report["policies"]["cli_sessions"]["eligible"] == 1


def test_quarantine_retention_preserves_recent_failures_and_prunes_old_unattached_rows() -> None:
    conn = _connection()
    conn.executemany(
        "INSERT INTO source_quarantine_records VALUES (?, 'vault-1', NULL, '', ?, ?)",
        [
            ("passed-old", "passed", "2026-01-01T00:00:00+00:00"),
            ("failed-old", "failed", "2026-01-01T00:00:00+00:00"),
            ("failed-recent", "failed", "2026-08-01T00:00:00+00:00"),
        ],
    )

    report = run_maintenance(
        connection=conn,
        batch_size=10,
        now=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )

    remaining = {
        row["id"] for row in conn.execute("SELECT id FROM source_quarantine_records").fetchall()
    }
    assert remaining == {"failed-recent"}
    assert report["policies"]["quarantine_artifacts"]["deleted"] == 2
