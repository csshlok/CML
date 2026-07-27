const DEFINITIONS = Object.freeze({
  chatgpt_mcp_setup: { environment: "CML_FEATURE_CHATGPT_MCP_SETUP", defaultValue: true },
  secure_mcp_tunnel: { environment: "CML_FEATURE_SECURE_MCP_TUNNEL", defaultValue: true },
  chatgpt_mcp_write_tools: {
    environment: "CML_FEATURE_CHATGPT_MCP_WRITE_TOOLS",
    defaultValue: true,
  },
  mcp_streaming: { environment: "CML_FEATURE_MCP_STREAMING", defaultValue: false },
  mcp_remote_http: { environment: "CML_FEATURE_MCP_REMOTE_HTTP", defaultValue: false },
});

function parseBoolean(value, fallback) {
  if (value === undefined || value === null || String(value).trim() === "") return fallback;
  const normalized = String(value).trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(normalized)) return true;
  if (["0", "false", "no", "off"].includes(normalized)) return false;
  return fallback;
}

function resolveMcpFeatureFlags(environment = process.env) {
  return Object.fromEntries(
    Object.entries(DEFINITIONS).map(([name, definition]) => [
      name,
      parseBoolean(environment[definition.environment], definition.defaultValue),
    ]),
  );
}

module.exports = {
  DEFINITIONS,
  parseBoolean,
  resolveMcpFeatureFlags,
};
