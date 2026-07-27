"""Transport-independent MCP tool contracts and argument validation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

MAX_TOOL_STRING_LENGTH = 50_000
MAX_IDENTIFIER_LENGTH = 240
READ_ONLY_TOOLS = {
    "get_cluster_context",
    "expand_context_item",
    "list_clusters",
    "list_writeback_reviews",
    "list_captures",
}
WRITE_TOOLS = {
    "log_external_turn",
    "capture_external_artifact",
    "decide_writeback_review",
}
CAPABILITY_PROFILES = {"read_only", "read_write"}
FORBIDDEN_UNICODE_CONTROLS = {
    "\u061c",
    "\u200e",
    "\u200f",
    "\u202a",
    "\u202b",
    "\u202c",
    "\u202d",
    "\u202e",
    "\u2066",
    "\u2067",
    "\u2068",
    "\u2069",
}


def _string(*, maximum: int = MAX_IDENTIFIER_LENGTH, minimum: int = 0, enum: list[str] | None = None) -> dict:
    schema: dict[str, Any] = {"type": "string", "maxLength": maximum}
    if minimum:
        schema["minLength"] = minimum
    if enum is not None:
        schema["enum"] = enum
    return schema


def _object(properties: dict, required: list[str] | None = None) -> dict:
    schema = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _tool(
    name: str,
    description: str,
    schema: dict,
    *,
    read_only: bool,
    destructive: bool = False,
    idempotent: bool,
    open_world: bool = False,
) -> dict:
    return {
        "name": name,
        "description": description,
        "inputSchema": schema,
        "annotations": {
            "readOnlyHint": read_only,
            "destructiveHint": destructive,
            "idempotentHint": idempotent,
            "openWorldHint": open_world,
        },
        "_meta": {
            "cml/toolVersion": "1.0.0",
            "cml/capabilityProfile": "read_only" if read_only else "read_write",
        },
    }


TOOL_CONTRACTS = [
    _tool(
        "get_cluster_context",
        "Retrieve source-grounded context from allowed local Vault libraries.",
        _object(
            {
                "query": _string(maximum=8_000, minimum=1),
                "vault_id": _string(),
                "cluster_id": _string(),
                "limit": {"type": "integer", "minimum": 1, "maximum": 30},
                "format": _string(maximum=16, enum=["packet", "json"]),
                "debug": {"type": "boolean"},
            },
            ["query"],
        ),
        read_only=True,
        idempotent=True,
    ),
    _tool(
        "expand_context_item",
        "Expand one context handle within the currently allowed Vault scope.",
        _object(
            {
                "handle": _string(maximum=1_024, minimum=1),
                "vault_id": _string(),
                "cluster_id": _string(),
                "mode": _string(maximum=32, enum=["full", "page", "chunk"]),
            },
            ["handle"],
        ),
        read_only=True,
        idempotent=True,
    ),
    _tool(
        "list_clusters",
        "List clusters visible to this connection.",
        _object(
            {
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                "cursor": _string(maximum=2_048),
            }
        ),
        read_only=True,
        idempotent=True,
    ),
    _tool(
        "list_writeback_reviews",
        "List saved items that need local review.",
        _object(
            {
                "vault_id": _string(),
                "pending_only": {"type": "boolean"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                "cursor": _string(maximum=2_048),
                "format": _string(maximum=16, enum=["summary", "json"]),
                "debug": {"type": "boolean"},
            }
        ),
        read_only=True,
        idempotent=True,
    ),
    _tool(
        "decide_writeback_review",
        "Approve or keep one saved item gated after local review.",
        _object(
            {
                "source_id": _string(minimum=1),
                "approved": {"type": "boolean"},
                "expected_updated_at": _string(maximum=64),
                "idempotency_key": _string(maximum=240),
                "format": _string(maximum=16, enum=["receipt", "json"]),
                "debug": {"type": "boolean"},
            },
            ["source_id", "approved", "idempotency_key"],
        ),
        read_only=False,
        destructive=True,
        idempotent=True,
    ),
    _tool(
        "list_captures",
        "List recent transcripts and artifacts saved through this connection.",
        _object(
            {
                "vault_id": _string(),
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                "cursor": _string(maximum=2_048),
                "format": _string(maximum=16, enum=["summary", "json"]),
                "debug": {"type": "boolean"},
            }
        ),
        read_only=True,
        idempotent=True,
    ),
    _tool(
        "log_external_turn",
        "Save a model prompt and response into an allowed Vault library.",
        _object(
            {
                "vault_id": _string(),
                "cluster_id": _string(),
                "user_prompt": _string(maximum=MAX_TOOL_STRING_LENGTH, minimum=1),
                "model_response": _string(maximum=MAX_TOOL_STRING_LENGTH, minimum=1),
                "context_request_id": _string(),
                "model_name": _string(),
                "idempotency_key": _string(maximum=240),
                "format": _string(maximum=16, enum=["receipt", "json"]),
                "debug": {"type": "boolean"},
            },
            ["user_prompt", "model_response", "idempotency_key"],
        ),
        read_only=False,
        idempotent=True,
    ),
    _tool(
        "capture_external_artifact",
        "Save generated notes, code, or analysis into an allowed Vault library.",
        _object(
            {
                "vault_id": _string(),
                "cluster_id": _string(),
                "title": _string(maximum=240, minimum=1),
                "content": _string(maximum=MAX_TOOL_STRING_LENGTH, minimum=1),
                "artifact_type": _string(maximum=120),
                "idempotency_key": _string(maximum=240),
                "format": _string(maximum=16, enum=["receipt", "json"]),
                "debug": {"type": "boolean"},
            },
            ["title", "content", "idempotency_key"],
        ),
        read_only=False,
        idempotent=True,
    ),
]
_CONTRACTS_BY_NAME = {tool["name"]: tool for tool in TOOL_CONTRACTS}


def normalize_capability_profile(value: str | None) -> str:
    normalized = str(value or "read_only").strip().lower()
    return normalized if normalized in CAPABILITY_PROFILES else "read_only"


def tools_for_profile(profile: str | None = None) -> list[dict]:
    normalized = normalize_capability_profile(profile)
    allowed = READ_ONLY_TOOLS if normalized == "read_only" else READ_ONLY_TOOLS | WRITE_TOOLS
    return [deepcopy(tool) for tool in TOOL_CONTRACTS if tool["name"] in allowed]


def validate_tool_arguments(name: object, arguments: object, *, profile: str | None = None) -> str | None:
    if not isinstance(name, str) or not name:
        return "Tool name is required."
    contract = _CONTRACTS_BY_NAME.get(name)
    if contract is None:
        return f"Unknown CML tool: {name}"
    normalized_profile = normalize_capability_profile(profile)
    if normalized_profile == "read_only" and name in WRITE_TOOLS:
        return f"Tool is not available for read-only access: {name}"
    if not isinstance(arguments, dict):
        return "Tool arguments must be an object."

    schema = contract["inputSchema"]
    properties = schema["properties"]
    unknown = sorted(set(arguments) - set(properties))
    if unknown:
        return f"Unexpected tool argument: {unknown[0]}"
    for required in schema.get("required", []):
        value = arguments.get(required)
        if value is None or (isinstance(value, str) and not value.strip()):
            return _required_message(name, required)
    for key, value in arguments.items():
        field_error = _validate_value(key, value, properties[key])
        if field_error:
            return field_error
    return None


def _required_message(name: str, field: str) -> str:
    if name == "get_cluster_context" and field == "query":
        return "get_cluster_context requires query."
    if name == "expand_context_item" and field == "handle":
        return "expand_context_item requires handle."
    if name == "log_external_turn":
        return f"log_external_turn requires {field}."
    if name == "capture_external_artifact":
        return f"capture_external_artifact requires {field}."
    if name == "decide_writeback_review":
        return f"decide_writeback_review requires {field}."
    return f"{name} requires {field}."


def _validate_value(key: str, value: object, schema: dict) -> str | None:
    expected = schema.get("type")
    if expected == "string":
        if not isinstance(value, str):
            return f"Tool argument must be a string: {key}"
        if "\x00" in value:
            return f"Tool argument contains a NUL character: {key}"
        if any(
            0xD800 <= ord(character) <= 0xDFFF
            or (ord(character) < 0x20 and character not in "\t\n\r")
            or character in FORBIDDEN_UNICODE_CONTROLS
            for character in value
        ):
            return f"Tool argument contains an unsafe Unicode control character: {key}"
        if len(value) > int(schema.get("maxLength", MAX_TOOL_STRING_LENGTH)):
            return f"Tool argument is too large: {key}"
        if len(value.strip()) < int(schema.get("minLength", 0)):
            return f"Tool argument is required: {key}"
        if "enum" in schema and value not in schema["enum"]:
            choices = " or ".join(schema["enum"])
            return f"{key} must be {choices}."
    elif expected == "boolean":
        if not isinstance(value, bool):
            return f"decide_writeback_review requires boolean approved." if key == "approved" else f"Tool argument must be boolean: {key}"
    elif expected == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return f"Tool argument must be an integer: {key}"
        if value < schema.get("minimum", value) or value > schema.get("maximum", value):
            return f"Tool argument is out of range: {key}"
    return None
