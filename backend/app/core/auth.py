import hmac

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.app.core.config import get_settings


PUBLIC_PATHS = {
    "/health",
    "/openapi.json",
    "/docs",
    "/redoc",
}

def _api_path(api_prefix: str, suffix: str) -> str:
    return f"{api_prefix.rstrip('/')}/{suffix.lstrip('/')}"


def _is_public_path(path: str, method: str, api_prefix: str = "/api/v1") -> bool:
    if path in PUBLIC_PATHS:
        return True
    extension_public_paths = {
        ("GET", _api_path(api_prefix, "/extension/status")),
        ("POST", _api_path(api_prefix, "/extension/capture")),
        ("POST", _api_path(api_prefix, "/extension/capture-upload")),
    }
    if (method.upper(), path) in extension_public_paths:
        return True
    public_bridge_prefixes = (
        _api_path(api_prefix, "/bridge/context"),
        _api_path(api_prefix, "/bridge/clusters"),
        _api_path(api_prefix, "/bridge/external-turn"),
        _api_path(api_prefix, "/bridge/artifacts"),
    )
    for prefix in public_bridge_prefixes:
        if path == prefix or path.startswith(f"{prefix}/"):
            return True
    if method.upper() == "POST" and path == _api_path(api_prefix, "/bridge/approval-requests"):
        return True
    approval_status_prefix = _api_path(api_prefix, "/bridge/approval-requests")
    if method.upper() == "GET" and path.startswith(f"{approval_status_prefix}/") and path.endswith("/status"):
        return True
    return False


class LocalApiAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        token = settings.api_token
        if _is_public_path(request.url.path, request.method, settings.api_prefix):
            return await call_next(request)
        if not token:
            if settings.allow_unauthenticated_api:
                return await call_next(request)
            return JSONResponse({"detail": "Local API token is not configured"}, status_code=503)

        supplied = request.headers.get("x-cml-api-token", "")
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            supplied = authorization[7:].strip()
        if not hmac.compare_digest(supplied, token):
            return JSONResponse({"detail": "Missing or invalid local API token"}, status_code=401)
        return await call_next(request)
