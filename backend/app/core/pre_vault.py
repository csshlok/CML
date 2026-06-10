from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.app.core.config import get_settings

PRE_VAULT_SUFFIXES = (
    "/health",
    "/docs",
    "/openapi.json",
)

API_PRE_VAULT_SUFFIXES = (
    "/models",
    "/jobs/status",
    "/diagnostics",
    "/system/startup-status",
    "/system/preflight",
    "/system/hardware",
    "/system/ocr",
    "/system/vault-safety",
    "/extension/status",
)


def _api_path(api_prefix: str, suffix: str) -> str:
    return f"{api_prefix.rstrip('/')}/{suffix.lstrip('/')}"


def allowed_pre_vault_paths(api_prefix: str) -> tuple[str, ...]:
    return (
        *PRE_VAULT_SUFFIXES,
        *(_api_path(api_prefix, suffix) for suffix in API_PRE_VAULT_SUFFIXES),
    )


class BackendModeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        settings = get_settings()
        if settings.backend_mode != "pre_vault":
            return await call_next(request)
        path = request.url.path
        if any(path == allowed or path.startswith(f"{allowed}/") for allowed in allowed_pre_vault_paths(settings.api_prefix)):
            return await call_next(request)
        return JSONResponse(
            {"detail": "Vault not initialized. Finish setup before using vault, source, chat, search, or Bridge APIs."},
            status_code=409,
        )
