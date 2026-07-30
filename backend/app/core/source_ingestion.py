from __future__ import annotations

from dataclasses import dataclass

from backend.app.core.database import utc_now


INGESTION_STAGES = {
    "imported",
    "extracting",
    "searchable",
    "organizing",
    "describing",
    "ready",
    "paused",
    "needs_attention",
}


@dataclass(frozen=True)
class IngestionIdentity:
    source_id: str
    generation: int
    checksum: str

    @property
    def job_suffix(self) -> str:
        return f"g{self.generation}:{self.checksum or 'no-checksum'}"


def source_ingestion_identity(conn, source_id: str) -> IngestionIdentity | None:
    row = conn.execute(
        """
        SELECT id, ingestion_generation, checksum
        FROM sources
        WHERE id = ? AND deleted_at IS NULL
        """,
        (source_id,),
    ).fetchone()
    if row is None:
        return None
    return IngestionIdentity(
        source_id=str(row["id"]),
        generation=max(1, int(row["ingestion_generation"] or 1)),
        checksum=str(row["checksum"] or ""),
    )


def begin_source_ingestion(
    conn,
    *,
    source_id: str,
    detail: str = "Preparing source indexing.",
) -> IngestionIdentity | None:
    now = utc_now()
    conn.execute(
        """
        UPDATE sources
        SET ingestion_generation = ingestion_generation + 1,
            ingestion_stage = 'imported',
            ingestion_error_code = '',
            ingestion_status_detail = ?,
            ingestion_updated_at = ?
        WHERE id = ? AND deleted_at IS NULL
        """,
        (detail[:240], now, source_id),
    )
    return source_ingestion_identity(conn, source_id)


def publish_source_ingestion_stage(
    conn,
    *,
    source_id: str,
    stage: str,
    generation: int | None = None,
    detail: str = "",
    error_code: str = "",
) -> bool:
    normalized_stage = str(stage).strip().casefold()
    if normalized_stage not in INGESTION_STAGES:
        raise ValueError(f"invalid_source_ingestion_stage:{normalized_stage}")
    params: list[object] = [
        normalized_stage,
        str(error_code or "")[:96],
        str(detail or "")[:240],
        utc_now(),
        source_id,
    ]
    generation_clause = ""
    if generation is not None:
        generation_clause = " AND ingestion_generation = ?"
        params.append(max(1, int(generation)))
    result = conn.execute(
        f"""
        UPDATE sources
        SET ingestion_stage = ?,
            ingestion_error_code = ?,
            ingestion_status_detail = ?,
            ingestion_updated_at = ?
        WHERE id = ? AND deleted_at IS NULL{generation_clause}
        """,
        params,
    )
    return result.rowcount == 1
