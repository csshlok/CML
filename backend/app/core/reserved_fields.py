import json

from starlette.middleware.base import BaseHTTPMiddleware

from backend.app.core.config import get_settings


def _api_path(api_prefix: str, suffix: str) -> str:
    return f"{api_prefix.rstrip('/')}/{suffix.lstrip('/')}"


def chat_context_paths(api_prefix: str) -> set[str]:
    return {
        _api_path(api_prefix, "/chat/context"),
        _api_path(api_prefix, "/chat/context/stream"),
    }


class ReservedChatFieldMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        settings = get_settings()
        if request.method.upper() == "POST" and request.url.path in chat_context_paths(settings.api_prefix):
            body = await request.body()
            try:
                json.loads(body.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                async def receive():
                    return {"type": "http.request", "body": body, "more_body": False}
                request._receive = receive
                return await call_next(request)

            async def receive():
                return {"type": "http.request", "body": body, "more_body": False}
            request._receive = receive
        return await call_next(request)
