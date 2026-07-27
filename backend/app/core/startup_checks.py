from backend.app.core.database import connect


class StartupCheckError(RuntimeError):
    pass


def verify_sqlite_integrity(*, full: bool = True) -> None:
    with connect() as conn:
        pragma = "integrity_check" if full else "quick_check"
        rows = conn.execute(f"PRAGMA {pragma}").fetchall()
    values = [row[0] for row in rows]
    if values != ["ok"]:
        detail = "; ".join(str(value) for value in values[:10])
        check_name = "integrity check" if full else "quick check"
        raise StartupCheckError(f"SQLite {check_name} failed: {detail}")


def verify_schema_version() -> None:
    required_tables = {
        "vaults",
        "clusters",
        "sources",
        "source_pages",
        "source_chunks",
        "chat_sessions",
        "chat_messages",
        "temporal_facts",
        "temporal_fact_session_state",
        "atomic_memory_facts",
        "atomic_memory_source_units",
        "atomic_memory_session_state",
        "atomic_memory_semantic_state",
        "temporal_fact_reviews",
        "app_jobs",
        "vault_security_metadata",
        "encrypted_content",
        "derived_state_publications",
        "derived_state_staged_artifacts",
        "source_quarantine_records",
        "reconciliation_runs",
        "reconciliation_items",
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
