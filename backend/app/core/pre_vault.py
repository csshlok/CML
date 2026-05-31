from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.app.core.config import get_settings

ALLOWED_PRE_VAULT_PATHS = (
    "/health",
    "/docs",
    "/openapi.json",
    "/api/v1/models",
    "/api/v1/jobs/status",
    "/api/v1/diagnostics",
    "/api/v1/system",
    "/api/v1/extension/status",
)


class BackendModeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        settings = get_settings()
        if settings.backend_mode != "pre_vault":
            return await call_next(request)
        path = request.url.path
        if any(path == allowed or path.startswith(f"{allowed}/") for allowed in ALLOWED_PRE_VAULT_PATHS):
            return await call_next(request)
        return JSONResponse(
            {"detail": "Vault not initialized. Finish setup before using vault, source, chat, search, or Bridge APIs."},
            status_code=409,
        )
