import ipaddress

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.app.core.cli_auth import (
    CLI_SCOPES,
    CliAuthError,
    approve_pairing,
    cli_auth_me,
    consume_pairing,
    create_pairing_challenge,
    create_session,
    deny_pairing,
    list_clients,
    list_pairing_challenges,
    pairing_status,
    revoke_client,
    rotate_client,
)


router = APIRouter(prefix="/cli-auth", tags=["cli-auth"])


class PairingCreate(BaseModel):
    verifier_hash: str = Field(min_length=64, max_length=64)
    requested_scopes: list[str] = Field(min_length=1, max_length=10)
    requester_name: str = Field(default="Odin CLI", max_length=120)
    executable_fingerprint: str = Field(min_length=64, max_length=64)
    runtime_instance_id: str = Field(min_length=1, max_length=120)


class PairingConsume(BaseModel):
    verifier: str = Field(min_length=32, max_length=240)


class PairingDecision(BaseModel):
    scopes: list[str] = Field(min_length=1, max_length=10)
    allowed_vault_ids: list[str] = Field(min_length=1, max_length=20)


class SessionCreate(BaseModel):
    client_id: str = Field(min_length=1, max_length=160)
    credential: str = Field(min_length=32, max_length=512)
    executable_fingerprint: str = Field(min_length=64, max_length=64)


@router.post("/pairing-challenges")
def pairing_create(payload: PairingCreate, request: Request) -> dict:
    _require_loopback(request)
    return _call(
        create_pairing_challenge,
        verifier_hash=payload.verifier_hash,
        requested_scopes=payload.requested_scopes,
        requester_name=payload.requester_name,
        executable_fingerprint=payload.executable_fingerprint,
        runtime_instance_id=payload.runtime_instance_id,
    )


@router.get("/pairing-challenges/{challenge_id}/status")
def pairing_get_status(challenge_id: str, request: Request) -> dict:
    _require_loopback(request)
    verifier = request.headers.get("x-odin-pairing-verifier", "")
    return _call(pairing_status, challenge_id, verifier)


@router.post("/pairing-challenges/{challenge_id}/consume")
def pairing_consume(challenge_id: str, payload: PairingConsume, request: Request) -> dict:
    _require_loopback(request)
    return _call(consume_pairing, challenge_id, payload.verifier)


@router.get("/pairing-challenges")
def pairing_list(status: str = "pending", limit: int = 50) -> list[dict]:
    return list_pairing_challenges(status=status, limit=limit)


@router.post("/pairing-challenges/{challenge_id}/approve")
def pairing_approve(challenge_id: str, payload: PairingDecision) -> dict:
    return _call(
        approve_pairing,
        challenge_id,
        scopes=payload.scopes,
        allowed_vault_ids=payload.allowed_vault_ids,
    )


@router.post("/pairing-challenges/{challenge_id}/deny")
def pairing_deny(challenge_id: str) -> dict:
    return _call(deny_pairing, challenge_id)


@router.post("/sessions")
def session_create(payload: SessionCreate, request: Request) -> dict:
    _require_loopback(request)
    return _call(
        create_session,
        client_id=payload.client_id,
        credential=payload.credential,
        executable_fingerprint=payload.executable_fingerprint,
    )


@router.get("/me")
def auth_me(request: Request) -> dict:
    context = getattr(request.state, "cli_auth", None)
    if not context:
        raise HTTPException(status_code=401, detail="cli_session_required")
    return cli_auth_me(context)


@router.get("/clients")
def client_list() -> list[dict]:
    return list_clients()


@router.post("/clients/{client_id}/revoke")
def client_revoke(client_id: str) -> dict:
    return _call(revoke_client, client_id)


@router.post("/clients/{client_id}/rotate")
def client_rotate(client_id: str) -> dict:
    return _call(rotate_client, client_id)


@router.get("/scopes")
def scope_list() -> dict:
    return {"scopes": sorted(CLI_SCOPES)}


def _require_loopback(request: Request) -> None:
    host = request.client.host if request.client else ""
    try:
        if not ipaddress.ip_address(host).is_loopback:
            raise HTTPException(status_code=403, detail="loopback_required")
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="loopback_required") from exc


def _call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except CliAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
