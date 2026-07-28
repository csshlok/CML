function cleanIpcErrorMessage(error, fallback) {
  const raw = error instanceof Error ? error.message : String(error || "");
  const remotePrefix =
    /^Error invoking remote method '[^']+':\s*(?:Error:\s*)?/i;
  const cleaned = raw.replace(remotePrefix, "").trim();
  return cleaned || fallback;
}

async function invokeWithCleanError(ipcRenderer, channel, fallback) {
  try {
    return await ipcRenderer.invoke(channel);
  } catch (error) {
    throw new Error(cleanIpcErrorMessage(error, fallback));
  }
}

module.exports = {
  cleanIpcErrorMessage,
  invokeWithCleanError,
};
