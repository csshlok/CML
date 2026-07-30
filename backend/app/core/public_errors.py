from __future__ import annotations

import logging
import re
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


logger = logging.getLogger("cml.public_errors")

_STABLE_CODE = re.compile(r"^[a-z][a-z0-9_:-]{1,95}$")
_TECHNICAL_DETAIL = re.compile(
    r"(?:[a-zA-Z]:\\|\\\\|/Users/|/home/|Traceback|WinError|Errno|"
    r"sqlite|database is locked|permission denied|access is denied|"
    r"no such file|stack trace|exception:|failed to get ['\"]?[a-zA-Z]+ path)",
    re.IGNORECASE,
)
_SAFE_CODE_MESSAGES = {
    "invalid_vault_secret": "Incorrect passphrase. Try again.",
    "invalid_cursor": "That page is no longer available. Refresh and try again.",
    "vault_locked": "Unlock this library to continue.",
}


def api_error(
    *,
    status_code: int,
    code: str,
    message: str,
    action: str | None = None,
    retryable: bool = False,
    field_issues: list[dict] | None = None,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "action": action,
            "retryable": bool(retryable),
            "field_issues": field_issues or [],
        },
    )


def public_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    status = int(exc.status_code)
    raw_detail = exc.detail
    if isinstance(raw_detail, dict) and {"code", "message"} <= set(raw_detail):
        error = {
            "code": str(raw_detail["code"]),
            "message": str(raw_detail["message"]),
            "action": raw_detail.get("action"),
            "diagnostic_id": raw_detail.get("diagnostic_id"),
            "retryable": bool(raw_detail.get("retryable")),
            "field_issues": raw_detail.get("field_issues") or [],
        }
        return JSONResponse(
            status_code=status,
            content={"detail": error["message"], "error": error},
            headers=exc.headers,
        )
    raw_text = str(raw_detail or "").strip()
    unsafe = status >= 500 or bool(_TECHNICAL_DETAIL.search(raw_text))
    diagnostic_id = None
    if unsafe:
        diagnostic_id = f"diag-{uuid4()}"
        logger.error(
            "public_http_error diagnostic_id=%s method=%s path=%s status=%s detail=%r",
            diagnostic_id,
            request.method,
            request.url.path,
            status,
            raw_text,
        )
    code = _code_for_detail(raw_text, status)
    message = _message_for_status(status) if unsafe else _safe_message(raw_text, status)
    error = {
        "code": code,
        "message": message,
        "action": _action_for_status(status),
        "diagnostic_id": diagnostic_id,
        "retryable": status in {409, 429, 503} or status >= 500,
        "field_issues": [],
    }
    return JSONResponse(
        status_code=status,
        content={"detail": message, "error": error},
        headers=exc.headers,
    )


def public_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    diagnostic_id = f"diag-{uuid4()}"
    logger.error(
        "unhandled_public_error diagnostic_id=%s method=%s path=%s",
        diagnostic_id,
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    message = "Vault could not complete that action."
    return JSONResponse(
        status_code=500,
        content={
            "detail": message,
            "error": {
                "code": "internal_error",
                "message": message,
                "action": "Try again. If it still fails, open Diagnostics.",
                "diagnostic_id": diagnostic_id,
                "retryable": True,
                "field_issues": [],
            },
        },
    )


def public_stream_exception(exc: Exception, *, surface: str) -> dict:
    diagnostic_id = f"diag-{uuid4()}"
    logger.error(
        "public_stream_error diagnostic_id=%s surface=%s",
        diagnostic_id,
        surface,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return {
        "code": "stream_interrupted",
        "message": "Vault could not finish this answer.",
        "action": "Try again.",
        "diagnostic_id": diagnostic_id,
        "retriable": True,
    }


def public_validation_exception(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    diagnostic_id = f"diag-{uuid4()}"
    logger.info(
        "public_validation_error diagnostic_id=%s method=%s path=%s errors=%r",
        diagnostic_id,
        request.method,
        request.url.path,
        exc.errors(),
    )
    message = "Check the highlighted information and try again."
    return JSONResponse(
        status_code=422,
        content={
            "detail": message,
            "error": {
                "code": "invalid_request",
                "message": message,
                "action": "Review the information you entered.",
                "diagnostic_id": diagnostic_id,
                "retryable": False,
                "field_issues": [],
            },
        },
    )


def _code_for_detail(detail: str, status: int) -> str:
    normalized = detail.casefold().strip()
    if _STABLE_CODE.fullmatch(normalized):
        return normalized[:96]
    return {
        400: "invalid_request",
        401: "authentication_required",
        403: "permission_denied",
        404: "not_found",
        409: "conflict",
        423: "vault_locked",
        429: "too_many_requests",
        503: "service_unavailable",
    }.get(status, "internal_error" if status >= 500 else "request_failed")


def _safe_message(detail: str, status: int) -> str:
    if not detail:
        return _message_for_status(status)
    if _STABLE_CODE.fullmatch(detail.casefold()):
        known = _SAFE_CODE_MESSAGES.get(detail.casefold())
        if known:
            return known
        return detail.replace("_", " ").replace(":", " ").strip().capitalize() + "."
    return detail[:300]


def _message_for_status(status: int) -> str:
    if status in {401, 403}:
        return "Vault needs permission before it can do that."
    if status == 404:
        return "That item is no longer available."
    if status == 409:
        return "Vault could not apply that change."
    if status == 423:
        return "Unlock this library to continue."
    if status == 429:
        return "Too many attempts. Wait a moment and try again."
    if status == 503:
        return "Vault's local service is temporarily unavailable."
    return "Vault could not complete that action."


def _action_for_status(status: int) -> str | None:
    if status == 423:
        return "Unlock the library and try again."
    if status == 429:
        return "Wait a moment and try again."
    if status >= 500:
        return "Try again. If it still fails, open Diagnostics."
    return None
