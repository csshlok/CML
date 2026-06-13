import json

from starlette.middleware.base import BaseHTTPMiddleware

CHAT_CONTEXT_PATHS = {
    "/api/v1/chat/context",
    "/api/v1/chat/context/stream",
}


class ReservedChatFieldMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.method.upper() == "POST" and request.url.path in CHAT_CONTEXT_PATHS:
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
