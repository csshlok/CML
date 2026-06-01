const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const path = require("node:path");

class FileTokenStore {
  constructor(userDataPath, safeStorage = null) {
    this.tokenPath = path.join(userDataPath, "backend-token");
    this.safeStorage = safeStorage;
  }

  async get() {
    try {
      const persisted = (await fs.readFile(this.tokenPath, "utf8")).trim();
      const token = this.decodePersistedToken(persisted);
      return token.length >= 32 ? token : null;
    } catch {
      return null;
    }
  }

  async set(token) {
    await fs.mkdir(path.dirname(this.tokenPath), { recursive: true });
    const persisted = this.encodeTokenForStorage(token);
    await fs.writeFile(this.tokenPath, persisted, { encoding: "utf8", mode: 0o600 });
  }

  async clear() {
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
    const nonce = crypto.randomBytes(16);
    const key = crypto.scryptSync(path.dirname(this.tokenPath), nonce, 32);
    const cipher = crypto.createCipheriv("aes-256-gcm", key, nonce);
    const ciphertext = Buffer.concat([cipher.update(token, "utf8"), cipher.final()]);
    return `local:v1:${nonce.toString("base64")}:${cipher.getAuthTag().toString("base64")}:${ciphertext.toString("base64")}`;
  }

  decodePersistedToken(persisted) {
    if (persisted.startsWith("safe:v1:") && this.safeStorage?.isEncryptionAvailable?.()) {
      return this.safeStorage.decryptString(Buffer.from(persisted.slice("safe:v1:".length), "base64"));
    }
    if (persisted.startsWith("local:v1:")) {
      const [, , nonceValue, tagValue, ciphertextValue] = persisted.split(":");
      const nonce = Buffer.from(nonceValue, "base64");
      const key = crypto.scryptSync(path.dirname(this.tokenPath), nonce, 32);
      const decipher = crypto.createDecipheriv("aes-256-gcm", key, nonce);
      decipher.setAuthTag(Buffer.from(tagValue, "base64"));
      return Buffer.concat([
        decipher.update(Buffer.from(ciphertextValue, "base64")),
        decipher.final(),
      ]).toString("utf8");
    }
    return persisted;
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
