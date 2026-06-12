import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.app.core.version import app_version


BACKEND_URL = os.getenv("CML_BACKEND_URL", "http://127.0.0.1:7343").rstrip("/")
BRIDGE_TOKEN = os.getenv("CML_BRIDGE_TOKEN", "")
MAX_TOOL_STRING_LENGTH = 50_000


def main() -> int:
    for line in sys.stdin:
        line = line.lstrip("\ufeff").lstrip("\xef\xbb\xbf")
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            response = handle_message(message)
            if response is None:
                continue
        except CMLBridgeApplicationError as exc:
            response = {
                "jsonrpc": "2.0",
                "id": exc.request_id,
                "error": {"code": exc.code, "message": exc.message},
            }
        except Exception as exc:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32603, "message": str(exc)},
            }
        print(json.dumps(response), flush=True)
    return 0


def handle_message(message: dict) -> dict:
    method = message.get("method")
    request_id = message.get("id")
    if request_id is None:
        return None
    if method == "initialize":
        return result(
            request_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "cml-bridge", "version": app_version()},
            },
        )
    if method == "tools/list":
        return result(request_id, {"tools": tools()})
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        validation_error = validate_tool_arguments(name, arguments)
        if validation_error:
            return error(request_id, -32602, validation_error)
        if name == "get_cluster_context":
            return result(request_id, call_get_cluster_context(arguments, request_id))
        if name == "list_clusters":
            return result(request_id, call_list_clusters(request_id))
        if name == "log_external_turn":
            return result(request_id, call_log_external_turn(arguments, request_id))
        if name == "capture_external_artifact":
            return result(request_id, call_capture_external_artifact(arguments, request_id))
        return error(request_id, -32602, f"Unknown CML tool: {name}")
    return error(request_id, -32601, f"Unknown method: {method}")


def tools() -> list[dict]:
    return [
        {
            "name": "get_cluster_context",
            "description": "Retrieve source-grounded context from the local CML Bridge.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "vault_id": {"type": "string"},
                    "cluster_id": {"type": "string"},
                    "limit": {"type": "number"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "list_clusters",
            "description": "List clusters visible to the local CML backend.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "log_external_turn",
            "description": "Save an outside model prompt/response transcript into an allowed CML vault or cluster.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "vault_id": {"type": "string"},
                    "cluster_id": {"type": "string"},
                    "user_prompt": {"type": "string"},
                    "model_response": {"type": "string"},
                    "context_request_id": {"type": "string"},
                    "model_name": {"type": "string"},
                },
                "required": ["user_prompt", "model_response"],
            },
        },
        {
            "name": "capture_external_artifact",
            "description": "Save an outside model artifact such as generated notes, code, or analysis into CML.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "vault_id": {"type": "string"},
                    "cluster_id": {"type": "string"},
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "artifact_type": {"type": "string"},
                },
                "required": ["title", "content"],
            },
        },
    ]


def call_get_cluster_context(arguments: dict, request_id) -> dict:
    payload = {
        "query": arguments.get("query", ""),
        "vault_id": arguments.get("vault_id"),
        "cluster_id": arguments.get("cluster_id"),
        "limit": int(arguments.get("limit") or 5),
        "client_name": "cml-mcp",
    }
    data = http_json(
        "/api/v1/bridge/context",
        method="POST",
        payload=payload,
        headers={"x-cml-bridge-token": BRIDGE_TOKEN},
        request_id=request_id,
    )
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(data, indent=2),
            }
        ]
    }


def call_list_clusters(request_id) -> dict:
    data = http_json(
        "/api/v1/bridge/clusters",
        headers={"x-cml-bridge-token": BRIDGE_TOKEN},
        request_id=request_id,
    )
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(data, indent=2),
            }
        ]
    }


def call_log_external_turn(arguments: dict, request_id) -> dict:
    payload = {
        "vault_id": arguments.get("vault_id"),
        "cluster_id": arguments.get("cluster_id"),
        "client_name": "cml-mcp",
        "user_prompt": arguments.get("user_prompt", ""),
        "model_response": arguments.get("model_response", ""),
        "context_request_id": arguments.get("context_request_id"),
        "model_name": arguments.get("model_name"),
        "metadata": arguments.get("metadata") or {},
    }
    data = http_json(
        "/api/v1/bridge/external-turn",
        method="POST",
        payload=payload,
        headers={"x-cml-bridge-token": BRIDGE_TOKEN},
        request_id=request_id,
    )
    return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}


def call_capture_external_artifact(arguments: dict, request_id) -> dict:
    payload = {
        "vault_id": arguments.get("vault_id"),
        "cluster_id": arguments.get("cluster_id"),
        "client_name": "cml-mcp",
        "title": arguments.get("title", ""),
        "content": arguments.get("content", ""),
        "artifact_type": arguments.get("artifact_type") or "generated_text",
        "metadata": arguments.get("metadata") or {},
    }
    data = http_json(
        "/api/v1/bridge/artifacts",
        method="POST",
        payload=payload,
        headers={"x-cml-bridge-token": BRIDGE_TOKEN},
        request_id=request_id,
    )
    return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}


def validate_tool_arguments(name, arguments) -> str | None:
    if not isinstance(name, str) or not name:
        return "Tool name is required."
    if not isinstance(arguments, dict):
        return "Tool arguments must be an object."
    for key, value in arguments.items():
        if isinstance(value, str) and len(value) > MAX_TOOL_STRING_LENGTH:
            return f"Tool argument is too large: {key}"
    if name == "get_cluster_context" and not str(arguments.get("query") or "").strip():
        return "get_cluster_context requires query."
    if name == "log_external_turn":
        if not str(arguments.get("user_prompt") or "").strip():
            return "log_external_turn requires user_prompt."
        if not str(arguments.get("model_response") or "").strip():
            return "log_external_turn requires model_response."
    if name == "capture_external_artifact":
        if not str(arguments.get("title") or "").strip():
            return "capture_external_artifact requires title."
        if not str(arguments.get("content") or "").strip():
            return "capture_external_artifact requires content."
    return None


def http_json(
    path: str,
    method: str = "GET",
    payload: dict | None = None,
    headers: dict | None = None,
    request_id=None,
):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        BACKEND_URL + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = ""
        try:
            body = json.loads(exc.read().decode("utf-8"))
            detail = str(body.get("detail") or "")
        except Exception:
            detail = str(exc)
        raise CMLBridgeApplicationError(request_id, app_error_code(detail), detail or "bridge_request_failed") from exc
    except URLError as exc:
        raise CMLBridgeApplicationError(request_id, 1005, f"CML backend is not reachable: {exc.reason}") from exc


def result(request_id, value: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": value}


def error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


class CMLBridgeApplicationError(RuntimeError):
    def __init__(self, request_id, code: int, message: str) -> None:
        super().__init__(message)
        self.request_id = request_id
        self.code = code
        self.message = message


def app_error_code(detail: str) -> int:
    return {
        "no_active_vault": 1001,
        "bridge_disabled": 1002,
        "bridge_token_invalid": 1003,
        "bridge_shared_token_disabled": 1003,
        "vault_not_allowed": 1004,
        "cluster_not_allowed": 1004,
        "bridge_rate_limited": 1006,
        "vault_not_found": 1003,
        "cluster_not_found": 1007,
    }.get(detail, 1000)


if __name__ == "__main__":
    sys.exit(main())
