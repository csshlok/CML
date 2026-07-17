import os
import sqlite3
import tempfile
import unittest
from pathlib import Path


class OdinReleaseMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.database_path = Path(self.tmp.name) / "odin-v9.sqlite3"
        os.environ["CML_DATABASE_PATH"] = str(self.database_path)
        os.environ["CML_DATA_DIR"] = str(Path(self.tmp.name) / "data")
        from backend.app.core.config import get_settings

        get_settings.cache_clear()

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        os.environ.pop("CML_DATABASE_PATH", None)
        os.environ.pop("CML_DATA_DIR", None)
        self.tmp.cleanup()

    def _create_v9_contract_fixture(self) -> None:
        conn = sqlite3.connect(self.database_path)
        conn.executescript(
            """
            PRAGMA foreign_keys = OFF;
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                error TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE projects (
                id TEXT PRIMARY KEY,
                active_snapshot_id TEXT
            );
            CREATE TABLE project_snapshots (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                activated_at TEXT,
                structure_status TEXT NOT NULL,
                retrieval_status TEXT NOT NULL
            );
            CREATE TABLE project_index_runs (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE sources (
                id TEXT PRIMARY KEY
            );
            CREATE TABLE source_chunks (
                id TEXT PRIMARY KEY
            );
            CREATE TABLE project_sources (
                project_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                file_role TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                discovered_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO projects (id, active_snapshot_id) VALUES ('project-old', 'snapshot-old');
            INSERT INTO project_snapshots (
                id, project_id, activated_at, structure_status, retrieval_status
            ) VALUES (
                'snapshot-old', 'project-old', '2026-07-01T00:00:00Z', 'ready', 'partial'
            );
            INSERT INTO sources (id) VALUES ('source-old');
            INSERT INTO project_sources (
                project_id, source_id, relative_path, file_role, content_hash, discovered_at, updated_at
            ) VALUES (
                'project-old', 'source-old', 'src/main.py', 'source', 'hash-old',
                '2026-07-01T00:00:00Z', '2026-07-01T00:00:00Z'
            );
            """
        )
        conn.executemany(
            """
            INSERT INTO schema_migrations (
                version, name, started_at, finished_at, status, error
            ) VALUES (?, ?, '2026-07-01T00:00:00Z', '2026-07-01T00:00:01Z', 'succeeded', '')
            """,
            [(version, f"migration-{version}") for version in range(1, 10)],
        )
        conn.commit()
        conn.close()

    def test_v10_migration_backfills_active_layers_and_snapshot_membership(self) -> None:
        self._create_v9_contract_fixture()
        from backend.app.core.database import connect
        from backend.app.core.migrations import run_migrations

        run_migrations()

        with connect() as conn:
            project = conn.execute("SELECT * FROM projects WHERE id = 'project-old'").fetchone()
            snapshot = conn.execute("SELECT * FROM project_snapshots WHERE id = 'snapshot-old'").fetchone()
            membership = conn.execute("SELECT * FROM project_snapshot_sources").fetchone()
            migration = conn.execute("SELECT * FROM schema_migrations WHERE version = 10").fetchone()
            scope_migration = conn.execute("SELECT * FROM schema_migrations WHERE version = 11").fetchone()
            tables = {
                row["name"]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            }
            source_columns = {row["name"] for row in conn.execute("PRAGMA table_info(sources)").fetchall()}
            chunk_columns = {row["name"] for row in conn.execute("PRAGMA table_info(source_chunks)").fetchall()}

        self.assertEqual(project["active_manifest_snapshot_id"], "snapshot-old")
        self.assertEqual(project["active_structure_snapshot_id"], "snapshot-old")
        self.assertEqual(project["active_retrieval_snapshot_id"], "snapshot-old")
        self.assertEqual(snapshot["manifest_activated_at"], snapshot["activated_at"])
        self.assertEqual(snapshot["structure_activated_at"], snapshot["activated_at"])
        self.assertEqual(snapshot["retrieval_activated_at"], snapshot["activated_at"])
        self.assertEqual(membership["source_id"], "source-old")
        self.assertEqual(membership["stage_status"], "active")
        self.assertEqual(migration["status"], "succeeded")
        self.assertEqual(scope_migration["status"], "succeeded")
        self.assertEqual(project["discovery_scope"], "context")
        self.assertEqual(snapshot["discovery_scope"], "context")
        self.assertTrue({"cli_clients", "cli_pairing_challenges", "cli_sessions", "cli_auth_audit"} <= tables)
        self.assertTrue({"project_id", "project_snapshot_id", "activation_state"} <= source_columns)
        self.assertTrue({"project_id", "project_snapshot_id", "activation_state"} <= chunk_columns)

    def test_v10_migration_is_idempotent(self) -> None:
        self._create_v9_contract_fixture()
        from backend.app.core.database import connect
        from backend.app.core.migrations import _migration_010_odin_release_contracts, run_migrations

        run_migrations()
        with connect() as conn:
            _migration_010_odin_release_contracts(conn)
            count = conn.execute("SELECT COUNT(*) AS total FROM project_snapshot_sources").fetchone()["total"]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
