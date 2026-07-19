from fastapi import APIRouter, HTTPException, Query

from backend.app.core.database import connect
from backend.app.core.retrieval_telemetry import retrieval_packing_diagnostics
from backend.app.core.temporal_facts import (
    correct_temporal_fact,
    list_reviewable_temporal_facts,
    retract_temporal_fact,
)
from backend.app.schemas import (
    RetrievalPackingDiagnosticsRead,
    TemporalFactCorrectionRequest,
    TemporalFactRead,
    TemporalFactRetractionRequest,
)

router = APIRouter(prefix="/memory", tags=["memory"])


def _require_vault(conn, vault_id: str) -> None:
    if conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="Vault not found")


@router.get("/facts", response_model=list[TemporalFactRead])
def list_temporal_facts(
    vault_id: str,
    cluster_id: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
) -> list[dict]:
    with connect() as conn:
        _require_vault(conn, vault_id)
        return list_reviewable_temporal_facts(
            conn, vault_id=vault_id, cluster_id=cluster_id, limit=limit
        )


@router.post("/facts/{fact_id}/correct", response_model=TemporalFactRead)
def correct_fact(fact_id: str, payload: TemporalFactCorrectionRequest) -> dict:
    with connect() as conn:
        _require_vault(conn, payload.vault_id)
        try:
            return correct_temporal_fact(
                conn,
                vault_id=payload.vault_id,
                fact_id=fact_id,
                object_text=payload.object_text,
                note=payload.note,
                valid_from=payload.valid_from,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Memory fact not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/facts/{fact_id}/retract", response_model=TemporalFactRead)
def retract_fact(fact_id: str, payload: TemporalFactRetractionRequest) -> dict:
    with connect() as conn:
        _require_vault(conn, payload.vault_id)
        try:
            return retract_temporal_fact(
                conn, vault_id=payload.vault_id, fact_id=fact_id, note=payload.note
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Memory fact not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/retrieval-efficiency", response_model=RetrievalPackingDiagnosticsRead)
def get_retrieval_efficiency(vault_id: str) -> dict:
    with connect() as conn:
        _require_vault(conn, vault_id)
        return retrieval_packing_diagnostics(conn, vault_id=vault_id)
