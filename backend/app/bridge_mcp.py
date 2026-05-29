import json
import os
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen


BACKEND_URL = os.getenv("CML_BACKEND_URL", "http://127.0.0.1:7343").rstrip("/")
BRIDGE_TOKEN = os.getenv("CML_BRIDGE_TOKEN", "")


def main() -> int:
    for line in sys.stdin:
        line = line.lstrip("\ufeff").lstrip("\xef\xbb\xbf")
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            response = handle_message(message)
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
    if method == "initialize":
        return result(
            request_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "cml-bridge", "version": "0.1.0"},
            },
        )
    if method == "tools/list":
        return result(request_id, {"tools": tools()})
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name == "get_cluster_context":
            return result(request_id, call_get_cluster_context(arguments))
        if name == "list_clusters":
            return result(request_id, call_list_clusters())
        return error(request_id, -32602, f"Unknown CML tool: {name}")
    if method == "notifications/initialized":
        return result(request_id, {})
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
    ]


def call_get_cluster_context(arguments: dict) -> dict:
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
    )
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(data, indent=2),
            }
        ]
    }


def call_list_clusters() -> dict:
    data = http_json("/api/v1/clusters")
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(data, indent=2),
            }
        ]
    }


def http_json(path: str, method: str = "GET", payload: dict | None = None, headers: dict | None = None):
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
    except URLError as exc:
        return {"error": f"CML backend is not reachable: {exc.reason}"}


def result(request_id, value: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": value}


def error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


if __name__ == "__main__":
    sys.exit(main())
