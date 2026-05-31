import json

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

CHAT_CONTEXT_PATHS = {
    "/api/v1/chat/context",
    "/api/v1/chat/context/stream",
}


class ReservedChatFieldMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.method.upper() == "POST" and request.url.path in CHAT_CONTEXT_PATHS:
            body = await request.body()
            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                async def receive():
                    return {"type": "http.request", "body": body, "more_body": False}
                request._receive = receive
                return await call_next(request)
            if isinstance(payload, dict) and "complete_analysis" in payload:
                return JSONResponse(
                    {
                        "detail": (
                            "complete_analysis is reserved for future full-scope map/reduce. "
                            "Use expanded_analysis for the current broader-scoring mode."
                        )
                    },
                    status_code=501,
                )

            async def receive():
                return {"type": "http.request", "body": body, "more_body": False}
            request._receive = receive
        return await call_next(request)
