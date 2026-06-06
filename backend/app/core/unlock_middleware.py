from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.app.core.unlock_state import require_ready_for_request


class UnlockGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        try:
            require_ready_for_request(request.url.path, request.method)
        except Exception as exc:
            name = exc.__class__.__name__
            detail = str(exc)
            if name == "RepairRequiredError" or detail == "vault_repair_required":
                return JSONResponse({"detail": "vault_repair_required"}, status_code=423)
            if name == "UnlockRequiredError" or detail == "vault_unlock_required":
                return JSONResponse({"detail": "vault_unlock_required"}, status_code=423)
            raise
        return await call_next(request)
