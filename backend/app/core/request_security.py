import hashlib
import hmac

from starlette.responses import JSONResponse

from backend.app.core.bridge_security import BridgeRateLimitError, enforce_rate_limit
from backend.app.core.config import get_settings
from backend.app.core.database import connect


BRIDGE_BODY_LIMIT = 2 * 1024 * 1024
EXTENSION_TEXT_BODY_LIMIT = 2 * 1024 * 1024
EXTENSION_UPLOAD_BODY_LIMIT = 28 * 1024 * 1024
BRIDGE_WINDOW_BYTE_LIMIT = 20 * 1024 * 1024
EXTENSION_WINDOW_BYTE_LIMIT = 100 * 1024 * 1024


class RequestSecurityMiddleware:
    """Authenticate integration requests and cap their bodies before model parsing."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        settings = get_settings()
        if settings.backend_mode == "pre_vault":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path") or "")
        method = str(scope.get("method") or "GET").upper()
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers") or []
        }
        route = _protected_route(path, method, settings.api_prefix)
        if route is None:
            await self.app(scope, receive, send)
            return
        kind, body_limit, window_byte_limit = route
        principal = _authenticate_integration(kind, headers, settings.api_token)
        if principal is None:
            await JSONResponse({"detail": f"Missing or invalid {kind} token"}, status_code=401)(scope, receive, send)
            return
        content_length = headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > body_limit:
                    await JSONResponse({"detail": "Request body is too large"}, status_code=413)(scope, receive, send)
                    return
            except ValueError:
                await JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)(scope, receive, send)
                return
        body = bytearray()
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            body.extend(chunk)
            if len(body) > body_limit:
                await JSONResponse({"detail": "Request body is too large"}, status_code=413)(scope, receive, send)
                return
            more_body = bool(message.get("more_body", False))
        try:
            with connect() as conn:
                enforce_rate_limit(
                    conn,
                    scope_type=f"{kind}_ingress",
                    scope_id=principal,
                    bucket="request_bytes",
                    limit=240,
                    window_seconds=5 * 60,
                    byte_count=len(body),
                    byte_limit=window_byte_limit,
                )
        except BridgeRateLimitError:
            await JSONResponse({"detail": "Integration request quota exceeded"}, status_code=429)(scope, receive, send)
            return
        scope.setdefault("state", {})["request_body_bytes"] = len(body)
        delivered = False

        async def replay_receive():
            nonlocal delivered
            if delivered:
                return {"type": "http.request", "body": b"", "more_body": False}
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay_receive, send)


def _protected_route(path: str, method: str, api_prefix: str):
    if method != "POST":
        return None
    root = api_prefix.rstrip("/")
    extension_upload = f"{root}/extension/capture-upload"
    if path == extension_upload:
        return "extension", EXTENSION_UPLOAD_BODY_LIMIT, EXTENSION_WINDOW_BYTE_LIMIT
    if path == f"{root}/extension/capture":
        return "extension", EXTENSION_TEXT_BODY_LIMIT, EXTENSION_WINDOW_BYTE_LIMIT
    bridge_roots = (
        f"{root}/bridge/context",
        f"{root}/bridge/external-turn",
        f"{root}/bridge/artifacts",
        f"{root}/bridge/captures",
        f"{root}/bridge/reviews",
    )
    if any(path == item or path.startswith(f"{item}/") for item in bridge_roots):
        return "bridge", BRIDGE_BODY_LIMIT, BRIDGE_WINDOW_BYTE_LIMIT
    return None


def _authenticate_integration(kind: str, headers: dict[str, str], api_token: str) -> str | None:
    supplied_api = headers.get("x-cml-api-token", "")
    if api_token and hmac.compare_digest(supplied_api, api_token):
        return "desktop"
    header_name = "x-cml-extension-token" if kind == "extension" else "x-cml-bridge-token"
    token = headers.get(header_name, "")
    if not token:
        return None
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with connect() as conn:
        if kind == "extension":
            row = conn.execute(
                "SELECT id FROM extension_clients WHERE token_hash = ? AND enabled = 1",
                (digest,),
            ).fetchone()
            return str(row["id"]) if row else None
        client = conn.execute(
            "SELECT id FROM bridge_clients WHERE token_hash = ?",
            (digest,),
        ).fetchone()
        if client:
            return str(client["id"])
        settings = conn.execute(
            "SELECT enabled, bridge_token FROM bridge_settings WHERE id = 'default'",
        ).fetchone()
        # Authentication and feature availability are separate decisions. A
        # previously valid shared credential must reach the route so a disabled
        # Bridge returns the stable authenticated 403 contract, never a misleading 401.
        if settings and hmac.compare_digest(str(settings["bridge_token"] or ""), token):
            return "bridge-settings"
    return None
