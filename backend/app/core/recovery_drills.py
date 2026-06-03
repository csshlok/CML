from backend.app.core.database import connect
from backend.app.core.generation_recovery import recover_interrupted_generations
from backend.app.core.startup_repair import startup_repair_summary
from backend.app.core.startup_status import startup_status_staleness


def startup_recovery_drills(*, apply_recovery: bool = False, stale_timeout_seconds: int = 30) -> dict:
    summary = startup_repair_summary(apply_recovery=apply_recovery)
    staleness = startup_status_staleness(timeout_seconds=stale_timeout_seconds)
    generation_counts_before = _generation_counts()
    generation_recovered = recover_interrupted_generations() if apply_recovery else 0
    generation_counts_after = _generation_counts()
    return {
        "apply_recovery": apply_recovery,
        "stale_startup_phase": staleness,
        "interrupted_migrations": summary.get("interrupted_migrations", []),
        "interrupted_jobs": summary.get("interrupted_jobs", {}),
        "generation_counts_before": generation_counts_before,
        "generation_counts_after": generation_counts_after,
        "generations_recovered": generation_recovered,
        "issues": summary.get("issues", []),
        "passes_drill": (
            not staleness.get("stale")
            and not summary.get("interrupted_migrations")
            and not generation_counts_after.get("in_flight", 0)
            and not summary.get("issues")
        ),
    }


def _generation_counts() -> dict[str, int]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT state, COUNT(*) AS count
            FROM chat_generations
            GROUP BY state
            """
        ).fetchall()
    return {str(row["state"]): int(row["count"]) for row in rows}
