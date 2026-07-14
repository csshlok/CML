const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const path = require("node:path");

const RUNTIME_DESCRIPTOR_VERSION = 1;
const RUNTIME_DESCRIPTOR_NAME = "odin-runtime.json";

function runtimeDescriptorPath(userDataPath) {
  return path.join(userDataPath, RUNTIME_DESCRIPTOR_NAME);
}

function isLoopbackBackendUrl(value) {
  try {
    const url = new URL(String(value));
    return url.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);
  } catch {
    return false;
  }
}

function createRuntimeDescriptor({ backendUrl, apiPrefix, backendInstanceId, backendPid, desktopPid, ttlMs = 12 * 60 * 60 * 1000, now = Date.now() }) {
  if (!isLoopbackBackendUrl(backendUrl)) throw new Error("Odin runtime descriptors require a loopback backend URL.");
  if (!backendInstanceId) throw new Error("The backend instance identity is required.");
  return {
    version: RUNTIME_DESCRIPTOR_VERSION,
    backend_url: String(backendUrl).replace(/\/+$/, ""),
    api_prefix: apiPrefix,
    backend_instance_id: backendInstanceId,
    backend_pid: Number.isInteger(backendPid) && backendPid > 0 ? backendPid : null,
    desktop_pid: Number(desktopPid),
    created_at: new Date(now).toISOString(),
    expires_at: new Date(now + ttlMs).toISOString(),
    discovery_nonce: crypto.randomBytes(24).toString("base64url"),
  };
}

async function writeRuntimeDescriptor(filePath, descriptor) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  const temporaryPath = `${filePath}.${process.pid}.${crypto.randomBytes(6).toString("hex")}.tmp`;
  try {
    await fs.writeFile(temporaryPath, `${JSON.stringify(descriptor, null, 2)}\n`, { encoding: "utf8", mode: 0o600, flag: "wx" });
    await fs.chmod(temporaryPath, 0o600).catch(() => {});
    await fs.rename(temporaryPath, filePath);
    await fs.chmod(filePath, 0o600).catch(() => {});
  } finally {
    await fs.rm(temporaryPath, { force: true }).catch(() => {});
  }
}

async function removeRuntimeDescriptor(filePath) {
  await fs.rm(filePath, { force: true }).catch(() => {});
}

module.exports = {
  RUNTIME_DESCRIPTOR_NAME,
  createRuntimeDescriptor,
  isLoopbackBackendUrl,
  removeRuntimeDescriptor,
  runtimeDescriptorPath,
  writeRuntimeDescriptor,
};
