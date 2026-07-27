"""Authoritative environment-backed rollout switches for MCP capabilities."""

from __future__ import annotations

import os
from collections.abc import Mapping

_DEFAULTS = {
    "chatgpt_mcp_setup": True,
    "secure_mcp_tunnel": True,
    "chatgpt_mcp_write_tools": True,
    "mcp_streaming": False,
    "mcp_remote_http": False,
}
_ENVIRONMENT = {
    "chatgpt_mcp_setup": "CML_FEATURE_CHATGPT_MCP_SETUP",
    "secure_mcp_tunnel": "CML_FEATURE_SECURE_MCP_TUNNEL",
    "chatgpt_mcp_write_tools": "CML_FEATURE_CHATGPT_MCP_WRITE_TOOLS",
    "mcp_streaming": "CML_FEATURE_MCP_STREAMING",
    "mcp_remote_http": "CML_FEATURE_MCP_REMOTE_HTTP",
}


def mcp_feature_flags(environment: Mapping[str, str] | None = None) -> dict[str, bool]:
    values = os.environ if environment is None else environment
    return {
        name: _parse_boolean(values.get(_ENVIRONMENT[name]), fallback)
        for name, fallback in _DEFAULTS.items()
    }


def effective_mcp_capability_profile(requested: str | None) -> str:
    wants_write = str(requested or "").strip().lower() == "read_write"
    if wants_write and mcp_feature_flags()["chatgpt_mcp_write_tools"]:
        return "read_write"
    return "read_only"


def _parse_boolean(value: str | None, fallback: bool) -> bool:
    if value is None or not str(value).strip():
        return fallback
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return fallback
