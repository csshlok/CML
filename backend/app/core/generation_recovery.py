from datetime import UTC, datetime, timedelta

from backend.app.core.database import connect, utc_now


def recover_interrupted_generations(*, stale_after_seconds: int = 30) -> int:
    now = utc_now()
    cutoff = (datetime.now(UTC) - timedelta(seconds=max(0, stale_after_seconds))).isoformat()
    with connect() as conn:
        result = conn.execute(
            """
            UPDATE chat_generations
            SET state = 'retriable', lease_owner = '',
                error = CASE
                    WHEN error = '' THEN 'Generation was interrupted by backend restart.'
                    ELSE error
                END,
                updated_at = ?
            WHERE state = 'in_flight'
              AND COALESCE(heartbeat_at, updated_at, created_at) <= ?
            """,
            (now, cutoff),
        )
        return int(result.rowcount or 0)
