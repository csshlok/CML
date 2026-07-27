import hmac

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.app.core.config import get_settings
from backend.app.core.cli_auth import authenticate_session


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
        _api_path(api_prefix, "/bridge/captures"),
        _api_path(api_prefix, "/bridge/reviews"),
    )
    for prefix in public_bridge_prefixes:
        if path == prefix or path.startswith(f"{prefix}/"):
            return True
    if method.upper() == "POST" and path == _api_path(api_prefix, "/bridge/approval-requests"):
        return True
    cli_pairing_root = _api_path(api_prefix, "/cli-auth/pairing-challenges")
    if method.upper() == "POST" and path == cli_pairing_root:
        return True
    if method.upper() == "GET" and path.startswith(f"{cli_pairing_root}/") and path.endswith("/status"):
        return True
    if method.upper() == "POST" and path.startswith(f"{cli_pairing_root}/") and path.endswith("/consume"):
        return True
    if method.upper() == "POST" and path == _api_path(api_prefix, "/cli-auth/sessions"):
        return True
    approval_status_prefix = _api_path(api_prefix, "/bridge/approval-requests")
    if method.upper() == "GET" and path.startswith(f"{approval_status_prefix}/") and path.endswith("/status"):
        return True
    return False


class LocalApiAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        token = settings.api_token
        is_public = _is_public_path(request.url.path, request.method, settings.api_prefix)
        bridge_runtime_roots = tuple(
            _api_path(settings.api_prefix, suffix)
            for suffix in (
                "/bridge/context",
                "/bridge/clusters",
                "/bridge/external-turn",
                "/bridge/artifacts",
                "/bridge/captures",
                "/bridge/reviews",
            )
        )
        requires_bridge_token = any(
            request.url.path == root or request.url.path.startswith(f"{root}/")
            for root in bridge_runtime_roots
        )
        has_bridge_token = bool(request.headers.get("x-cml-bridge-token", ""))
        if is_public and (not requires_bridge_token or has_bridge_token):
            request.state.auth_kind = "bridge" if requires_bridge_token else "public"
            return await call_next(request)
        if not token:
            if settings.allow_unauthenticated_api:
                request.state.auth_kind = "desktop-development"
                return await call_next(request)
            return JSONResponse({"detail": "Local API token is not configured"}, status_code=503)

        supplied = request.headers.get("x-cml-api-token", "")
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            supplied = authorization[7:].strip()
        if hmac.compare_digest(supplied, token):
            request.state.auth_kind = "desktop"
            return await call_next(request)

        cli_context = authenticate_session(supplied)
        if cli_context is None:
            return JSONResponse({"detail": "Missing or invalid local API token"}, status_code=401)
        required_scope = _required_cli_scope(request.url.path, request.method, settings.api_prefix)
        if required_scope is None:
            return JSONResponse({"detail": "CLI access is not permitted for this endpoint"}, status_code=403)
        if required_scope and required_scope not in cli_context["scopes"]:
            return JSONResponse({"detail": f"Missing CLI scope: {required_scope}"}, status_code=403)
        request.state.auth_kind = "cli"
        request.state.cli_auth = cli_context
        return await call_next(request)


def _required_cli_scope(path: str, method: str, api_prefix: str) -> str | None:
    normalized_method = method.upper()
    if path == _api_path(api_prefix, "/cli-auth/me") and normalized_method == "GET":
        return ""
    projects_root = _api_path(api_prefix, "/projects")
    if path == projects_root:
        return "project:read" if normalized_method == "GET" else "project:write" if normalized_method == "POST" else None
    if not path.startswith(f"{projects_root}/"):
        return None
    suffix = path[len(projects_root) + 1 :]
    parts = [part for part in suffix.split("/") if part]
    if not parts:
        return None
    if len(parts) == 1:
        if normalized_method == "GET":
            return "project:read"
        if normalized_method in {"PATCH", "DELETE"}:
            return "project:write"
        return None
    section = parts[1]
    if section == "context" and normalized_method == "POST":
        return "context:read"
    if section == "links":
        return "project:read" if normalized_method == "GET" else "cluster:link" if normalized_method in {"POST", "DELETE"} else None
    if section in {"sync", "reindex", "cancel"} and normalized_method == "POST":
        return "project:write"
    if section in {"runs", "graph"} and normalized_method == "GET":
        return "project:read"
    return None
