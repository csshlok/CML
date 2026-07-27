const test = require("node:test");
const assert = require("node:assert/strict");

const { resolveMcpFeatureFlags } = require("./mcp-feature-flags.cjs");

test("MCP rollout flags have safe explicit defaults", () => {
  assert.deepEqual(resolveMcpFeatureFlags({}), {
    chatgpt_mcp_setup: true,
    secure_mcp_tunnel: true,
    chatgpt_mcp_write_tools: true,
    mcp_streaming: false,
    mcp_remote_http: false,
  });
});

test("MCP rollout kill switches accept common boolean forms and reject ambiguity", () => {
  const flags = resolveMcpFeatureFlags({
    CML_FEATURE_CHATGPT_MCP_SETUP: "off",
    CML_FEATURE_SECURE_MCP_TUNNEL: "0",
    CML_FEATURE_CHATGPT_MCP_WRITE_TOOLS: "false",
    CML_FEATURE_MCP_STREAMING: "yes",
    CML_FEATURE_MCP_REMOTE_HTTP: "ambiguous",
  });
  assert.equal(flags.chatgpt_mcp_setup, false);
  assert.equal(flags.secure_mcp_tunnel, false);
  assert.equal(flags.chatgpt_mcp_write_tools, false);
  assert.equal(flags.mcp_streaming, true);
  assert.equal(flags.mcp_remote_http, false);
});
