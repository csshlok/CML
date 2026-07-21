from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill and inspect content-free atomic-memory coverage for local vaults."
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--vault-id", action="append", default=[])
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Initialize current schema and regenerate atomic memory before reporting.",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _table_names(database: Path) -> set[str]:
    uri = database.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        return {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        conn.close()


def _preflight_summary(database: Path, tables: set[str]) -> dict:
    uri = database.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        return {
            "vault_count": conn.execute("SELECT COUNT(*) FROM vaults").fetchone()[0]
            if "vaults" in tables else 0,
            "session_count": conn.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0]
            if "chat_sessions" in tables else 0,
            "message_count": conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
            if "chat_messages" in tables else 0,
            "atomic_schema_ready": {
                "atomic_memory_facts",
                "atomic_memory_source_units",
                "atomic_memory_session_state",
            }.issubset(tables),
        }
    finally:
        conn.close()


def main() -> int:
    args = parse_args()
    database = args.database.resolve()
    if not database.is_file():
        raise FileNotFoundError(f"Database does not exist: {database}")
    tables_before = _table_names(database)
    required = {
        "atomic_memory_facts",
        "atomic_memory_source_units",
        "atomic_memory_session_state",
    }
    if not args.backfill and not required.issubset(tables_before):
        print(
            json.dumps(
                {
                    "database": str(database),
                    "backfill_performed": False,
                    **_preflight_summary(database, tables_before),
                    "next_action": "Rerun with --backfill to initialize and compile atomic memory.",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    os.environ["CML_DATABASE_PATH"] = str(database)
    os.environ["CML_DATA_DIR"] = str(database.parent)
    from backend.app.core.atomic_memory_store import atomic_memory_coverage_report
    from backend.app.core.config import get_settings
    from backend.app.core.database import connect, init_db
    from backend.app.core.temporal_facts import sync_chat_session_temporal_facts
    from backend.app.core.vault_safety import vault_safety_status

    get_settings.cache_clear()
    safety = None
    if args.backfill:
        safety = vault_safety_status(create_backup=True)
        if not safety["integrity_ok"]:
            raise RuntimeError("Database integrity check failed; backfill was not started")
        init_db()
    reports: list[dict] = []
    with connect() as conn:
        vault_rows = conn.execute("SELECT id FROM vaults ORDER BY created_at, id").fetchall()
        requested = set(args.vault_id)
        vault_ids = [
            str(row["id"])
            for row in vault_rows
            if not requested or str(row["id"]) in requested
        ]
        if requested - set(vault_ids):
            raise ValueError("One or more requested vault IDs were not found")
        if args.backfill:
            for vault_id in vault_ids:
                sessions = conn.execute(
                    "SELECT id FROM chat_sessions WHERE vault_id = ? ORDER BY created_at, id",
                    (vault_id,),
                ).fetchall()
                for session in sessions:
                    session_id = str(session["id"])
                    messages = conn.execute(
                        """
                        SELECT * FROM chat_messages WHERE session_id = ?
                        ORDER BY created_at, rowid
                        """,
                        (session_id,),
                    ).fetchall()
                    sync_chat_session_temporal_facts(
                        conn,
                        vault_id=vault_id,
                        session_id=session_id,
                        messages=messages,
                    )
        reports = [
            atomic_memory_coverage_report(conn, vault_id=vault_id)
            for vault_id in vault_ids
        ]
    payload = {
        "database": str(database),
        "backfill_performed": bool(args.backfill),
        "backup_path": safety["backup_path"] if safety else None,
        "vault_count": len(reports),
        "reports": reports,
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
