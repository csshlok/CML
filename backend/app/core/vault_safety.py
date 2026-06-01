import shutil
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.core.database import connect, utc_now


def vault_safety_status(*, create_backup: bool = False) -> dict:
    settings = get_settings()
    database_path = settings.database_path
    backup_path = None
    integrity_rows: list[str] = []
    wal_checkpoint = "not-run"
    with connect() as conn:
        integrity_rows = [row[0] for row in conn.execute("PRAGMA integrity_check").fetchall()]
        checkpoint = conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        wal_checkpoint = ",".join(str(value) for value in checkpoint) if checkpoint else "ok"
    if create_backup:
        backup_path = _create_sqlite_backup(database_path)
    return {
        "database_path": str(database_path),
        "integrity_ok": integrity_rows == ["ok"],
        "integrity_result": integrity_rows,
        "wal_checkpoint": wal_checkpoint,
        "backup_path": str(backup_path) if backup_path else None,
        "created_at": utc_now(),
    }


def _create_sqlite_backup(database_path: Path) -> Path:
    settings = get_settings()
    backup_dir = settings.data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().replace(":", "-").replace("+", "_")
    target = backup_dir / f"vault-{stamp}.sqlite3"
    if not database_path.exists():
        raise FileNotFoundError(f"Database does not exist: {database_path}")
    shutil.copy2(database_path, target)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{database_path}{suffix}")
        if sidecar.exists():
            shutil.copy2(sidecar, Path(f"{target}{suffix}"))
    return target
