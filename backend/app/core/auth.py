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

PUBLIC_BRIDGE_PREFIXES = (
    "/api/v1/bridge/context",
    "/api/v1/bridge/clusters",
    "/api/v1/bridge/external-turn",
    "/api/v1/bridge/artifacts",
)


def _is_public_path(path: str, method: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    for prefix in PUBLIC_BRIDGE_PREFIXES:
        if path == prefix or path.startswith(f"{prefix}/"):
            return True
    if method.upper() == "POST" and path == "/api/v1/bridge/approval-requests":
        return True
    if method.upper() == "GET" and path.startswith("/api/v1/bridge/approval-requests/") and path.endswith("/status"):
        return True
    return False


class LocalApiAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        token = settings.api_token
        if _is_public_path(request.url.path, request.method):
            return await call_next(request)
        if not token:
            if settings.allow_unauthenticated_api:
                return await call_next(request)
            return JSONResponse({"detail": "Local API token is not configured"}, status_code=503)

        supplied = request.headers.get("x-cml-api-token", "")
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            supplied = authorization[7:].strip()
        if supplied != token:
            return JSONResponse({"detail": "Missing or invalid local API token"}, status_code=401)
        return await call_next(request)
