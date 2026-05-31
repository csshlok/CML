const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const path = require("node:path");

class FileTokenStore {
  constructor(userDataPath) {
    this.tokenPath = path.join(userDataPath, "backend-token");
  }

  async get() {
    try {
      const token = (await fs.readFile(this.tokenPath, "utf8")).trim();
      return token.length >= 32 ? token : null;
    } catch {
      return null;
    }
  }

  async set(token) {
    await fs.mkdir(path.dirname(this.tokenPath), { recursive: true });
    await fs.writeFile(this.tokenPath, token, { encoding: "utf8", mode: 0o600 });
  }

  async clear() {
    try {
      await fs.unlink(this.tokenPath);
    } catch {
      // Missing token files are already clear.
    }
  }
}

function createTokenStore(userDataPath) {
  return new FileTokenStore(userDataPath);
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
