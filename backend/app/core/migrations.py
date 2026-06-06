from collections.abc import Callable

from backend.app.core.database import connect, utc_now

SCHEMA_VERSION = 2


class MigrationError(RuntimeError):
    pass


Migration = Callable[[object], None]


def _migration_001_baseline(conn) -> None:
    # init_db() owns the clean-slate schema today. This baseline records that
    # migration tracking exists before public user data ships.
    conn.execute("SELECT 1")


def _migration_002_vault_security_metadata(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vault_security_metadata (
            vault_id TEXT PRIMARY KEY,
            security_version INTEGER NOT NULL,
            kdf_algorithm TEXT NOT NULL,
            kdf_params_json TEXT NOT NULL,
            passphrase_salt TEXT NOT NULL,
            passphrase_wrapped_vmk TEXT NOT NULL,
            recovery_salt TEXT NOT NULL,
            recovery_wrapped_vmk TEXT NOT NULL,
            unlock_mode TEXT NOT NULL DEFAULT 'convenience',
            pin_enabled INTEGER NOT NULL DEFAULT 0,
            pin_salt TEXT NOT NULL DEFAULT '',
            pin_wrapped_unlock_secret TEXT NOT NULL DEFAULT '',
            active_derived_state_tuple TEXT NOT NULL DEFAULT '{}',
            previous_verified_tuple TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vault_security_unlock_mode ON vault_security_metadata(unlock_mode)")


MIGRATIONS: dict[int, Migration] = {
    1: _migration_001_baseline,
    2: _migration_002_vault_security_metadata,
}


def run_migrations() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                error TEXT NOT NULL DEFAULT ''
            )
            """
        )
        running = conn.execute(
            "SELECT version, name FROM schema_migrations WHERE status = 'running' ORDER BY version DESC LIMIT 1"
        ).fetchone()
        if running is not None:
            raise MigrationError(
                f"Previous migration did not finish: {running['version']} {running['name']}"
            )
        current_row = conn.execute(
            "SELECT MAX(version) AS version FROM schema_migrations WHERE status = 'succeeded'"
        ).fetchone()
        current_version = int(current_row["version"] or 0)
        for version in range(current_version + 1, SCHEMA_VERSION + 1):
            migration = MIGRATIONS.get(version)
            if migration is None:
                raise MigrationError(f"No migration registered for schema version {version}")
            name = migration.__name__.removeprefix("_migration_")
            started_at = utc_now()
            conn.execute(
                """
                INSERT INTO schema_migrations (version, name, started_at, status)
                VALUES (?, ?, ?, 'running')
                """,
                (version, name, started_at),
            )
            try:
                migration(conn)
            except Exception as exc:
                conn.execute(
                    """
                    UPDATE schema_migrations
                    SET status = 'failed', finished_at = ?, error = ?
                    WHERE version = ?
                    """,
                    (utc_now(), str(exc)[:1000], version),
                )
                raise MigrationError(f"Migration {version} failed: {exc}") from exc
            conn.execute(
                """
                UPDATE schema_migrations
                SET status = 'succeeded', finished_at = ?, error = ''
                WHERE version = ?
                """,
                (utc_now(), version),
            )
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
