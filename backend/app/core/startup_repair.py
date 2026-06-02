from backend.app.core.background_jobs import recover_interrupted_jobs
from backend.app.core.database import connect
from backend.app.core.startup_checks import verify_schema_version, verify_sqlite_integrity
from backend.app.core.startup_status import read_startup_status
from backend.app.core.vector_maintenance import vector_repair_plan


def startup_repair_summary(*, apply_recovery: bool = False) -> dict:
    summary = {
        "startup_status": read_startup_status(),
        "database_integrity": "unknown",
        "schema": "unknown",
        "interrupted_jobs": {},
        "vector_repair": {},
        "safe_degraded_mode": False,
        "issues": [],
    }
    try:
        verify_sqlite_integrity()
        verify_schema_version()
        summary["database_integrity"] = "ok"
        summary["schema"] = "ok"
    except Exception as exc:
        summary["database_integrity"] = "failed"
        summary["schema"] = "failed"
        summary["safe_degraded_mode"] = True
        summary["issues"].append(f"database_or_schema_check_failed: {exc}")
        return summary

    try:
        if apply_recovery:
            summary["interrupted_jobs"] = recover_interrupted_jobs()
        else:
            summary["interrupted_jobs"] = _interrupted_job_counts()
    except Exception as exc:
        summary["safe_degraded_mode"] = True
        summary["issues"].append(f"job_recovery_failed: {exc}")

    try:
        summary["vector_repair"] = vector_repair_plan()
    except Exception as exc:
        summary["issues"].append(f"vector_repair_plan_failed: {exc}")

    return summary


def _interrupted_job_counts() -> dict:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT restart_policy, COUNT(*) AS count
            FROM app_jobs
            WHERE status = 'running'
            GROUP BY restart_policy
            """
        ).fetchall()
    return {str(row["restart_policy"] or "unknown"): int(row["count"]) for row in rows}
