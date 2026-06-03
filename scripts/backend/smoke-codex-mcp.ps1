$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}

$code = @'
import json
from backend.app import bridge_mcp

calls = []

def fake_http_json(path, method="GET", payload=None, headers=None, request_id=None):
    calls.append({"path": path, "method": method, "payload": payload})
    if path.endswith("/bridge/context"):
        return {"query": payload["query"], "selected_clusters": [], "source_snippets": [], "warnings": []}
    if path.endswith("/bridge/clusters"):
        return {"clusters": []}
    if path.endswith("/bridge/external-turn"):
        return {"source_id": "source-codex-turn", "vault_id": payload.get("vault_id") or "vault-1", "source_type": "external_transcript", "indexed": True, "warnings": []}
    if path.endswith("/bridge/artifacts"):
        return {"source_id": "source-codex-artifact", "vault_id": payload.get("vault_id") or "vault-1", "source_type": "external_artifact", "indexed": True, "warnings": []}
    raise AssertionError(path)

bridge_mcp.http_json = fake_http_json
messages = [
    {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "get_cluster_context", "arguments": {"query": "codex smoke"}}},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "log_external_turn", "arguments": {"user_prompt": "p", "model_response": "r"}}},
    {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "capture_external_artifact", "arguments": {"title": "artifact", "content": "body"}}},
    {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "log_external_turn", "arguments": {"user_prompt": "missing response"}}},
]
responses = [bridge_mcp.handle_message(message) for message in messages]
print(json.dumps({
    "codex_style_jsonrpc": True,
    "responses": responses,
    "http_calls": calls,
    "malformed_call_rejected": responses[-1]["error"]["code"] == -32602,
}, indent=2))
'@

$code | & $python -
