const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const path = require("node:path");

class FileTokenStore {
  constructor(userDataPath, safeStorage = null) {
    this.tokenPath = path.join(userDataPath, "backend-token");
    this.safeStorage = safeStorage;
    this.memoryToken = null;
  }

  async get() {
    if (!this.safeStorage?.isEncryptionAvailable?.()) {
      return this.memoryToken;
    }
    try {
      const persisted = (await fs.readFile(this.tokenPath, "utf8")).trim();
      const token = this.decodePersistedToken(persisted);
      return token.length >= 32 ? token : null;
    } catch {
      return null;
    }
  }

  async set(token) {
    if (!this.safeStorage?.isEncryptionAvailable?.()) {
      this.memoryToken = token;
      await this.clearPersistedToken();
      return;
    }
    await fs.mkdir(path.dirname(this.tokenPath), { recursive: true });
    const persisted = this.encodeTokenForStorage(token);
    await fs.writeFile(this.tokenPath, persisted, { encoding: "utf8", mode: 0o600 });
  }

  async clear() {
    this.memoryToken = null;
    await this.clearPersistedToken();
  }

  async clearPersistedToken() {
    try {
      await fs.unlink(this.tokenPath);
    } catch {
      // Missing token files are already clear.
    }
  }

  encodeTokenForStorage(token) {
    if (this.safeStorage?.isEncryptionAvailable?.()) {
      const encrypted = this.safeStorage.encryptString(token).toString("base64");
      return `safe:v1:${encrypted}`;
    }
    throw new Error("Secure credential storage is unavailable");
  }

  decodePersistedToken(persisted) {
    if (persisted.startsWith("safe:v1:") && this.safeStorage?.isEncryptionAvailable?.()) {
      return this.safeStorage.decryptString(Buffer.from(persisted.slice("safe:v1:".length), "base64"));
    }
    return "";
  }
}

function createTokenStore(userDataPath, safeStorage = null) {
  return new FileTokenStore(userDataPath, safeStorage);
}

async function getOrCreateToken(tokenStore) {
  const existing = await tokenStore.get();
  if (existing) return existing;
  const token = crypto.randomBytes(32).toString("base64url");
  await tokenStore.set(token);
  return token;
}

module.exports = {
  createTokenStore,
  getOrCreateToken,
};
