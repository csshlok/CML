export function buildExtensionSetupText({
  backendUrl,
  token,
  vaultId = "",
  clusterId = "",
  vaultPath = "",
  clientName = "Browser extension",
  browser = "chrome",
}) {
  return JSON.stringify(
    {
      backend_url: backendUrl,
      extension_token: token,
      default_vault_id: vaultId || "",
      default_cluster_id: clusterId || "",
      vault_path: vaultPath || "",
      client_name: clientName,
      browser,
      install_targets: ["chrome", "brave"],
      primary_actions: ["save_link_to_vault", "take_and_save_screenshot"],
      optional_actions: ["save_selection"],
      headers: {
        "x-cml-extension-token": token,
      },
      capture_example: {
        endpoint: `${String(backendUrl || "").replace(/\/+$/, "")}/api/v1/extension/capture`,
        payload: {
          vault_id: vaultId || "",
          cluster_id: clusterId || "",
          capture_type: "page",
          title: "Saved link to vault",
          url: "https://example.com/article",
          text: "Page capture handled by the browser extension.",
        },
      },
    },
    null,
    2,
  );
}

export function describeExtensionScope(allowedVaultIds, vaultNamesById) {
  if (!Array.isArray(allowedVaultIds) || allowedVaultIds.length === 0) {
    return "All vaults allowed";
  }
  return allowedVaultIds.map((id) => vaultNamesById.get(id) || id).join(", ");
}
