from backend.app.core.database import connect, utc_now


def recover_interrupted_generations() -> int:
    now = utc_now()
    with connect() as conn:
        result = conn.execute(
            """
            UPDATE chat_generations
            SET state = 'retriable',
                error = CASE
                    WHEN error = '' THEN 'Generation was interrupted by backend restart.'
                    ELSE error
                END,
                updated_at = ?
            WHERE state = 'in_flight'
            """,
            (now,),
        )
        return int(result.rowcount or 0)
