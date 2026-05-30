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


class LocalApiAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        token = get_settings().api_token
        if not token or request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        supplied = request.headers.get("x-cml-api-token", "")
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            supplied = authorization[7:].strip()
        if supplied != token:
            return JSONResponse({"detail": "Missing or invalid local API token"}, status_code=401)
        return await call_next(request)
