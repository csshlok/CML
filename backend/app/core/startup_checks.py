from backend.app.core.database import connect


class StartupCheckError(RuntimeError):
    pass


def verify_sqlite_integrity() -> None:
    with connect() as conn:
        rows = conn.execute("PRAGMA integrity_check").fetchall()
    values = [row[0] for row in rows]
    if values != ["ok"]:
        detail = "; ".join(str(value) for value in values[:10])
        raise StartupCheckError(f"SQLite integrity check failed: {detail}")


def verify_schema_version() -> None:
    required_tables = {
        "vaults",
        "clusters",
        "sources",
        "source_pages",
        "source_chunks",
        "chat_sessions",
        "chat_messages",
        "app_jobs",
        "vault_security_metadata",
        "encrypted_content",
    }
    with connect() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    names = {row["name"] for row in rows}
    missing = sorted(required_tables - names)
    if missing:
        raise StartupCheckError(f"Database schema is missing required tables: {', '.join(missing)}")


def run_startup_checks() -> None:
    verify_sqlite_integrity()
    verify_schema_version()
