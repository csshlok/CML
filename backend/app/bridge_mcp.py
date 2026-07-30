import json
import os
import socket
import sys
import threading
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.app.core.version import app_version
from backend.app.core.context_packets import build_bridge_context_packet, packet_telemetry
from backend.app.core.mcp_features import effective_mcp_capability_profile
from backend.app.bridge_mcp_tools import (
    normalize_capability_profile,
    tools_for_profile,
    validate_tool_arguments as validate_contract_arguments,
)
from backend.app.bridge_mcp_stdio import ConcurrentMCPRuntime, RequestCancellation, run_stdio


def _normalize_api_prefix(value: str) -> str:
    raw = str(value or "/api/v1").strip()
    prefixed = raw if raw.startswith("/") else f"/{raw}"
    return prefixed.rstrip("/") or "/api/v1"


BACKEND_URL = os.getenv("CML_BACKEND_URL", "http://127.0.0.1:7343").rstrip("/")
BRIDGE_TOKEN = os.getenv("CML_BRIDGE_TOKEN", "")
API_PREFIX = _normalize_api_prefix(os.getenv("CML_API_PREFIX", "/api/v1"))
MAX_STDIN_MESSAGE_BYTES = 1_048_576
MAX_BACKEND_RESPONSE_BYTES = 2_097_152
MAX_TOOL_OUTPUT_BYTES = 524_288
SUPPORTED_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05", "2024-10-07")
CAPABILITY_PROFILE = effective_mcp_capability_profile(
    normalize_capability_profile(os.getenv("CML_MCP_CAPABILITY_PROFILE") or "read_write")
)
_REQUEST_CONTEXT = threading.local()


def main() -> int:
    return run_stdio()


def _application_error_response(exc) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": exc.request_id,
        "error": {
            "code": exc.code,
            "message": exc.message,
            "data": {
                "error_code": exc.error_code,
                "retriable": exc.retriable,
                "correlation_id": str(exc.request_id) if exc.request_id is not None else "",
            },
        },
    }


def handle_message(message: dict) -> dict | None:
    if not isinstance(message, dict):
        return error(None, -32600, "Request must be a JSON object.")
    method = message.get("method")
    request_id = message.get("id")
    if request_id is None:
        return None
    if method == "initialize":
        requested_version = str((message.get("params") or {}).get("protocolVersion") or SUPPORTED_PROTOCOL_VERSIONS[-1])
        negotiated_version = (
            requested_version
            if requested_version in SUPPORTED_PROTOCOL_VERSIONS
            else SUPPORTED_PROTOCOL_VERSIONS[0]
        )
        return result(
            request_id,
            {
                "protocolVersion": negotiated_version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "cml-bridge", "version": app_version()},
            },
        )
    if method == "tools/list":
        return result(request_id, {"tools": tools()})
    if method == "tools/call":
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return error(request_id, -32602, "Tool call parameters must be an object.")
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
            return result(request_id, call_list_clusters(arguments, request_id))
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
    return tools_for_profile(CAPABILITY_PROFILE)


def call_get_cluster_context(arguments: dict, request_id) -> dict:
    output_format = str(arguments.get("format") or "packet").strip().lower() or "packet"
    debug = bool(arguments.get("debug"))
    payload = {
        "query": arguments.get("query", ""),
        "vault_id": arguments.get("vault_id"),
        "cluster_id": arguments.get("cluster_id"),
        "unclustered_only": bool(arguments.get("unclustered_only")),
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


def call_list_clusters(arguments: dict | None, request_id) -> dict:
    arguments = arguments or {}
    query = _query_string(
        limit=int(arguments.get("limit") or 100),
        cursor=arguments.get("cursor"),
    )
    data = http_json(
        f"{api_path('/bridge/clusters')}{query}",
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
        limit=int(arguments.get("limit") or 100),
        cursor=arguments.get("cursor"),
    )
    data = http_json(
        f"{api_path('/bridge/reviews/page')}{query}",
        headers={"x-cml-bridge-token": BRIDGE_TOKEN},
        request_id=request_id,
    )
    page = data if isinstance(data, dict) else {"items": data, "next_cursor": None, "has_more": False}
    raw_text = json.dumps(data, indent=2, ensure_ascii=False)
    return {
        "content": [
            {
                "type": "text",
                "text": raw_text if output_format == "json" or debug else _format_reviews_summary(page.get("items", []), page=page),
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
        payload={
            "approved": bool(arguments.get("approved")),
            "expected_updated_at": arguments.get("expected_updated_at"),
            "idempotency_key": arguments.get("idempotency_key"),
        },
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
        cursor=arguments.get("cursor"),
    )
    data = http_json(
        f"{api_path('/bridge/captures/page')}{query}",
        headers={"x-cml-bridge-token": BRIDGE_TOKEN},
        request_id=request_id,
    )
    page = data if isinstance(data, dict) else {"items": data, "next_cursor": None, "has_more": False}
    raw_text = json.dumps(data, indent=2, ensure_ascii=False)
    return {
        "content": [
            {
                "type": "text",
                "text": raw_text if output_format == "json" or debug else _format_captures_summary(page.get("items", []), page=page),
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
        "idempotency_key": arguments.get("idempotency_key"),
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
        "idempotency_key": arguments.get("idempotency_key"),
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
    return validate_contract_arguments(name, arguments, profile=CAPABILITY_PROFILE)


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
            cancellation = getattr(_REQUEST_CONTEXT, "cancellation", None)
            if cancellation:
                cancellation.add_closer(response.close)
            try:
                if cancellation and cancellation.is_set():
                    raise CMLBridgeApplicationError(
                        request_id,
                        -32800,
                        "Request cancelled.",
                        error_code="cancelled",
                        retriable=True,
                    )
                response_bytes = response.read(MAX_BACKEND_RESPONSE_BYTES + 1)
            finally:
                if cancellation:
                    cancellation.remove_closer(response.close)
            if len(response_bytes) > MAX_BACKEND_RESPONSE_BYTES:
                raise CMLBridgeApplicationError(
                    request_id,
                    1008,
                    "Bridge response is too large.",
                    error_code="request_too_large",
                    retriable=False,
                )
            return json.loads(response_bytes.decode("utf-8"))
    except HTTPError as exc:
        detail = ""
        try:
            body = json.loads(exc.read().decode("utf-8"))
            detail = str(body.get("detail") or "")
        except Exception:
            detail = str(exc)
        error_code, safe_message, retriable = safe_application_error(detail)
        raise CMLBridgeApplicationError(
            request_id,
            app_error_code(detail),
            safe_message,
            error_code=error_code,
            retriable=retriable,
        ) from exc
    except URLError as exc:
        if isinstance(getattr(exc, "reason", None), (TimeoutError, socket.timeout)):
            raise CMLBridgeApplicationError(
                request_id,
                1005,
                "Vault took too long to respond. Try again.",
                error_code="backend_timeout",
                retriable=True,
            ) from exc
        raise CMLBridgeApplicationError(
            request_id,
            1005,
            "Vault is not reachable. Open Vault and try again.",
            error_code="backend_unavailable",
            retriable=True,
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise CMLBridgeApplicationError(
            request_id,
            1005,
            "Vault took too long to respond. Try again.",
            error_code="backend_timeout",
            retriable=True,
        ) from exc
    except ConnectionResetError as exc:
        raise CMLBridgeApplicationError(
            request_id,
            1005,
            "Vault is not reachable. Open Vault and try again.",
            error_code="backend_unavailable",
            retriable=True,
        ) from exc


def api_path(suffix: str) -> str:
    return f"{API_PREFIX.rstrip('/')}/{suffix.lstrip('/')}"


def result(request_id, value: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": _bounded_tool_output(value)}


def error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


class CMLBridgeApplicationError(RuntimeError):
    def __init__(
        self,
        request_id,
        code: int,
        message: str,
        *,
        error_code: str = "internal_error",
        retriable: bool = False,
    ) -> None:
        super().__init__(message)
        self.request_id = request_id
        self.code = code
        self.message = message
        self.error_code = error_code
        self.retriable = retriable


def app_error_code(detail: str) -> int:
    return {
        "no_active_vault": 1001,
        "bridge_disabled": 1002,
        "bridge_token_invalid": 1003,
        "bridge_shared_token_disabled": 1003,
        "vault_not_allowed": 1004,
        "cluster_not_allowed": 1004,
        "bridge_rate_limited": 1006,
        "capability_denied": 1004,
        "scope_denied": 1004,
        "vault_not_found": 1003,
        "cluster_not_found": 1007,
        "idempotency_key_reused": 1009,
        "idempotency_request_in_progress": 1009,
        "bridge_review_changed": 1009,
    }.get(detail, 1000)


def safe_application_error(detail: str) -> tuple[str, str, bool]:
    mapping = {
        "no_active_vault": ("no_active_vault", "No library is allowed for this connection.", False),
        "bridge_disabled": ("bridge_disabled", "Bridge is turned off in Vault.", False),
        "bridge_token_invalid": ("client_revoked", "This connection is no longer authorized.", False),
        "bridge_shared_token_disabled": ("client_revoked", "This connection must be paired again.", False),
        "vault_not_allowed": ("scope_denied", "This library is outside the allowed scope.", False),
        "cluster_not_allowed": ("scope_denied", "This cluster is outside the allowed scope.", False),
        "scope_denied": ("scope_denied", "This item is outside the allowed scope.", False),
        "capability_denied": ("capability_denied", "This connection has read-only access.", False),
        "bridge_rate_limited": ("rate_limited", "Too many requests. Try again shortly.", True),
        "vault_not_found": ("vault_missing", "The requested library is no longer available.", False),
        "cluster_not_found": ("cluster_missing", "The requested cluster is no longer available.", False),
        "bridge_review_not_found": ("conflict", "That review is no longer available.", False),
        "bridge_review_changed": ("conflict", "That review changed. Refresh it before deciding.", False),
        "idempotency_key_reused": (
            "conflict",
            "This request key was already used for different content.",
            False,
        ),
        "idempotency_request_in_progress": (
            "conflict",
            "This request is already being processed.",
            True,
        ),
    }
    return mapping.get(detail, ("internal_error", "Vault could not complete this request.", False))


def _bounded_tool_output(value: dict) -> dict:
    content = value.get("content") if isinstance(value, dict) else None
    if not isinstance(content, list):
        return value
    if len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= MAX_TOOL_OUTPUT_BYTES:
        return value
    marker = "\n\n[Output shortened. Request a smaller page or context limit.]"
    bounded: list = []
    base = {
        **value,
        "content": bounded,
        "_meta": {**value.get("_meta", {}), "output_bounded": True},
    }
    for item in content:
        candidate = [*bounded, item]
        if len(
            json.dumps({**base, "content": candidate}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ) <= MAX_TOOL_OUTPUT_BYTES:
            bounded.append(item)
            continue
        if not isinstance(item, dict) or item.get("type") != "text" or not isinstance(item.get("text"), str):
            break
        encoded = item["text"].encode("utf-8")
        low, high = 0, len(encoded)
        best = marker
        while low <= high:
            midpoint = (low + high) // 2
            clipped = encoded[:midpoint].decode("utf-8", errors="ignore") + marker
            trial = [*bounded, {**item, "text": clipped}]
            size = len(
                json.dumps({**base, "content": trial}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
            if size <= MAX_TOOL_OUTPUT_BYTES:
                best = clipped
                low = midpoint + 1
            else:
                high = midpoint - 1
        bounded.append({**item, "text": best})
        break
    if not bounded:
        bounded.append({"type": "text", "text": marker.strip()})
    return base


def _format_context_packet(data: dict, *, raw_text: str) -> str:
    packet_text = str(data.get("packet_text") or "").strip()
    if packet_text:
        return packet_text
    packet = build_bridge_context_packet(
        query=str(data.get("query") or ""),
        context_request_id=str(data.get("context_request_id") or "") or None,
        selected_clusters=[item for item in data.get("selected_clusters") or [] if isinstance(item, dict)],
        citations=[item for item in data.get("citations") or [] if isinstance(item, dict)],
        source_snippets=[item for item in data.get("source_snippets") or [] if isinstance(item, dict)],
        warnings=[str(item).strip() for item in data.get("warnings") or [] if str(item).strip()],
        memory_items=[item for item in data.get("memory_items") or [] if isinstance(item, dict)],
        working_memory=data.get("working_memory") or {},
        retrieval_authority=bool(data.get("retrieval_authority", True)),
        cluster_profile=data.get("cluster_profile") or {},
        token_estimate=data.get("token_estimate") or {},
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


def _format_reviews_summary(data: list[dict], *, page: dict | None = None) -> str:
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
    if page and page.get("has_more") and page.get("next_cursor"):
        lines.append(f"- More results are available. Call this tool again with cursor: {page['next_cursor']}")
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


def _format_captures_summary(data: list[dict], *, page: dict | None = None) -> str:
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
    if page and page.get("has_more") and page.get("next_cursor"):
        lines.append(f"- More results are available. Call this tool again with cursor: {page['next_cursor']}")
    return "\n".join(lines)


def _query_string(**params: object) -> str:
    filtered = {key: value for key, value in params.items() if value is not None and value != ""}
    if not filtered:
        return ""
    return f"?{urlencode(filtered)}"


if __name__ == "__main__":
    sys.exit(main())
