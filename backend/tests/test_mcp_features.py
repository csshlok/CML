from unittest.mock import patch

from backend.app.core.mcp_features import (
    effective_mcp_capability_profile,
    mcp_feature_flags,
)


def test_mcp_feature_flags_have_explicit_rollout_defaults_and_parsing() -> None:
    assert mcp_feature_flags({}) == {
        "chatgpt_mcp_setup": True,
        "secure_mcp_tunnel": True,
        "chatgpt_mcp_write_tools": True,
        "mcp_streaming": False,
        "mcp_remote_http": False,
    }
    assert mcp_feature_flags(
        {
            "CML_FEATURE_CHATGPT_MCP_SETUP": "off",
            "CML_FEATURE_SECURE_MCP_TUNNEL": "0",
            "CML_FEATURE_CHATGPT_MCP_WRITE_TOOLS": "no",
            "CML_FEATURE_MCP_STREAMING": "on",
            "CML_FEATURE_MCP_REMOTE_HTTP": "unexpected",
        }
    ) == {
        "chatgpt_mcp_setup": False,
        "secure_mcp_tunnel": False,
        "chatgpt_mcp_write_tools": False,
        "mcp_streaming": True,
        "mcp_remote_http": False,
    }


def test_write_profile_downgrades_when_rollout_switch_is_off() -> None:
    with patch.dict(
        "os.environ",
        {"CML_FEATURE_CHATGPT_MCP_WRITE_TOOLS": "false"},
        clear=False,
    ):
        assert effective_mcp_capability_profile("read_write") == "read_only"
