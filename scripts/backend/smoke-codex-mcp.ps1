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
approved = False

def fake_http_json(path, method="GET", payload=None, headers=None, request_id=None):
    global approved
    calls.append({"path": path, "method": method, "payload": payload})
    if path.endswith("/bridge/context"):
        return {"query": payload["query"], "selected_clusters": [], "source_snippets": [], "warnings": []}
    if path.endswith("/bridge/clusters"):
        return {"clusters": []}
    if path.endswith("/bridge/external-turn"):
        return {
            "source_id": "source-codex-turn",
            "vault_id": payload.get("vault_id") or "vault-1",
            "source_type": "external_transcript",
            "indexed": True,
            "quality_state": "partially_grounded",
            "review_required": True,
            "trust_tier": "external_capture",
            "reasons": ["matched_source_title"],
            "security_labels": ["review_needed", "partial_external"],
            "warnings": [],
        }
    if path.endswith("/bridge/artifacts"):
        return {
            "source_id": "source-codex-artifact",
            "vault_id": payload.get("vault_id") or "vault-1",
            "source_type": "external_artifact",
            "indexed": True,
            "quality_state": "user_artifact",
            "review_required": False,
            "trust_tier": "external_capture",
            "reasons": ["explicit_artifact_capture"],
            "security_labels": ["lora_excluded"],
            "warnings": [],
        }
    if "/bridge/reviews/" in path and method == "POST":
        approved = bool(payload.get("approved"))
        return {
            "source_id": "source-codex-turn",
            "title": "External model turn - cml-mcp",
            "quality_state": "partially_grounded",
            "approved": approved,
            "trust_tier": "trusted_reviewed" if approved else "external_capture",
            "reasons": ["matched_source_title"],
            "security_labels": [] if approved else ["review_needed", "partial_external"],
        }
    if path.endswith("/bridge/reviews?pending_only=true"):
        return [] if approved else [
            {
                "source_id": "source-codex-turn",
                "title": "External model turn - cml-mcp",
                "quality_state": "partially_grounded",
                "approved": False,
                "trust_tier": "external_capture",
            }
        ]
    if path.endswith("/bridge/captures?limit=50"):
        return [
            {
                "source_id": "source-codex-turn",
                "title": "External model turn - cml-mcp",
                "source_type": "external_transcript",
                "quality_state": "partially_grounded",
                "approved": approved,
            },
            {
                "source_id": "source-codex-artifact",
                "title": "artifact",
                "source_type": "external_artifact",
                "quality_state": "user_artifact",
                "approved": False,
            },
        ]
    raise AssertionError(path)

bridge_mcp.http_json = fake_http_json
messages = [
    {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "get_cluster_context", "arguments": {"query": "codex smoke"}}},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "log_external_turn", "arguments": {"user_prompt": "p", "model_response": "r"}}},
    {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "capture_external_artifact", "arguments": {"title": "artifact", "content": "body"}}},
    {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "list_writeback_reviews", "arguments": {}}},
    {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "decide_writeback_review", "arguments": {"source_id": "source-codex-turn", "approved": True}}},
    {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "list_captures", "arguments": {}}},
    {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "log_external_turn", "arguments": {"user_prompt": "missing response"}}},
]
responses = [bridge_mcp.handle_message(message) for message in messages]
print(json.dumps({
    "codex_style_jsonrpc": True,
    "responses": responses,
    "http_calls": calls,
    "review_queue_checked": "CML Writeback Review Queue" in responses[4]["result"]["content"][0]["text"],
    "review_approved": "Approved: yes" in responses[5]["result"]["content"][0]["text"],
    "captures_listed": "CML Recent Captures" in responses[6]["result"]["content"][0]["text"],
    "malformed_call_rejected": responses[-1]["error"]["code"] == -32602,
}, indent=2))
'@

$code | & $python -
