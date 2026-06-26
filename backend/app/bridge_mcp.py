import json
import os
import sys
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.app.core.version import app_version
from backend.app.core.context_packets import build_bridge_context_packet, packet_telemetry


def _normalize_api_prefix(value: str) -> str:
    raw = str(value or "/api/v1").strip()
    prefixed = raw if raw.startswith("/") else f"/{raw}"
    return prefixed.rstrip("/") or "/api/v1"


BACKEND_URL = os.getenv("CML_BACKEND_URL", "http://127.0.0.1:7343").rstrip("/")
BRIDGE_TOKEN = os.getenv("CML_BRIDGE_TOKEN", "")
API_PREFIX = _normalize_api_prefix(os.getenv("CML_API_PREFIX", "/api/v1"))
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
        if name == "expand_context_item":
            return result(request_id, call_expand_context_item(arguments, request_id))
        if name == "list_clusters":
            return result(request_id, call_list_clusters(request_id))
        if name == "list_writeback_reviews":
            return result(request_id, call_list_writeback_reviews(arguments, request_id))
        if name == "decide_writeback_review":
            return result(request_id, call_decide_writeback_review(arguments, request_id))
        if name == "list_captures":
            return result(request_id, call_list_captures(arguments, request_id))
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
                    "format": {"type": "string", "enum": ["packet", "json"]},
                    "debug": {"type": "boolean"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "expand_context_item",
            "description": "Expand one CML context packet handle into fuller source, page, or chunk text.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "handle": {"type": "string"},
                    "vault_id": {"type": "string"},
                    "cluster_id": {"type": "string"},
                    "mode": {"type": "string"},
                },
                "required": ["handle"],
            },
        },
        {
            "name": "list_clusters",
            "description": "List clusters visible to the local CML backend.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "list_writeback_reviews",
            "description": "List Bridge writeback reviews, especially downgraded captures that still need approval.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "vault_id": {"type": "string"},
                    "pending_only": {"type": "boolean"},
                    "format": {"type": "string", "enum": ["summary", "json"]},
                    "debug": {"type": "boolean"},
                },
            },
        },
        {
            "name": "decide_writeback_review",
            "description": "Approve or keep gated one downgraded Bridge writeback capture.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source_id": {"type": "string"},
                    "approved": {"type": "boolean"},
                    "format": {"type": "string", "enum": ["receipt", "json"]},
                    "debug": {"type": "boolean"},
                },
                "required": ["source_id", "approved"],
            },
        },
        {
            "name": "list_captures",
            "description": "List recent Bridge-stored external transcripts and artifacts with quality state.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "vault_id": {"type": "string"},
                    "limit": {"type": "number"},
                    "format": {"type": "string", "enum": ["summary", "json"]},
                    "debug": {"type": "boolean"},
                },
            },
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
                    "format": {"type": "string", "enum": ["receipt", "json"]},
                    "debug": {"type": "boolean"},
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
                    "format": {"type": "string", "enum": ["receipt", "json"]},
                    "debug": {"type": "boolean"},
                },
                "required": ["title", "content"],
            },
        },
    ]


def call_get_cluster_context(arguments: dict, request_id) -> dict:
    output_format = str(arguments.get("format") or "packet").strip().lower() or "packet"
    debug = bool(arguments.get("debug"))
    payload = {
        "query": arguments.get("query", ""),
        "vault_id": arguments.get("vault_id"),
        "cluster_id": arguments.get("cluster_id"),
        "limit": int(arguments.get("limit") or 5),
        "client_name": "cml-mcp",
    }
    data = http_json(
        api_path("/bridge/context"),
        method="POST",
        payload=payload,
        headers={"x-cml-bridge-token": BRIDGE_TOKEN},
        request_id=request_id,
    )
    raw_text = json.dumps(data, indent=2, ensure_ascii=False)
    return {
        "content": [
            {
                "type": "text",
                "text": raw_text if output_format == "json" or debug else _format_context_packet(data, raw_text=raw_text),
            }
        ]
    }


def call_list_clusters(request_id) -> dict:
    data = http_json(
        api_path("/bridge/clusters"),
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


def call_list_writeback_reviews(arguments: dict, request_id) -> dict:
    output_format = str(arguments.get("format") or "summary").strip().lower() or "summary"
    debug = bool(arguments.get("debug"))
    query = _query_string(
        vault_id=arguments.get("vault_id"),
        pending_only="true" if bool(arguments.get("pending_only", True)) else None,
    )
    data = http_json(
        f"{api_path('/bridge/reviews')}{query}",
        headers={"x-cml-bridge-token": BRIDGE_TOKEN},
        request_id=request_id,
    )
    raw_text = json.dumps(data, indent=2, ensure_ascii=False)
    return {
        "content": [
            {
                "type": "text",
                "text": raw_text if output_format == "json" or debug else _format_reviews_summary(data),
            }
        ]
    }


def call_decide_writeback_review(arguments: dict, request_id) -> dict:
    output_format = str(arguments.get("format") or "receipt").strip().lower() or "receipt"
    debug = bool(arguments.get("debug"))
    source_id = str(arguments.get("source_id") or "").strip()
    data = http_json(
        api_path(f"/bridge/reviews/{source_id}"),
        method="POST",
        payload={"approved": bool(arguments.get("approved"))},
        headers={"x-cml-bridge-token": BRIDGE_TOKEN},
        request_id=request_id,
    )
    raw_text = json.dumps(data, indent=2, ensure_ascii=False)
    return {
        "content": [
            {
                "type": "text",
                "text": raw_text if output_format == "json" or debug else _format_review_decision_receipt(data),
            }
        ]
    }


def call_list_captures(arguments: dict, request_id) -> dict:
    output_format = str(arguments.get("format") or "summary").strip().lower() or "summary"
    debug = bool(arguments.get("debug"))
    query = _query_string(
        vault_id=arguments.get("vault_id"),
        limit=int(arguments.get("limit") or 50),
    )
    data = http_json(
        f"{api_path('/bridge/captures')}{query}",
        headers={"x-cml-bridge-token": BRIDGE_TOKEN},
        request_id=request_id,
    )
    raw_text = json.dumps(data, indent=2, ensure_ascii=False)
    return {
        "content": [
            {
                "type": "text",
                "text": raw_text if output_format == "json" or debug else _format_captures_summary(data),
            }
        ]
    }


def call_expand_context_item(arguments: dict, request_id) -> dict:
    payload = {
        "handle": arguments.get("handle", ""),
        "vault_id": arguments.get("vault_id"),
        "cluster_id": arguments.get("cluster_id"),
        "mode": arguments.get("mode") or "full",
        "client_name": "cml-mcp",
    }
    data = http_json(
        api_path("/bridge/context/expand"),
        method="POST",
        payload=payload,
        headers={"x-cml-bridge-token": BRIDGE_TOKEN},
        request_id=request_id,
    )
    return {"content": [{"type": "text", "text": json.dumps(data, indent=2, ensure_ascii=False)}]}


def call_log_external_turn(arguments: dict, request_id) -> dict:
    output_format = str(arguments.get("format") or "receipt").strip().lower() or "receipt"
    debug = bool(arguments.get("debug"))
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
        api_path("/bridge/external-turn"),
        method="POST",
        payload=payload,
        headers={"x-cml-bridge-token": BRIDGE_TOKEN},
        request_id=request_id,
    )
    raw_text = json.dumps(data, indent=2, ensure_ascii=False)
    return {
        "content": [
            {
                "type": "text",
                "text": raw_text if output_format == "json" or debug else _format_capture_receipt(data, capture_kind="external_turn"),
            }
        ]
    }


def call_capture_external_artifact(arguments: dict, request_id) -> dict:
    output_format = str(arguments.get("format") or "receipt").strip().lower() or "receipt"
    debug = bool(arguments.get("debug"))
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
        api_path("/bridge/artifacts"),
        method="POST",
        payload=payload,
        headers={"x-cml-bridge-token": BRIDGE_TOKEN},
        request_id=request_id,
    )
    raw_text = json.dumps(data, indent=2, ensure_ascii=False)
    return {
        "content": [
            {
                "type": "text",
                "text": raw_text if output_format == "json" or debug else _format_capture_receipt(data, capture_kind="external_artifact"),
            }
        ]
    }


def validate_tool_arguments(name, arguments) -> str | None:
    if not isinstance(name, str) or not name:
        return "Tool name is required."
    if not isinstance(arguments, dict):
        return "Tool arguments must be an object."
    for key, value in arguments.items():
        if isinstance(value, str) and len(value) > MAX_TOOL_STRING_LENGTH:
            return f"Tool argument is too large: {key}"
    if name == "get_cluster_context":
        if not str(arguments.get("query") or "").strip():
            return "get_cluster_context requires query."
        requested_format = str(arguments.get("format") or "packet").strip().lower()
        if requested_format and requested_format not in {"packet", "json"}:
            return "get_cluster_context format must be packet or json."
    if name == "log_external_turn":
        if not str(arguments.get("user_prompt") or "").strip():
            return "log_external_turn requires user_prompt."
        if not str(arguments.get("model_response") or "").strip():
            return "log_external_turn requires model_response."
        requested_format = str(arguments.get("format") or "receipt").strip().lower()
        if requested_format and requested_format not in {"receipt", "json"}:
            return "log_external_turn format must be receipt or json."
    if name == "expand_context_item":
        if not str(arguments.get("handle") or "").strip():
            return "expand_context_item requires handle."
    if name == "list_writeback_reviews":
        requested_format = str(arguments.get("format") or "summary").strip().lower()
        if requested_format and requested_format not in {"summary", "json"}:
            return "list_writeback_reviews format must be summary or json."
    if name == "decide_writeback_review":
        if not str(arguments.get("source_id") or "").strip():
            return "decide_writeback_review requires source_id."
        if "approved" not in arguments or not isinstance(arguments.get("approved"), bool):
            return "decide_writeback_review requires boolean approved."
        requested_format = str(arguments.get("format") or "receipt").strip().lower()
        if requested_format and requested_format not in {"receipt", "json"}:
            return "decide_writeback_review format must be receipt or json."
    if name == "list_captures":
        requested_format = str(arguments.get("format") or "summary").strip().lower()
        if requested_format and requested_format not in {"summary", "json"}:
            return "list_captures format must be summary or json."
    if name == "capture_external_artifact":
        if not str(arguments.get("title") or "").strip():
            return "capture_external_artifact requires title."
        if not str(arguments.get("content") or "").strip():
            return "capture_external_artifact requires content."
        requested_format = str(arguments.get("format") or "receipt").strip().lower()
        if requested_format and requested_format not in {"receipt", "json"}:
            return "capture_external_artifact format must be receipt or json."
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


def api_path(suffix: str) -> str:
    return f"{API_PREFIX.rstrip('/')}/{suffix.lstrip('/')}"


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


def _format_context_packet(data: dict, *, raw_text: str) -> str:
    packet_text = str(data.get("packet_text") or "").strip()
    if packet_text:
        return packet_text
    packet = build_bridge_context_packet(
        query=str(data.get("query") or ""),
        context_request_id=str(data.get("context_request_id") or "") or None,
        selected_clusters=[item for item in data.get("selected_clusters") or [] if isinstance(item, dict)],
        source_snippets=[item for item in data.get("source_snippets") or [] if isinstance(item, dict)],
        warnings=[str(item).strip() for item in data.get("warnings") or [] if str(item).strip()],
        memory_items=[item for item in data.get("memory_items") or [] if isinstance(item, dict)],
        working_memory=data.get("working_memory") or {},
        retrieval_authority=bool(data.get("retrieval_authority", True)),
        expert_digest=data.get("expert_digest") or {},
        token_ledger=data.get("token_ledger") or {},
        bundle_status=data.get("bundle_status") or {},
    )
    telemetry = packet_telemetry(packet, raw_text=raw_text)
    return (
        f"{telemetry['packet_text']}\n\n"
        "Packet Telemetry\n"
        f"- Raw JSON bytes: {telemetry['raw_bytes']}\n"
        f"- Packet bytes: {telemetry['packet_bytes']}\n"
        f"- Approx savings vs raw JSON: {telemetry['savings_percent']:.1f}%"
    )


def _format_capture_receipt(data: dict, *, capture_kind: str) -> str:
    quality_state = str(data.get("quality_state") or "unknown")
    review_required = bool(data.get("review_required"))
    trust_tier = str(data.get("trust_tier") or "unknown")
    warnings = [str(item).strip() for item in data.get("warnings") or [] if str(item).strip()]
    reasons = [str(item).strip() for item in data.get("reasons") or [] if str(item).strip()]
    security_labels = [str(item).strip() for item in data.get("security_labels") or [] if str(item).strip()]
    title = "External Turn Saved" if capture_kind == "external_turn" else "External Artifact Saved"
    lines = [
        f"CML Capture Receipt: {title}",
        f"- Source ID: {data.get('source_id') or ''}",
        f"- Source type: {data.get('source_type') or capture_kind}",
        f"- Vault ID: {data.get('vault_id') or ''}",
    ]
    cluster_id = str(data.get("cluster_id") or "").strip()
    if cluster_id:
        lines.append(f"- Cluster ID: {cluster_id}")
    lines.extend(
        [
            f"- Quality state: {quality_state}",
            f"- Trust tier: {trust_tier}",
            f"- Review required: {'yes' if review_required else 'no'}",
            f"- Indexed: {'yes' if bool(data.get('indexed')) else 'no'}",
        ]
    )
    if reasons:
        lines.append("Reasons")
        lines.extend(f"- {reason}" for reason in reasons)
    if security_labels:
        lines.append("Security Labels")
        lines.extend(f"- {label}" for label in security_labels)
    if warnings:
        lines.append("Warnings")
        lines.extend(f"- {warning}" for warning in warnings)
    lines.append("Next Step")
    if review_required:
        lines.append("- Keep this capture as audit/history until a user reviews and approves it in CML.")
    elif quality_state == "user_artifact":
        lines.append("- This was stored as a user artifact, not auto-promoted as grounded memory.")
    else:
        lines.append("- This capture is available to CML with the trust state shown above.")
    return "\n".join(lines)


def _format_reviews_summary(data: list[dict]) -> str:
    rows = [item for item in data if isinstance(item, dict)]
    lines = ["CML Writeback Review Queue", f"- Review count: {len(rows)}"]
    if not rows:
        lines.append("- No downgraded writebacks need review right now.")
        return "\n".join(lines)
    for item in rows:
        source_id = str(item.get("source_id") or "")
        title = str(item.get("title") or "")
        quality_state = str(item.get("quality_state") or "unknown")
        trust_tier = str(item.get("trust_tier") or "unknown")
        approved = bool(item.get("approved"))
        lines.append(
            f"- {source_id}: {title} | quality={quality_state} | trust={trust_tier} | approved={'yes' if approved else 'no'}"
        )
    lines.append("Next Step")
    lines.append("- Use decide_writeback_review with one source_id after checking the capture in CML.")
    return "\n".join(lines)


def _format_review_decision_receipt(data: dict) -> str:
    lines = [
        "CML Writeback Review Decision",
        f"- Source ID: {data.get('source_id') or ''}",
        f"- Title: {data.get('title') or ''}",
        f"- Quality state: {data.get('quality_state') or 'unknown'}",
        f"- Approved: {'yes' if bool(data.get('approved')) else 'no'}",
        f"- Trust tier: {data.get('trust_tier') or 'unknown'}",
    ]
    reasons = [str(item).strip() for item in data.get("reasons") or [] if str(item).strip()]
    security_labels = [str(item).strip() for item in data.get("security_labels") or [] if str(item).strip()]
    if reasons:
        lines.append("Reasons")
        lines.extend(f"- {reason}" for reason in reasons)
    if security_labels:
        lines.append("Security Labels")
        lines.extend(f"- {label}" for label in security_labels)
    return "\n".join(lines)


def _format_captures_summary(data: list[dict]) -> str:
    rows = [item for item in data if isinstance(item, dict)]
    lines = ["CML Recent Captures", f"- Capture count: {len(rows)}"]
    if not rows:
        lines.append("- No external captures are stored yet.")
        return "\n".join(lines)
    for item in rows:
        lines.append(
            f"- {item.get('source_id') or ''}: {item.get('title') or ''} | type={item.get('source_type') or ''} | "
            f"quality={item.get('quality_state') or 'unknown'} | approved={'yes' if bool(item.get('approved')) else 'no'}"
        )
    return "\n".join(lines)


def _query_string(**params: object) -> str:
    filtered = {key: value for key, value in params.items() if value is not None and value != ""}
    if not filtered:
        return ""
    return f"?{urlencode(filtered)}"


if __name__ == "__main__":
    sys.exit(main())
