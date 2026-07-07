import json
import hashlib
import secrets
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Query, Request

from backend.app.api.routes.sources import source_from_row
from backend.app.core.bridge_security import (
    APPROVAL_DELIVERY_SECONDS,
    APPROVAL_PENDING_SECONDS,
    APPROVAL_RATE_LIMIT_GLOBAL,
    APPROVAL_RATE_LIMIT_PER_FINGERPRINT,
    APPROVAL_RATE_WINDOW_SECONDS,
    CLIENT_RATE_LIMIT,
    CLIENT_RATE_WINDOW_SECONDS,
    GLOBAL_RATE_LIMIT,
    BridgeRateLimitError,
    compact_bridge_tables,
    enforce_rate_limit,
    inspect_client_identity,
    is_expired,
    iso_after,
    load_secure_json,
    metadata_fingerprint,
    store_secure_json,
)
from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.core.background_jobs import enqueue_job
from backend.app.core.cluster_bundle import build_cluster_bundle_context
from backend.app.core.context_packets import build_bridge_context_packet, render_context_packet
from backend.app.core.embeddings import content_hash
from backend.app.core.encrypted_storage import (
    chunk_from_encrypted_row,
    get_encrypted_text,
    is_vault_secured,
    page_from_encrypted_row,
    plaintext_column_for_text,
    source_from_encrypted_row,
    store_source_content_fields,
)
from backend.app.core.memory_card import summarize_text
from backend.app.core.context_memory import (
    apply_bridge_quality_to_source,
    classify_external_response_quality,
    persist_bridge_writeback_review,
    rebuild_source_memory,
    set_bridge_writeback_review_approval,
)
from backend.app.core.retrieval_trust import sensitive_query_categories
from backend.app.core.unlock_state import current_unlock_state, security_gate_active
from backend.app.schemas import (
    BridgeApprovalDecision,
    BridgeApprovalRequestCreate,
    BridgeApprovalRequestCreateResponse,
    BridgeApprovalRequestPollResponse,
    BridgeApprovalRequestRead,
    BridgeAuditEventRead,
    BridgeArtifactCapture,
    BridgeContextExpandRequest,
    BridgeContextExpandResponse,
    BridgeContextRequest,
    BridgeContextResponse,
    BridgeCaptureResponse,
    BridgeCaptureListItem,
    BridgeClientCreate,
    BridgeClientCreateResponse,
    BridgeClientRead,
    BridgeClientUpdate,
    BridgeExternalTurnCapture,
    BridgeRequestRead,
    BridgeSettingsUpdate,
    BridgeStatus,
    BridgeTokenRotationRead,
    BridgeWritebackReviewDecision,
    BridgeWritebackReviewRead,
)

router = APIRouter(prefix="/bridge", tags=["bridge"])


@router.get("/status", response_model=BridgeStatus)
def bridge_status() -> dict[str, str | bool]:
    with connect() as conn:
        return _bridge_status_from_conn(conn)


@router.patch("/settings", response_model=BridgeStatus)
def update_bridge_settings(payload: BridgeSettingsUpdate) -> dict:
    updates = payload.model_dump(exclude_unset=True)
    with connect() as conn:
        settings = _get_bridge_settings(conn)
        next_settings = {**settings, **updates}
        rotating = bool(updates.get("rotate_token") or not next_settings.get("bridge_token"))
        previous_token = str(settings.get("bridge_token") or "")
        if rotating:
            next_settings["bridge_token"] = secrets.token_urlsafe(24)
        now = utc_now()
        _ensure_bridge_settings(conn)
        conn.execute(
            """
            UPDATE bridge_settings
            SET enabled = ?,
                allowed_vault_ids = ?,
                allowed_cluster_ids = ?,
                allow_raw_snippets = ?,
                allow_style_profile = ?,
                bridge_token = ?,
                updated_at = ?
            WHERE id = 'default'
            """,
            (
                1 if next_settings["enabled"] else 0,
                json.dumps(next_settings["allowed_vault_ids"]),
                json.dumps(next_settings["allowed_cluster_ids"]),
                1 if next_settings["allow_raw_snippets"] else 0,
                1 if next_settings["allow_cluster_profile"] else 0,
                next_settings["bridge_token"],
                now,
            ),
        )
        if rotating:
            conn.execute(
                """
                INSERT INTO bridge_token_rotations (
                    id, rotated_at, reason, previous_token_hash, new_token_hash
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    f"bridge-token-rotation-{uuid4()}",
                    now,
                    "manual_rotation" if updates.get("rotate_token") else "initial_token_created",
                    _token_hash(previous_token),
                    _token_hash(next_settings["bridge_token"]),
                ),
            )
        return _bridge_status_from_conn(conn)


@router.post("/approval-requests", response_model=BridgeApprovalRequestCreateResponse)
def create_bridge_approval_request(payload: BridgeApprovalRequestCreate, request: Request) -> dict:
    settings = _get_bridge_settings()
    if not settings["enabled"]:
        raise HTTPException(status_code=403, detail="bridge_disabled")
    unlock = current_unlock_state()
    identity = inspect_client_identity(payload.claimed_name, payload.executable_path)
    request_id = f"bridge-approval-{uuid4()}"
    approval_code = secrets.token_urlsafe(24)
    now = utc_now()
    expires_at = iso_after(APPROVAL_PENDING_SECONDS)
    with connect() as conn:
        requested_vault_ids = _existing_vault_ids(conn, payload.requested_vault_ids)
        requested_cluster_ids = _existing_cluster_ids(conn, payload.requested_cluster_ids)
        vault_id = _approval_vault_id(requested_vault_ids, unlock.get("vault_id"))
        if not vault_id:
            raise HTTPException(status_code=409, detail="no_active_vault")
        requested = {
            "claimed_name": identity["claimed_name"],
            "requested_vault_ids": requested_vault_ids,
            "requested_cluster_ids": requested_cluster_ids,
            "allow_raw_snippets": bool(payload.allow_raw_snippets),
            "allow_cluster_profile": bool(payload.allow_cluster_profile),
            "executable_path_claim": identity["executable_path_claim"],
            "observed_executable_path": identity["observed_executable_path"],
            "publisher_name": identity["publisher_name"],
            "signature_status": identity["signature_status"],
            "signature_detail": identity["signature_detail"],
            "verified_identity": bool(identity["verified_identity"]),
            "verified_identity_label": identity["verified_identity_label"],
            "requested_by_host": request.client.host if request.client else "",
            "detail": "",
        }
        fingerprint_hash = metadata_fingerprint(
            {
                "claimed_name": requested["claimed_name"],
                "requested_vault_ids": requested["requested_vault_ids"],
                "requested_cluster_ids": requested["requested_cluster_ids"],
                "executable_path_claim": requested["executable_path_claim"],
                "observed_executable_path": requested["observed_executable_path"],
            }
        )
        try:
            enforce_rate_limit(
                conn,
                scope_type="approval_fingerprint",
                scope_id=fingerprint_hash,
                bucket="bridge_approval_requests",
                limit=APPROVAL_RATE_LIMIT_PER_FINGERPRINT,
                window_seconds=APPROVAL_RATE_WINDOW_SECONDS,
            )
            enforce_rate_limit(
                conn,
                scope_type="approval_global",
                scope_id="global",
                bucket="bridge_approval_requests",
                limit=APPROVAL_RATE_LIMIT_GLOBAL,
                window_seconds=APPROVAL_RATE_WINDOW_SECONDS,
            )
        except BridgeRateLimitError as exc:
            _insert_bridge_audit_event(
                conn,
                vault_id=vault_id,
                client_id=None,
                approval_request_id=None,
                event_type="approval_request_rate_limited",
                detail={"claimed_name": requested["claimed_name"], "fingerprint_hash": fingerprint_hash},
            )
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        conn.execute(
            """
            INSERT INTO bridge_approval_requests (
                id, vault_id, status, fingerprint_hash, details_json, approval_code_hash,
                requested_at, expires_at, decided_at, delivered_at, client_id, updated_at
            )
            VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, NULL, NULL, NULL, ?)
            """,
            (
                request_id,
                vault_id,
                fingerprint_hash,
                store_secure_json(
                    conn,
                    vault_id=vault_id,
                    entity_type="bridge_approval_request",
                    entity_id=request_id,
                    field_name="details_json",
                    payload=requested,
                    now=now,
                ),
                _token_hash(approval_code),
                now,
                expires_at,
                now,
            ),
        )
        _insert_bridge_audit_event(
            conn,
            vault_id=vault_id,
            client_id=None,
            approval_request_id=request_id,
            event_type="approval_request_created",
            detail=requested,
        )
        compact_bridge_tables(conn)
    return {
        "request_id": request_id,
        "status": "pending",
        "expires_at": expires_at,
        "poll_code": approval_code,
        "detail": "Approval request created. Keep polling until the CML app approves or rejects it.",
    }


@router.get("/approval-requests/{request_id}/status", response_model=BridgeApprovalRequestPollResponse)
def poll_bridge_approval_request(
    request_id: str,
    approval_code: str = Query(min_length=8, max_length=512),
) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM bridge_approval_requests WHERE id = ?",
            (request_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="bridge_approval_request_not_found")
        if not _token_hash_matches(str(row["approval_code_hash"]), approval_code):
            raise HTTPException(status_code=401, detail="bridge_approval_code_invalid")
        if row["status"] == "pending" and is_expired(row["expires_at"]):
            conn.execute(
                """
                UPDATE bridge_approval_requests
                SET status = 'expired', updated_at = ?, decided_at = ?
                WHERE id = ?
                """,
                (utc_now(), utc_now(), request_id),
            )
            row = conn.execute("SELECT * FROM bridge_approval_requests WHERE id = ?", (request_id,)).fetchone()
        details = _approval_request_details(conn, row)
        response = {
            "request_id": request_id,
            "status": row["status"],
            "expires_at": row["expires_at"],
            "client_id": row["client_id"],
            "token": None,
            "token_available": False,
            "detail": details.get("detail", ""),
        }
        if row["status"] == "approved" and row["delivered_at"] is None:
            token = _pop_approval_delivery_token(conn, row)
            if token:
                response["token"] = token
                response["token_available"] = True
                conn.execute(
                    """
                    UPDATE bridge_approval_requests
                    SET delivered_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (utc_now(), utc_now(), request_id),
                )
        compact_bridge_tables(conn)
    return response


@router.get("/approval-requests", response_model=list[BridgeApprovalRequestRead])
def list_bridge_approval_requests(limit: int = 100, offset: int = 0) -> list[dict]:
    bounded_limit = max(1, min(limit, 200))
    bounded_offset = max(offset, 0)
    with connect() as conn:
        _expire_pending_approval_requests(conn)
        rows = conn.execute(
            """
            SELECT * FROM bridge_approval_requests
            ORDER BY
                CASE status WHEN 'pending' THEN 0 ELSE 1 END,
                updated_at DESC,
                id DESC
            LIMIT ? OFFSET ?
            """
            ,
            (bounded_limit, bounded_offset),
        ).fetchall()
        return [_approval_request_from_row(conn, row) for row in rows]


@router.post("/approval-requests/{request_id}/approve", response_model=BridgeClientCreateResponse)
def approve_bridge_approval_request(request_id: str, payload: BridgeApprovalDecision) -> dict:
    now = utc_now()
    with connect() as conn:
        _expire_pending_approval_requests(conn)
        row = conn.execute("SELECT * FROM bridge_approval_requests WHERE id = ?", (request_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="bridge_approval_request_not_found")
        if row["status"] != "pending":
            raise HTTPException(status_code=409, detail="bridge_approval_request_not_pending")
        if is_expired(row["expires_at"]):
            conn.execute(
                """
                UPDATE bridge_approval_requests
                SET status = 'expired', decided_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, request_id),
            )
            raise HTTPException(status_code=409, detail="bridge_approval_request_expired")
        details = _approval_request_details(conn, row)
        token = secrets.token_urlsafe(24)
        allowed_vault_ids = payload.allowed_vault_ids if payload.allowed_vault_ids is not None else details["requested_vault_ids"]
        allowed_cluster_ids = payload.allowed_cluster_ids if payload.allowed_cluster_ids is not None else details["requested_cluster_ids"]
        allow_raw_snippets = (
            bool(payload.allow_raw_snippets)
            if payload.allow_raw_snippets is not None
            else bool(details["allow_raw_snippets"])
        )
        allow_cluster_profile = (
            bool(payload.allow_cluster_profile)
            if payload.allow_cluster_profile is not None
            else bool(details["allow_cluster_profile"])
        )
        client_id = f"bridge-client-{uuid4()}"
        metadata = {
            "executable_path_claim": details["executable_path_claim"],
            "observed_executable_path": details["observed_executable_path"],
            "publisher_name": details["publisher_name"],
            "signature_status": details["signature_status"],
            "signature_detail": details["signature_detail"],
            "verified_identity": bool(details["verified_identity"]),
            "verified_identity_label": details["verified_identity_label"],
        }
        client_row = {
            "id": client_id,
            "name": details["claimed_name"],
            "token_hash": _token_hash(token),
            "enabled": 1,
            "approval_vault_id": row["vault_id"],
            "allowed_vault_ids": json.dumps(_existing_vault_ids(conn, allowed_vault_ids)),
            "allowed_cluster_ids": json.dumps(_existing_cluster_ids(conn, allowed_cluster_ids)),
            "allow_raw_snippets": 1 if allow_raw_snippets else 0,
            "allow_style_profile": 1 if allow_cluster_profile else 0,
            "metadata_json": store_secure_json(
                conn,
                vault_id=row["vault_id"],
                entity_type="bridge_client",
                entity_id=client_id,
                field_name="metadata_json",
                payload=metadata,
                now=now,
            ),
            "approval_request_id": request_id,
            "approved_at": now,
            "revoked_at": None,
            "last_request_at": None,
            "request_count_total": 0,
            "response_bytes_total": 0,
            "created_at": now,
            "updated_at": now,
        }
        conn.execute(
            """
            INSERT INTO bridge_clients (
                id, name, token_hash, enabled, approval_vault_id, allowed_vault_ids,
                allowed_cluster_ids, allow_raw_snippets, allow_style_profile,
                metadata_json, approval_request_id, approved_at, revoked_at, last_request_at,
                request_count_total, response_bytes_total, created_at, updated_at
            )
            VALUES (
                :id, :name, :token_hash, :enabled, :approval_vault_id, :allowed_vault_ids,
                :allowed_cluster_ids, :allow_raw_snippets, :allow_style_profile,
                :metadata_json, :approval_request_id, :approved_at, :revoked_at, :last_request_at,
                :request_count_total, :response_bytes_total, :created_at, :updated_at
            )
            """,
            client_row,
        )
        details["detail"] = str(payload.detail or "").strip()
        conn.execute(
            """
            UPDATE bridge_approval_requests
            SET status = 'approved',
                decided_at = ?,
                expires_at = ?,
                client_id = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (now, iso_after(APPROVAL_DELIVERY_SECONDS), client_id, now, request_id),
        )
        sanitized_details = store_secure_json(
            conn,
            vault_id=row["vault_id"],
            entity_type="bridge_approval_request",
            entity_id=request_id,
            field_name="details_json",
            payload=details,
            now=now,
        )
        conn.execute(
            "UPDATE bridge_approval_requests SET details_json = ?, updated_at = ? WHERE id = ?",
            (sanitized_details, now, request_id),
        )
        _store_approval_delivery_token(conn, row["vault_id"], request_id, token, now=now)
        _insert_bridge_audit_event(
            conn,
            vault_id=row["vault_id"],
            client_id=client_id,
            approval_request_id=request_id,
            event_type="approval_request_approved",
            detail={
                "claimed_name": details["claimed_name"],
                "allowed_vault_ids": json.loads(client_row["allowed_vault_ids"]),
                "allowed_cluster_ids": json.loads(client_row["allowed_cluster_ids"]),
            },
        )
        compact_bridge_tables(conn)
        return {**_bridge_client_from_mapping(client_row, metadata=metadata), "token": token}


@router.post("/approval-requests/{request_id}/reject", response_model=BridgeApprovalRequestRead)
def reject_bridge_approval_request(request_id: str, payload: BridgeApprovalDecision) -> dict:
    now = utc_now()
    with connect() as conn:
        _expire_pending_approval_requests(conn)
        row = conn.execute("SELECT * FROM bridge_approval_requests WHERE id = ?", (request_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="bridge_approval_request_not_found")
        if row["status"] != "pending":
            raise HTTPException(status_code=409, detail="bridge_approval_request_not_pending")
        details = _approval_request_details(conn, row)
        details["detail"] = str(payload.detail or "").strip()
        conn.execute(
            """
            UPDATE bridge_approval_requests
            SET status = 'rejected', decided_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, now, request_id),
        )
        sanitized_details = store_secure_json(
            conn,
            vault_id=row["vault_id"],
            entity_type="bridge_approval_request",
            entity_id=request_id,
            field_name="details_json",
            payload=details,
            now=now,
        )
        conn.execute(
            "UPDATE bridge_approval_requests SET details_json = ?, updated_at = ? WHERE id = ?",
            (sanitized_details, now, request_id),
        )
        _insert_bridge_audit_event(
            conn,
            vault_id=row["vault_id"],
            client_id=None,
            approval_request_id=request_id,
            event_type="approval_request_rejected",
            detail={"claimed_name": details["claimed_name"], "detail": details["detail"]},
        )
        compact_bridge_tables(conn)
        updated = conn.execute("SELECT * FROM bridge_approval_requests WHERE id = ?", (request_id,)).fetchone()
        return _approval_request_from_row(conn, updated)


@router.get("/audit-events", response_model=list[BridgeAuditEventRead])
def list_bridge_audit_events(limit: int = 100, offset: int = 0) -> list[dict]:
    bounded_limit = max(1, min(limit, 200))
    bounded_offset = max(offset, 0)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM bridge_audit_events
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """
            ,
            (bounded_limit, bounded_offset),
        ).fetchall()
        return [_bridge_audit_event_from_row(conn, row) for row in rows]


@router.post("/context", response_model=BridgeContextResponse)
def build_context(payload: BridgeContextRequest, x_cml_bridge_token: str | None = Header(default=None)) -> dict:
    settings, client_permissions, auth_mode = _authorize_bridge_runtime_token(x_cml_bridge_token)
    permissions = client_permissions or settings

    with connect() as conn:
        if payload.cluster_id and permissions["allowed_cluster_ids"] and payload.cluster_id not in permissions["allowed_cluster_ids"]:
            _log_bridge_request(payload, mode_suffix="cluster_not_allowed", client_id=client_permissions["id"] if client_permissions else None)
            raise HTTPException(status_code=403, detail="cluster_not_allowed")
        try:
            vault_id = _resolve_bridge_vault_id(
                conn,
                requested_vault_id=payload.vault_id,
                requested_cluster_id=payload.cluster_id,
                permissions=permissions,
            )
        except HTTPException as exc:
            if exc.detail in {"no_active_vault", "vault_not_found", "cluster_not_found"}:
                _log_bridge_request(payload, mode_suffix=str(exc.detail), client_id=client_permissions["id"] if client_permissions else None)
            raise

        if permissions["allowed_vault_ids"] and vault_id not in permissions["allowed_vault_ids"]:
            _log_bridge_request(payload, mode_suffix="vault_not_allowed", client_id=client_permissions["id"] if client_permissions else None)
            raise HTTPException(status_code=403, detail="vault_not_allowed")

        if payload.cluster_id:
            cluster = conn.execute(
                "SELECT id FROM clusters WHERE id = ? AND vault_id = ?",
                (payload.cluster_id, vault_id),
            ).fetchone()
            if cluster is None:
                _log_bridge_request(payload, mode_suffix="cluster_not_found", client_id=client_permissions["id"] if client_permissions else None)
                raise HTTPException(status_code=404, detail="cluster_not_found")

    with connect() as conn:
        _enforce_runtime_rate_limits(conn, client_permissions, auth_mode)

    sensitive_categories = sensitive_query_categories(payload.query)
    context_request_id = payload.context_request_id or f"bridge-context-{uuid4()}"
    bundle = build_cluster_bundle_context(
        vault_id=vault_id,
        query=payload.query,
        cluster_id=payload.cluster_id,
        token_budget=payload.limit,
        mode=payload.mode,
    )
    exposed_cluster_profile = (bundle.get("cluster_profile") or {}) if bool(permissions["allow_cluster_profile"]) else {}
    warnings = list(bundle.get("warnings") or [])
    if sensitive_categories:
        warnings.append("Sensitive query categories detected: " + ", ".join(sensitive_categories) + ".")
    ordered_sources = []
    source_ids = [
        str(item.get("source_id") or item.get("id") or "")
        for item in bundle.get("source_snippets") or []
        if str(item.get("source_id") or item.get("id") or "").strip()
    ]
    with connect() as conn:
        source_rows = []
        if source_ids:
            source_rows = conn.execute(
                f"SELECT * FROM sources WHERE vault_id = ? AND id IN ({','.join('?' for _ in source_ids)})",
                [vault_id, *source_ids],
            ).fetchall()
            sources_by_id = {
                row["id"]: _bridge_source_from_row(
                    row,
                    conn=conn,
                    allow_raw_snippets=bool(permissions["allow_raw_snippets"]),
                )
                for row in source_rows
            }
            ordered_sources = [sources_by_id[source_id] for source_id in source_ids if source_id in sources_by_id]
    if not permissions["allow_raw_snippets"] and ordered_sources:
        warnings.append("Raw source text is redacted by Bridge permissions.")
    packet = build_bridge_context_packet(
        query=payload.query,
        context_request_id=context_request_id,
        selected_clusters=[item for item in bundle.get("selected_clusters") or [] if isinstance(item, dict)],
        citations=[item for item in bundle.get("citations") or [] if isinstance(item, dict)],
        source_snippets=ordered_sources,
        warnings=warnings,
        memory_items=[item for item in bundle.get("memory_items") or [] if isinstance(item, dict)],
        working_memory=bundle.get("working_memory") or {},
        retrieval_authority=bool(bundle.get("retrieval_authority", True)),
        cluster_profile=exposed_cluster_profile,
        token_estimate=bundle.get("token_estimate") or {},
        bundle_status=bundle.get("bundle_status") or {},
    )
    packet_text = render_context_packet(packet)
    response = {
        "context_request_id": context_request_id,
        "query": payload.query,
        "selected_clusters": [item for item in bundle.get("selected_clusters") or [] if isinstance(item, dict)],
        "source_snippets": ordered_sources,
        "citations": [item for item in bundle.get("citations") or [] if isinstance(item, dict)],
        "warnings": warnings,
        "packet_text": packet_text,
        "expansion_handles": [item["handle"] for item in packet["evidence"]],
        "memory_items": [item for item in bundle.get("memory_items") or [] if isinstance(item, dict)],
        "working_memory": bundle.get("working_memory") or {},
        "cluster_profile": exposed_cluster_profile,
        "retrieval_authority": bool(bundle.get("retrieval_authority", True)),
        "token_estimate": bundle.get("token_estimate") or {},
        "bundle_status": bundle.get("bundle_status") or {},
    }
    response_bytes = len(json.dumps(response, ensure_ascii=False).encode("utf-8"))
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO bridge_context_packets (
                id, vault_id, cluster_id, client_name, query, packet_text, evidence_handles_json, source_titles_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                vault_id = excluded.vault_id,
                cluster_id = excluded.cluster_id,
                client_name = excluded.client_name,
                query = excluded.query,
                packet_text = excluded.packet_text,
                evidence_handles_json = excluded.evidence_handles_json,
                source_titles_json = excluded.source_titles_json,
                created_at = excluded.created_at
            """,
            (
                context_request_id,
                vault_id,
                payload.cluster_id,
                payload.client_name,
                payload.query,
                packet_text,
                json.dumps(response["expansion_handles"], separators=(",", ":")),
                json.dumps([item["title"] for item in packet["evidence"]], separators=(",", ":")),
                utc_now(),
            ),
        )
        _insert_bridge_request(
            conn,
            payload.client_name,
            payload.query,
            payload.mode,
            client_id=client_permissions["id"] if client_permissions else None,
            decision="allowed",
            source_count=len(ordered_sources),
            response_bytes=response_bytes,
        )
        _record_bridge_client_usage(
            conn,
            client_permissions,
            response_bytes=response_bytes,
        )
        compact_bridge_tables(conn)
    return response


@router.post("/external-turn", response_model=BridgeCaptureResponse)
def log_external_turn(
    payload: BridgeExternalTurnCapture,
    x_cml_bridge_token: str | None = Header(default=None),
) -> dict:
    vault_id, cluster_id, client_permissions, auth_mode = _authorize_bridge_write_scope(
        payload.vault_id,
        payload.cluster_id,
        x_cml_bridge_token,
    )
    with connect() as conn:
        _enforce_runtime_rate_limits(conn, client_permissions, auth_mode)
    title = f"External model turn - {payload.client_name}"[:240]
    body = "\n\n".join(
        part
        for part in (
            f"External model transcript from {payload.client_name}",
            f"Model: {payload.model_name or 'unknown'}",
            f"Context request ID: {payload.context_request_id or 'none'}",
            "User prompt:",
            payload.user_prompt,
            "Model response:",
            payload.model_response,
            f"Metadata: {json.dumps(payload.metadata, sort_keys=True)}" if payload.metadata else "",
        )
        if part
    )
    quality = None
    with connect() as conn:
        quality = classify_external_response_quality(
            conn,
            vault_id=vault_id,
            context_request_id=payload.context_request_id,
            response_text=payload.model_response,
            artifact_mode=False,
        )
    return _capture_bridge_source(
        vault_id=vault_id,
        cluster_id=cluster_id,
        title=title,
        source_type="external_transcript",
        text=body,
        context_request_id=payload.context_request_id,
        quality_state=quality["quality_state"],
        quality_reasons=quality["reasons"],
        client_name=payload.client_name,
        mode="external_turn",
        client_id=client_permissions["id"] if client_permissions else None,
    )


@router.post("/context/expand", response_model=BridgeContextExpandResponse)
def expand_context_item(
    payload: BridgeContextExpandRequest,
    x_cml_bridge_token: str | None = Header(default=None),
) -> dict:
    settings, client_permissions, auth_mode = _authorize_bridge_runtime_token(x_cml_bridge_token)
    permissions = client_permissions or settings
    with connect() as conn:
        _enforce_runtime_rate_limits(conn, client_permissions, auth_mode)
        vault_id = _resolve_bridge_vault_id(
            conn,
            requested_vault_id=payload.vault_id,
            requested_cluster_id=payload.cluster_id,
            permissions=permissions,
        )
        expanded = _expand_bridge_handle(
            conn,
            vault_id=vault_id,
            handle=payload.handle,
            allow_raw_snippets=bool(permissions["allow_raw_snippets"]),
        )
        if permissions["allowed_cluster_ids"] and expanded.get("cluster_id") and expanded["cluster_id"] not in permissions["allowed_cluster_ids"]:
            raise HTTPException(status_code=403, detail="cluster_not_allowed")
        if permissions["allowed_vault_ids"] and vault_id not in permissions["allowed_vault_ids"]:
            raise HTTPException(status_code=403, detail="vault_not_allowed")
        compact_bridge_tables(conn)
    return expanded


@router.get("/reviews", response_model=list[BridgeWritebackReviewRead])
def list_bridge_writeback_reviews(
    vault_id: str | None = None,
    pending_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    params: list = []
    clauses: list[str] = []
    if vault_id:
        clauses.append("reviews.vault_id = ?")
        params.append(vault_id)
    if pending_only:
        clauses.append("reviews.approved = 0")
        clauses.append("reviews.quality_state <> 'grounded'")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    bounded_limit = max(1, min(limit, 200))
    bounded_offset = max(offset, 0)
    with connect() as conn:
        _ensure_bridge_vault_filter(conn, vault_id)
        rows = conn.execute(
            f"""
            SELECT reviews.*, sources.title, sources.trust_tier, sources.security_labels
            FROM bridge_writeback_reviews reviews
            JOIN sources ON sources.id = reviews.source_id
            {where}
            ORDER BY reviews.updated_at DESC, reviews.source_id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, bounded_limit, bounded_offset],
        ).fetchall()
    return [_bridge_review_from_row(row) for row in rows]


@router.get("/captures", response_model=list[BridgeCaptureListItem])
def list_bridge_captures(vault_id: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    params: list[object] = []
    clauses = ["sources.deleted_at IS NULL", "sources.source_type IN ('external_transcript', 'external_artifact')"]
    if vault_id:
        clauses.append("sources.vault_id = ?")
        params.append(vault_id)
    bounded_limit = max(1, min(limit, 200))
    bounded_offset = max(offset, 0)
    with connect() as conn:
        _ensure_bridge_vault_filter(conn, vault_id)
        rows = conn.execute(
            f"""
            SELECT
                sources.id AS source_id,
                sources.vault_id,
                sources.cluster_id,
                sources.title,
                sources.source_type,
                sources.trust_tier,
                sources.security_labels,
                COALESCE(reviews.quality_state, 'unknown') AS quality_state,
                COALESCE(reviews.approved, 0) AS approved,
                sources.created_at
            FROM sources
            LEFT JOIN bridge_writeback_reviews reviews ON reviews.source_id = sources.id
            WHERE {' AND '.join(clauses)}
            ORDER BY sources.created_at DESC, sources.id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, bounded_limit, bounded_offset],
        ).fetchall()
    return [
        {
            "source_id": row["source_id"],
            "vault_id": row["vault_id"],
            "cluster_id": row["cluster_id"],
            "title": row["title"],
            "source_type": row["source_type"],
            "quality_state": row["quality_state"],
            "approved": bool(row["approved"]),
            "trust_tier": row["trust_tier"],
            "security_labels": _json_list(row["security_labels"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


@router.post("/reviews/{source_id}", response_model=BridgeWritebackReviewRead)
def decide_bridge_writeback_review(source_id: str, payload: BridgeWritebackReviewDecision) -> dict:
    with connect() as conn:
        updated = set_bridge_writeback_review_approval(conn, source_id=source_id, approved=payload.approved)
        if updated is None:
            raise HTTPException(status_code=404, detail="bridge_review_not_found")
        row = conn.execute(
            """
            SELECT reviews.*, sources.title, sources.trust_tier, sources.security_labels
            FROM bridge_writeback_reviews reviews
            JOIN sources ON sources.id = reviews.source_id
            WHERE reviews.source_id = ?
            """,
            (source_id,),
        ).fetchone()
    return _bridge_review_from_row(row)


@router.post("/artifacts", response_model=BridgeCaptureResponse)
def capture_external_artifact(
    payload: BridgeArtifactCapture,
    x_cml_bridge_token: str | None = Header(default=None),
) -> dict:
    vault_id, cluster_id, client_permissions, auth_mode = _authorize_bridge_write_scope(
        payload.vault_id,
        payload.cluster_id,
        x_cml_bridge_token,
    )
    with connect() as conn:
        _enforce_runtime_rate_limits(conn, client_permissions, auth_mode)
    body = "\n\n".join(
        part
        for part in (
            f"External artifact from {payload.client_name}",
            f"Artifact type: {payload.artifact_type}",
            f"Metadata: {json.dumps(payload.metadata, sort_keys=True)}" if payload.metadata else "",
            payload.content,
        )
        if part
    )
    quality = {"quality_state": "user_artifact", "reasons": ["explicit_artifact_capture"]}
    return _capture_bridge_source(
        vault_id=vault_id,
        cluster_id=cluster_id,
        title=payload.title,
        source_type="external_artifact",
        text=body,
        context_request_id=None,
        quality_state=quality["quality_state"],
        quality_reasons=quality["reasons"],
        client_name=payload.client_name,
        mode="external_artifact",
        client_id=client_permissions["id"] if client_permissions else None,
    )


@router.get("/requests", response_model=list[BridgeRequestRead])
def list_bridge_requests(limit: int = 50, offset: int = 0) -> list[dict]:
    bounded_limit = max(1, min(limit, 200))
    bounded_offset = max(offset, 0)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM bridge_requests
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """
            ,
            (bounded_limit, bounded_offset),
        ).fetchall()
    return [dict_from_row(row) for row in rows]


@router.get("/token-rotations", response_model=list[BridgeTokenRotationRead])
def list_bridge_token_rotations(limit: int = 20, offset: int = 0) -> list[dict]:
    bounded_limit = max(1, min(limit, 100))
    bounded_offset = max(offset, 0)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, rotated_at, reason
            FROM bridge_token_rotations
            ORDER BY rotated_at DESC, id DESC
            LIMIT ? OFFSET ?
            """
            ,
            (bounded_limit, bounded_offset),
        ).fetchall()
    return [dict_from_row(row) for row in rows]


@router.get("/clients", response_model=list[BridgeClientRead])
def list_bridge_clients(limit: int = 100, offset: int = 0) -> list[dict]:
    bounded_limit = max(1, min(limit, 200))
    bounded_offset = max(offset, 0)
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM bridge_clients ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?",
            (bounded_limit, bounded_offset),
        ).fetchall()
        return [_bridge_client_from_row(conn, row) for row in rows]


@router.post("/clients", response_model=BridgeClientCreateResponse)
def create_bridge_client(payload: BridgeClientCreate) -> dict:
    now = utc_now()
    token = secrets.token_urlsafe(24)
    with connect() as conn:
        existing_vault_ids = _existing_vault_ids(conn, payload.allowed_vault_ids)
        existing_cluster_ids = _existing_cluster_ids(conn, payload.allowed_cluster_ids)
        client = {
            "id": f"bridge-client-{uuid4()}",
            "name": payload.name,
            "token_hash": _token_hash(token),
            "enabled": 1,
            "approval_vault_id": _bridge_client_anchor_vault_id(
                conn,
                allowed_vault_ids=existing_vault_ids,
                allowed_cluster_ids=existing_cluster_ids,
            ),
            "allowed_vault_ids": json.dumps(existing_vault_ids),
            "allowed_cluster_ids": json.dumps(existing_cluster_ids),
            "allow_raw_snippets": 1 if payload.allow_raw_snippets else 0,
            "allow_style_profile": 1 if payload.allow_cluster_profile else 0,
            "metadata_json": "{}",
            "approval_request_id": None,
            "approved_at": now,
            "revoked_at": None,
            "last_request_at": None,
            "request_count_total": 0,
            "response_bytes_total": 0,
            "created_at": now,
            "updated_at": now,
        }
        conn.execute(
            """
            INSERT INTO bridge_clients (
                id, name, token_hash, enabled, approval_vault_id, allowed_vault_ids, allowed_cluster_ids,
                allow_raw_snippets, allow_style_profile, metadata_json,
                approval_request_id, approved_at, revoked_at, last_request_at,
                request_count_total, response_bytes_total, created_at, updated_at
            )
            VALUES (
                :id, :name, :token_hash, :enabled, :approval_vault_id, :allowed_vault_ids, :allowed_cluster_ids,
                :allow_raw_snippets, :allow_style_profile, :metadata_json,
                :approval_request_id, :approved_at, :revoked_at, :last_request_at,
                :request_count_total, :response_bytes_total, :created_at, :updated_at
            )
            """,
            client,
        )
        _insert_bridge_audit_event(
            conn,
            vault_id=client["approval_vault_id"],
            client_id=client["id"],
            approval_request_id=None,
            event_type="bridge_client_created",
            detail={"name": payload.name, "manual": True},
        )
        compact_bridge_tables(conn)
    return {**_bridge_client_from_mapping(client), "token": token}


@router.patch("/clients/{client_id}", response_model=BridgeClientCreateResponse | BridgeClientRead)
def update_bridge_client(client_id: str, payload: BridgeClientUpdate) -> dict:
    updates = payload.model_dump(exclude_unset=True)
    now = utc_now()
    with connect() as conn:
        row = conn.execute("SELECT * FROM bridge_clients WHERE id = ?", (client_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="bridge_client_not_found")
        current = dict_from_row(row)
        token = None
        if updates.get("rotate_token"):
            token = secrets.token_urlsafe(24)
            conn.execute(
                """
                INSERT INTO bridge_client_token_rotations (
                    id, client_id, rotated_at, reason, previous_token_hash, new_token_hash
                )
                VALUES (?, ?, ?, 'manual_rotation', ?, ?)
                """,
                (
                    f"bridge-client-token-rotation-{uuid4()}",
                    client_id,
                    now,
                    current["token_hash"],
                    _token_hash(token),
                ),
            )
            current["token_hash"] = _token_hash(token)
        for key in (
            "name",
            "enabled",
            "allowed_vault_ids",
            "allowed_cluster_ids",
            "allow_raw_snippets",
            "allow_cluster_profile",
        ):
            if key in updates and updates[key] is not None:
                value = updates[key]
                if key == "allowed_vault_ids":
                    value = json.dumps(_existing_vault_ids(conn, value))
                elif key == "allowed_cluster_ids":
                    value = json.dumps(_existing_cluster_ids(conn, value))
                elif key in {"enabled", "allow_raw_snippets", "allow_cluster_profile"}:
                    value = 1 if value else 0
                if key == "allow_cluster_profile":
                    current["allow_style_profile"] = value
                else:
                    current[key] = value
        candidate_approval_vault_id = _bridge_client_anchor_vault_id(
            conn,
            allowed_vault_ids=_json_list(current.get("allowed_vault_ids")),
            allowed_cluster_ids=_json_list(current.get("allowed_cluster_ids")),
        )
        if current.get("approval_request_id") and current.get("approval_vault_id"):
            # Approved clients keep their original vault anchor so encrypted identity metadata
            # remains readable after later scope edits.
            current["approval_vault_id"] = current["approval_vault_id"]
        else:
            current["approval_vault_id"] = candidate_approval_vault_id
        current["updated_at"] = now
        conn.execute(
            """
            UPDATE bridge_clients
            SET name = :name,
                token_hash = :token_hash,
                enabled = :enabled,
                approval_vault_id = :approval_vault_id,
                allowed_vault_ids = :allowed_vault_ids,
                allowed_cluster_ids = :allowed_cluster_ids,
                allow_raw_snippets = :allow_raw_snippets,
                allow_style_profile = :allow_style_profile,
                updated_at = :updated_at
            WHERE id = :id
            """,
            current,
        )
        event_type = "bridge_client_updated"
        if updates.get("enabled") is False:
            current["revoked_at"] = now
            event_type = "bridge_client_revoked"
        elif updates.get("enabled") is True:
            current["revoked_at"] = None
        conn.execute(
            "UPDATE bridge_clients SET revoked_at = :revoked_at WHERE id = :id",
            current,
        )
        updated = conn.execute("SELECT * FROM bridge_clients WHERE id = ?", (client_id,)).fetchone()
        _insert_bridge_audit_event(
            conn,
            vault_id=current.get("approval_vault_id"),
            client_id=client_id,
            approval_request_id=current.get("approval_request_id"),
            event_type=event_type,
            detail={"name": current["name"]},
        )
        compact_bridge_tables(conn)
        result = _bridge_client_from_row(conn, updated)
        if token:
            return {**result, "token": token}
        return result


@router.delete("/clients/{client_id}", status_code=204)
def revoke_bridge_client(client_id: str) -> None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM bridge_clients WHERE id = ?", (client_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="bridge_client_not_found")
        now = utc_now()
        conn.execute(
            """
            UPDATE bridge_clients
            SET enabled = 0, revoked_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, now, client_id),
        )
        conn.execute(
            """
            UPDATE bridge_approval_requests
            SET status = CASE WHEN status = 'approved' THEN 'revoked' ELSE status END,
                updated_at = ?
            WHERE client_id = ?
            """,
            (now, client_id),
        )
        _insert_bridge_audit_event(
            conn,
            vault_id=row["approval_vault_id"],
            client_id=client_id,
            approval_request_id=row["approval_request_id"],
            event_type="bridge_client_revoked",
            detail={"name": row["name"]},
        )
        compact_bridge_tables(conn)


@router.get("/clusters")
def list_bridge_clusters(
    x_cml_bridge_token: str | None = Header(default=None),
    limit: int = 500,
    offset: int = 0,
) -> dict:
    safe_limit = max(1, min(int(limit), 1000))
    safe_offset = max(0, int(offset))
    with connect() as conn:
        settings, client_permissions, auth_mode = _authorize_bridge_runtime_token(
            x_cml_bridge_token,
            conn=conn,
        )
        permissions = client_permissions or settings
        _enforce_runtime_rate_limits(conn, client_permissions, auth_mode)
        params: list[object] = []
        clauses: list[str] = []
        if permissions["allowed_vault_ids"]:
            clauses.append(f"vault_id IN ({','.join('?' for _ in permissions['allowed_vault_ids'])})")
            params.extend(permissions["allowed_vault_ids"])
        if permissions["allowed_cluster_ids"]:
            clauses.append(f"id IN ({','.join('?' for _ in permissions['allowed_cluster_ids'])})")
            params.extend(permissions["allowed_cluster_ids"])
        if not clauses:
            raise HTTPException(status_code=409, detail="no_active_vault")
        rows = conn.execute(
            f"SELECT * FROM clusters WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?",
            [*params, safe_limit, safe_offset],
        ).fetchall()
    return {"clusters": [dict_from_row(row) for row in rows]}


def _ensure_bridge_settings(conn) -> None:
    existing = conn.execute("SELECT id FROM bridge_settings WHERE id = 'default'").fetchone()
    if existing is not None:
        return
    now = utc_now()
    conn.execute(
        """
        INSERT INTO bridge_settings (
            id, enabled, allowed_vault_ids, allowed_cluster_ids, allow_raw_snippets,
            allow_style_profile, bridge_token, created_at, updated_at
        )
        VALUES ('default', 0, '[]', '[]', 0, 0, ?, ?, ?)
        """,
        (secrets.token_urlsafe(24), now, now),
    )


def _get_bridge_settings(conn=None) -> dict:
    if conn is None:
        with connect() as local_conn:
            return _get_bridge_settings(local_conn)
    _ensure_bridge_settings(conn)
    row = conn.execute("SELECT * FROM bridge_settings WHERE id = 'default'").fetchone()
    configured_vault_ids = [str(item) for item in _json_list(row["allowed_vault_ids"])]
    configured_cluster_ids = [str(item) for item in _json_list(row["allowed_cluster_ids"])]
    existing_vault_ids = _existing_ids(conn, table="vaults", ids=configured_vault_ids)
    existing_cluster_ids = _existing_ids(conn, table="clusters", ids=configured_cluster_ids)
    allowed_vault_ids = [
        item for item in configured_vault_ids if item in existing_vault_ids
    ]
    allowed_cluster_ids = [
        item for item in configured_cluster_ids if item in existing_cluster_ids
    ]
    if (
        allowed_vault_ids != configured_vault_ids
        or allowed_cluster_ids != configured_cluster_ids
    ):
        conn.execute(
            """
            UPDATE bridge_settings
            SET allowed_vault_ids = ?, allowed_cluster_ids = ?, updated_at = ?
            WHERE id = 'default'
            """,
            (json.dumps(allowed_vault_ids), json.dumps(allowed_cluster_ids), utc_now()),
        )
    return {
        "enabled": bool(row["enabled"]),
        "allowed_vault_ids": allowed_vault_ids,
        "allowed_cluster_ids": allowed_cluster_ids,
        "allow_raw_snippets": bool(row["allow_raw_snippets"]),
        "allow_cluster_profile": bool(row["allow_style_profile"]),
        "bridge_token": row["bridge_token"] or "",
    }


def _pending_approval_count(conn=None) -> int:
    if conn is None:
        with connect() as local_conn:
            return _pending_approval_count(local_conn)
    _expire_pending_approval_requests(conn)
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM bridge_approval_requests WHERE status = 'pending'"
    ).fetchone()
    return int(row["count"] or 0)


def _bridge_status_from_conn(conn) -> dict[str, str | bool]:
    settings = _get_bridge_settings(conn)
    return {
        **settings,
        "mcp": "planned",
        "http_api": "available",
        "cli": "planned",
        "approval_requests_pending": _pending_approval_count(conn),
        "last_refreshed_at": utc_now(),
    }


def _json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _existing_ids(conn, *, table: str, ids: list[str]) -> set[str]:
    if table not in {"vaults", "clusters"}:
        raise ValueError("unsupported_id_table")
    unique_ids = list(dict.fromkeys(item for item in ids if item))
    if not unique_ids:
        return set()
    placeholders = ",".join("?" for _ in unique_ids)
    rows = conn.execute(
        f"SELECT id FROM {table} WHERE id IN ({placeholders})",
        unique_ids,
    ).fetchall()
    return {str(row["id"]) for row in rows}


def _ensure_bridge_vault_filter(conn, vault_id: str | None) -> None:
    if not vault_id:
        return
    row = conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="vault_not_found")


def _token_hash(token: str) -> str:
    if not token:
        return ""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _bridge_client_for_token(token: str | None, conn=None) -> dict | None:
    if token and len(token) > 512:
        return None
    token_hash = _token_hash(token or "")
    if not token_hash:
        return None
    if conn is None:
        with connect() as local_conn:
            return _bridge_client_for_token(token, conn=local_conn)
    row = conn.execute(
        "SELECT * FROM bridge_clients WHERE enabled = 1 AND token_hash = ? LIMIT 1",
        (token_hash,),
    ).fetchone()
    if row is not None:
        return _bridge_client_from_row(conn, row)
    return None


def _token_matches(expected: str, supplied: str | None) -> bool:
    if not expected or not supplied or len(supplied) > 512:
        return False
    return secrets.compare_digest(expected, supplied)


def _token_hash_matches(expected_hash: str, supplied: str | None) -> bool:
    if not expected_hash or not supplied or len(supplied) > 512:
        return False
    return secrets.compare_digest(expected_hash, _token_hash(supplied))


def _bridge_client_from_row(conn, row) -> dict:
    client = dict_from_row(row)
    metadata = {}
    approval_vault_id = client.get("approval_vault_id")
    if approval_vault_id:
        metadata = load_secure_json(
            conn,
            vault_id=str(approval_vault_id),
            entity_type="bridge_client",
            entity_id=client["id"],
            field_name="metadata_json",
            fallback_text=client.get("metadata_json"),
        )
    return _bridge_client_from_mapping(client, metadata=metadata)


def _bridge_client_from_mapping(client: dict, *, metadata: dict | None = None) -> dict:
    meta = metadata or {}
    return {
        "id": client["id"],
        "name": client["name"],
        "enabled": bool(client["enabled"]),
        "approval_vault_id": client.get("approval_vault_id"),
        "allowed_vault_ids": _json_list(client.get("allowed_vault_ids")),
        "allowed_cluster_ids": _json_list(client.get("allowed_cluster_ids")),
        "allow_raw_snippets": bool(client.get("allow_raw_snippets")),
        "allow_cluster_profile": bool(client.get("allow_style_profile")),
        "approval_request_id": client.get("approval_request_id"),
        "approved_at": client.get("approved_at"),
        "revoked_at": client.get("revoked_at"),
        "last_request_at": client.get("last_request_at"),
        "request_count_total": int(client.get("request_count_total") or 0),
        "response_bytes_total": int(client.get("response_bytes_total") or 0),
        "executable_path_claim": str(meta.get("executable_path_claim") or ""),
        "observed_executable_path": str(meta.get("observed_executable_path") or ""),
        "publisher_name": str(meta.get("publisher_name") or ""),
        "signature_status": str(meta.get("signature_status") or "not_provided"),
        "signature_detail": str(meta.get("signature_detail") or ""),
        "verified_identity": bool(meta.get("verified_identity")),
        "verified_identity_label": str(meta.get("verified_identity_label") or ""),
        "created_at": client["created_at"],
        "updated_at": client["updated_at"],
    }


def _bridge_client_anchor_vault_id(conn, *, allowed_vault_ids: list[str], allowed_cluster_ids: list[str]) -> str | None:
    if allowed_vault_ids:
        return str(allowed_vault_ids[0])
    if not allowed_cluster_ids:
        return None
    rows = conn.execute(
        f"SELECT DISTINCT vault_id FROM clusters WHERE id IN ({','.join('?' for _ in allowed_cluster_ids)})",
        allowed_cluster_ids,
    ).fetchall()
    vault_ids = [str(row["vault_id"]) for row in rows if row["vault_id"]]
    if len(vault_ids) == 1:
        return vault_ids[0]
    return None


def _bridge_source_from_row(row, *, conn=None, allow_raw_snippets: bool) -> dict:
    if allow_raw_snippets:
        return source_from_row(row, conn=conn)
    if conn is None:
        with connect() as local_conn:
            return _bridge_source_from_row(row, conn=local_conn, allow_raw_snippets=False)
    source = dict_from_row(row)
    if is_vault_secured(conn, source["vault_id"]):
        for field in ("summary", "tags"):
            encrypted = get_encrypted_text(
                conn,
                vault_id=source["vault_id"],
                entity_type="source",
                entity_id=source["id"],
                field_name=field,
            )
            if encrypted:
                source[field] = encrypted
    source["raw_text"] = ""
    source["extracted_text"] = ""
    raw_tags = source.get("tags") or "[]"
    try:
        tags = json.loads(raw_tags)
    except json.JSONDecodeError:
        tags = []
    source["tags"] = tags if isinstance(tags, list) else []
    return source


def _resolve_bridge_vault_id(
    conn,
    *,
    requested_vault_id: str | None,
    requested_cluster_id: str | None,
    permissions: dict,
) -> str:
    resolved_vault_id: str | None = None
    if requested_vault_id:
        resolved_vault_id = requested_vault_id
    elif requested_cluster_id:
        cluster = conn.execute("SELECT vault_id FROM clusters WHERE id = ?", (requested_cluster_id,)).fetchone()
        if cluster is None:
            raise HTTPException(status_code=404, detail="cluster_not_found")
        resolved_vault_id = str(cluster["vault_id"])
    else:
        allowed_vault_ids = list(permissions.get("allowed_vault_ids") or [])
        if len(allowed_vault_ids) == 1:
            resolved_vault_id = str(allowed_vault_ids[0])
    if not resolved_vault_id:
        raise HTTPException(status_code=409, detail="no_active_vault")
    vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (resolved_vault_id,)).fetchone()
    if vault is None:
        raise HTTPException(status_code=404, detail="vault_not_found")
    return resolved_vault_id


def _approval_request_details(conn, row) -> dict:
    return load_secure_json(
        conn,
        vault_id=row["vault_id"],
        entity_type="bridge_approval_request",
        entity_id=row["id"],
        field_name="details_json",
        fallback_text=row["details_json"],
    )


def _expire_pending_approval_requests(conn) -> None:
    conn.execute(
        """
        UPDATE bridge_approval_requests
        SET status = 'expired', decided_at = ?, updated_at = ?
        WHERE status = 'pending' AND expires_at <= ?
        """,
        (utc_now(), utc_now(), utc_now()),
    )


def _approval_request_from_row(conn, row) -> dict:
    details = _approval_request_details(conn, row)
    return {
        "id": row["id"],
        "vault_id": row["vault_id"],
        "status": row["status"],
        "claimed_name": str(details.get("claimed_name") or "unknown"),
        "requested_vault_ids": [str(item) for item in details.get("requested_vault_ids") or []],
        "requested_cluster_ids": [str(item) for item in details.get("requested_cluster_ids") or []],
        "allow_raw_snippets": bool(details.get("allow_raw_snippets")),
        "allow_cluster_profile": bool(
            details.get("allow_cluster_profile", details.get("allow_style_profile"))
        ),
        "executable_path_claim": str(details.get("executable_path_claim") or ""),
        "observed_executable_path": str(details.get("observed_executable_path") or ""),
        "publisher_name": str(details.get("publisher_name") or ""),
        "signature_status": str(details.get("signature_status") or "not_provided"),
        "signature_detail": str(details.get("signature_detail") or ""),
        "verified_identity": bool(details.get("verified_identity")),
        "verified_identity_label": str(details.get("verified_identity_label") or ""),
        "client_id": row["client_id"],
        "requested_at": row["requested_at"],
        "expires_at": row["expires_at"],
        "decided_at": row["decided_at"],
        "delivered_at": row["delivered_at"],
        "updated_at": row["updated_at"],
        "detail": str(details.get("detail") or ""),
    }


def _bridge_audit_event_from_row(conn, row) -> dict:
    detail = load_secure_json(
        conn,
        vault_id=str(row["vault_id"] or ""),
        entity_type="bridge_audit_event",
        entity_id=row["id"],
        field_name="detail_json",
        fallback_text=row["detail_json"],
    ) if row["vault_id"] else {}
    return {
        "id": row["id"],
        "vault_id": row["vault_id"],
        "client_id": row["client_id"],
        "approval_request_id": row["approval_request_id"],
        "event_type": row["event_type"],
        "detail": str(detail.get("detail") or detail.get("claimed_name") or ""),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _bridge_review_from_row(row) -> dict:
    return {
        "source_id": row["source_id"],
        "vault_id": row["vault_id"],
        "context_request_id": row["context_request_id"],
        "quality_state": row["quality_state"],
        "approved": bool(row["approved"]),
        "reasons": json.loads(row["reasons_json"] or "[]"),
        "title": row["title"] or "",
        "trust_tier": row["trust_tier"] or "",
        "security_labels": json.loads(row["security_labels"] or "[]"),
        "updated_at": row["updated_at"],
    }


def _authorize_bridge_runtime_token(token: str | None, *, conn=None) -> tuple[dict, dict | None, str]:
    settings = _get_bridge_settings(conn)
    client_permissions = _bridge_client_for_token(token, conn=conn)
    if not settings["enabled"]:
        raise HTTPException(status_code=403, detail="bridge_disabled")
    if client_permissions is not None:
        return settings, client_permissions, "client_token"
    if _token_matches(settings["bridge_token"], token):
        if security_gate_active():
            raise HTTPException(status_code=403, detail="bridge_shared_token_disabled")
        return settings, None, "shared_token"
    raise HTTPException(status_code=401, detail="bridge_token_invalid")


def _authorize_bridge_write_scope(
    vault_id: str | None,
    cluster_id: str | None,
    token: str | None,
) -> tuple[str, str | None, dict | None, str]:
    settings, client_permissions, auth_mode = _authorize_bridge_runtime_token(token)
    permissions = client_permissions or settings
    with connect() as conn:
        if cluster_id and permissions["allowed_cluster_ids"] and cluster_id not in permissions["allowed_cluster_ids"]:
            raise HTTPException(status_code=403, detail="cluster_not_allowed")
        resolved_vault_id = _resolve_bridge_vault_id(
            conn,
            requested_vault_id=vault_id,
            requested_cluster_id=cluster_id,
            permissions=permissions,
        )
        if permissions["allowed_vault_ids"] and resolved_vault_id not in permissions["allowed_vault_ids"]:
            raise HTTPException(status_code=403, detail="vault_not_allowed")
        vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (resolved_vault_id,)).fetchone()
        if vault is None:
            raise HTTPException(status_code=404, detail="vault_not_found")
        if cluster_id:
            cluster = conn.execute(
                "SELECT id FROM clusters WHERE id = ? AND vault_id = ?",
                (cluster_id, resolved_vault_id),
            ).fetchone()
            if cluster is None:
                raise HTTPException(status_code=404, detail="cluster_not_found")
    return resolved_vault_id, cluster_id, client_permissions, auth_mode


def _capture_bridge_source(
    *,
    vault_id: str,
    cluster_id: str | None,
    title: str,
    source_type: str,
    text: str,
    context_request_id: str | None,
    quality_state: str,
    quality_reasons: list[str],
    client_name: str,
    mode: str,
    client_id: str | None,
) -> dict:
    now = utc_now()
    source_id = f"bridge-capture-{uuid4()}"
    page_id = f"page-{uuid4()}"
    clean_text = text.strip()
    with connect() as conn:
        source_payload = store_source_content_fields(
            conn,
            {
                "id": source_id,
                "vault_id": vault_id,
                "raw_text": clean_text,
                "extracted_text": clean_text,
                "summary": summarize_text(clean_text),
                "tags": json.dumps(["BRIDGE", "EXTERNAL", source_type.upper(), client_name.upper()[:40]]),
            },
            now=now,
        )
        conn.execute(
            """
            INSERT INTO sources (
                id, vault_id, cluster_id, title, source_type, state, original_path, url,
                checksum, raw_text, extracted_text, summary, tags, cover_image_url, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'indexed', NULL, NULL, ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                source_id,
                vault_id,
                cluster_id,
                title,
                source_type,
                content_hash(clean_text),
                source_payload["raw_text"],
                source_payload["extracted_text"],
                source_payload["summary"],
                source_payload["tags"],
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO source_pages (
                id, source_id, vault_id, page_number, raw_text, extraction_version,
                content_hash, created_at, updated_at
            )
            VALUES (?, ?, ?, 1, ?, 'bridge-capture-v1', ?, ?, ?)
            """,
            (
                page_id,
                source_id,
                vault_id,
                plaintext_column_for_text(
                    conn,
                    vault_id=vault_id,
                    entity_type="source_page",
                    entity_id=page_id,
                    field_name="raw_text",
                    text=clean_text,
                    now=now,
                ),
                content_hash(clean_text),
                now,
                now,
            ),
        )
        persist_bridge_writeback_review(
            conn,
            source_id=source_id,
            vault_id=vault_id,
            context_request_id=context_request_id,
            quality_state=quality_state,
            reasons=quality_reasons,
        )
        apply_bridge_quality_to_source(
            conn,
            source_id=source_id,
            quality_state=quality_state,
            reasons=quality_reasons,
        )
        rebuild_source_memory(conn, source_id=source_id)
        source_row = conn.execute(
            "SELECT trust_tier, security_labels FROM sources WHERE id = ?",
            (source_id,),
        ).fetchone()
        enqueue_job(
            conn,
            job_type="reindex_source",
            payload={"source_id": source_id},
            dedupe_key=f"reindex-source:{source_id}",
            scope_id=source_id,
            user_initiated=True,
        )
        response_bytes = len(clean_text.encode("utf-8"))
        _insert_bridge_request(
            conn,
            client_name,
            title,
            mode,
            client_id=client_id,
            decision="captured",
            source_count=1,
            response_bytes=response_bytes,
        )
        if client_id:
            client_row = conn.execute("SELECT * FROM bridge_clients WHERE id = ?", (client_id,)).fetchone()
            if client_row is not None:
                _record_bridge_client_usage(conn, _bridge_client_from_row(conn, client_row), response_bytes=response_bytes)
        compact_bridge_tables(conn)
    security_labels = []
    trust_tier = ""
    if source_row is not None:
        trust_tier = str(source_row["trust_tier"] or "")
        try:
            parsed_labels = json.loads(source_row["security_labels"] or "[]")
            security_labels = parsed_labels if isinstance(parsed_labels, list) else []
        except json.JSONDecodeError:
            security_labels = []
    return {
        "source_id": source_id,
        "vault_id": vault_id,
        "cluster_id": cluster_id,
        "source_type": source_type,
        "indexed": True,
        "quality_state": quality_state,
        "approved": False,
        "review_required": "review_needed" in security_labels,
        "trust_tier": trust_tier,
        "reasons": quality_reasons,
        "security_labels": security_labels,
        "warnings": [
            "External model output was saved as derived transcript/artifact data.",
            f"Bridge quality state: {quality_state}.",
        ],
    }


def _expand_bridge_handle(conn, *, vault_id: str, handle: str, allow_raw_snippets: bool) -> dict:
    normalized = str(handle or "").strip()
    if not normalized or ":" not in normalized:
        raise HTTPException(status_code=400, detail="invalid_context_handle")
    kind, identifier = normalized.split(":", 1)
    if kind == "source":
        row = conn.execute(
            "SELECT * FROM sources WHERE id = ? AND vault_id = ? AND deleted_at IS NULL",
            (identifier, vault_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="context_handle_not_found")
        source = source_from_encrypted_row(conn, row)
        text = _expanded_source_text(source, allow_raw_snippets=allow_raw_snippets)
        warnings = []
        if not allow_raw_snippets:
            warnings.append("Expansion returned redacted source text because raw snippet permission is disabled.")
        return {
            "handle": normalized,
            "source_id": source["id"],
            "chunk_id": None,
            "page_id": None,
            "cluster_id": source.get("cluster_id"),
            "title": source["title"],
            "source_type": source["source_type"],
            "trust_tier": source.get("trust_tier") or "trusted_local",
            "text": text,
            "warnings": warnings,
        }
    if kind == "chunk":
        row = conn.execute(
            """
            SELECT chunks.*, sources.title AS source_title, sources.source_type, sources.trust_tier, sources.cluster_id
            FROM source_chunks chunks
            JOIN sources ON sources.id = chunks.source_id
            WHERE chunks.id = ? AND chunks.vault_id = ? AND sources.deleted_at IS NULL
            """,
            (identifier, vault_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="context_handle_not_found")
        chunk = chunk_from_encrypted_row(conn, row)
        text = str(chunk.get("text") or "").strip()
        return {
            "handle": normalized,
            "source_id": chunk["source_id"],
            "chunk_id": chunk["id"],
            "page_id": chunk.get("page_id"),
            "cluster_id": chunk.get("cluster_id"),
            "title": chunk.get("source_title") or "",
            "source_type": chunk.get("source_type") or "",
            "trust_tier": chunk.get("trust_tier") or "trusted_local",
            "text": text,
            "warnings": [],
        }
    if kind == "page":
        row = conn.execute(
            """
            SELECT pages.*, sources.title AS source_title, sources.source_type, sources.trust_tier, sources.cluster_id
            FROM source_pages pages
            JOIN sources ON sources.id = pages.source_id
            WHERE pages.id = ? AND pages.vault_id = ? AND sources.deleted_at IS NULL
            """,
            (identifier, vault_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="context_handle_not_found")
        page = page_from_encrypted_row(conn, row)
        return {
            "handle": normalized,
            "source_id": page["source_id"],
            "chunk_id": None,
            "page_id": page["id"],
            "cluster_id": page.get("cluster_id"),
            "title": page.get("source_title") or "",
            "source_type": page.get("source_type") or "",
            "trust_tier": page.get("trust_tier") or "trusted_local",
            "text": str(page.get("raw_text") or "").strip(),
            "warnings": [],
        }
    raise HTTPException(status_code=400, detail="unsupported_context_handle")


def _expanded_source_text(source: dict, *, allow_raw_snippets: bool) -> str:
    if allow_raw_snippets:
        text = str(source.get("extracted_text") or source.get("raw_text") or source.get("summary") or "").strip()
        return text
    return str(source.get("summary") or "").strip()


def _insert_bridge_request(
    conn,
    client_name: str,
    query: str,
    mode: str,
    *,
    client_id: str | None = None,
    decision: str = "allowed",
    source_count: int = 0,
    response_bytes: int = 0,
) -> None:
    conn.execute(
        """
        INSERT INTO bridge_requests (
            id, client_id, client_name, query, mode, decision, source_count, response_bytes, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"bridge-{uuid4()}",
            client_id,
            client_name,
            query,
            mode,
            decision,
            source_count,
            response_bytes,
            utc_now(),
        ),
    )


def _log_bridge_request(payload: BridgeContextRequest, *, mode_suffix: str, client_id: str | None = None) -> None:
    with connect() as conn:
        _insert_bridge_request(
            conn,
            payload.client_name,
            payload.query,
            f"{payload.mode}:{mode_suffix}",
            client_id=client_id,
            decision="blocked",
        )
        compact_bridge_tables(conn)


def _approval_vault_id(requested_vault_ids: list[str], current_vault_id: str | None) -> str | None:
    if requested_vault_ids:
        return str(requested_vault_ids[0])
    return current_vault_id


def _existing_vault_ids(conn, ids: list[str]) -> list[str]:
    ordered_ids = _normalized_unique_ids(ids)
    if not ordered_ids:
        return []
    placeholders = ",".join("?" for _ in ordered_ids)
    existing = {
        row["id"]
        for row in conn.execute(
            f"SELECT id FROM vaults WHERE id IN ({placeholders})",
            ordered_ids,
        ).fetchall()
    }
    return [item for item in ordered_ids if item in existing]


def _existing_cluster_ids(conn, ids: list[str]) -> list[str]:
    ordered_ids = _normalized_unique_ids(ids)
    if not ordered_ids:
        return []
    placeholders = ",".join("?" for _ in ordered_ids)
    existing = {
        row["id"]
        for row in conn.execute(
            f"SELECT id FROM clusters WHERE id IN ({placeholders})",
            ordered_ids,
        ).fetchall()
    }
    return [item for item in ordered_ids if item in existing]


def _normalized_unique_ids(ids: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for item in ids:
        normalized = str(item or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _store_approval_delivery_token(conn, vault_id: str, request_id: str, token: str, *, now: str) -> None:
    from backend.app.core.encrypted_storage import is_vault_secured, put_encrypted_text

    if is_vault_secured(conn, vault_id):
        put_encrypted_text(
            conn,
            vault_id=vault_id,
            entity_type="bridge_approval_request",
            entity_id=request_id,
            field_name="issued_token",
            text=token,
            now=now,
        )
        return
    details = _approval_request_details(conn, conn.execute("SELECT * FROM bridge_approval_requests WHERE id = ?", (request_id,)).fetchone())
    details["issued_token"] = token
    conn.execute(
        "UPDATE bridge_approval_requests SET details_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(details, sort_keys=True), now, request_id),
    )


def _pop_approval_delivery_token(conn, row) -> str:
    from backend.app.core.encrypted_storage import get_encrypted_text, is_vault_secured

    if is_vault_secured(conn, row["vault_id"]):
        token = get_encrypted_text(
            conn,
            vault_id=row["vault_id"],
            entity_type="bridge_approval_request",
            entity_id=row["id"],
            field_name="issued_token",
        )
        conn.execute(
            """
            DELETE FROM encrypted_content
            WHERE vault_id = ? AND entity_type = 'bridge_approval_request'
              AND entity_id = ? AND field_name = 'issued_token'
            """,
            (row["vault_id"], row["id"]),
        )
        return token
    details = _approval_request_details(conn, row)
    token = str(details.get("issued_token") or "")
    if token:
        details.pop("issued_token", None)
        conn.execute(
            "UPDATE bridge_approval_requests SET details_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(details, sort_keys=True), utc_now(), row["id"]),
        )
    return token


def _insert_bridge_audit_event(
    conn,
    *,
    vault_id: str | None,
    client_id: str | None,
    approval_request_id: str | None,
    event_type: str,
    detail: dict,
) -> None:
    event_id = f"bridge-audit-{uuid4()}"
    now = utc_now()
    detail_json = "{}"
    if vault_id:
        detail_json = store_secure_json(
            conn,
            vault_id=vault_id,
            entity_type="bridge_audit_event",
            entity_id=event_id,
            field_name="detail_json",
            payload=detail,
            now=now,
        )
    else:
        detail_json = json.dumps(detail, sort_keys=True)
    conn.execute(
        """
        INSERT INTO bridge_audit_events (
            id, vault_id, client_id, approval_request_id, event_type, detail_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (event_id, vault_id, client_id, approval_request_id, event_type, detail_json, now, now),
    )


def _enforce_runtime_rate_limits(conn, client_permissions: dict | None, auth_mode: str) -> None:
    try:
        enforce_rate_limit(
            conn,
            scope_type="bridge_global",
            scope_id="global",
            bucket="bridge_runtime",
            limit=GLOBAL_RATE_LIMIT,
            window_seconds=CLIENT_RATE_WINDOW_SECONDS,
        )
        subject_id = client_permissions["id"] if client_permissions else auth_mode
        enforce_rate_limit(
            conn,
            scope_type="bridge_subject",
            scope_id=subject_id,
            bucket="bridge_runtime",
            limit=CLIENT_RATE_LIMIT,
            window_seconds=CLIENT_RATE_WINDOW_SECONDS,
        )
    except BridgeRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


def _record_bridge_client_usage(conn, client_permissions: dict | None, *, response_bytes: int) -> None:
    if not client_permissions:
        return
    conn.execute(
        """
        UPDATE bridge_clients
        SET last_request_at = ?,
            request_count_total = request_count_total + 1,
            response_bytes_total = response_bytes_total + ?,
            updated_at = ?
        WHERE id = ?
        """,
        (utc_now(), response_bytes, utc_now(), client_permissions["id"]),
    )
