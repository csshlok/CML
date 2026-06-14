export function buildExtensionSetupText({
  backendUrl,
  token,
  vaultId = "",
  clientName = "Browser extension",
}) {
  return JSON.stringify(
    {
      backend_url: backendUrl,
      extension_token: token,
      default_vault_id: vaultId || "",
      client_name: clientName,
      headers: {
        "x-cml-extension-token": token,
      },
      capture_example: {
        endpoint: `${String(backendUrl || "").replace(/\/+$/, "")}/api/v1/extension/capture`,
        payload: {
          vault_id: vaultId || "",
          capture_type: "selection",
          title: "Saved page selection",
          url: "https://example.com/article",
          text: "Captured text goes here.",
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
