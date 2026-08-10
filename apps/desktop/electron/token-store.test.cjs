const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");

const { createTokenStore, getOrCreateToken } = require("./token-store.cjs");

const temporaryDirectories = new Set();

async function makeTempDir() {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "cml-token-store-"));
  temporaryDirectories.add(directory);
  return directory;
}

test.after(async () => {
  await Promise.all(
    [...temporaryDirectories].map((directory) =>
      fs.rm(directory, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 }),
    ),
  );
});

test("token store set/get/clear roundtrip", async () => {
  const dir = await makeTempDir();
  const store = createTokenStore(dir);

  await store.set("a".repeat(32));
  assert.equal(await store.get(), "a".repeat(32));

  await store.clear();
  assert.equal(await store.get(), null);
});

test("token store remains memory-only when secure storage is unavailable", async () => {
  const dir = await makeTempDir();
  const store = createTokenStore(dir);
  const token = "b".repeat(40);

  await store.set(token);
  await assert.rejects(fs.readFile(path.join(dir, "backend-token"), "utf8"), { code: "ENOENT" });
  assert.equal(await store.get(), token);
});

test("token store persists only safeStorage ciphertext", async () => {
  const dir = await makeTempDir();
  const safeStorage = {
    isEncryptionAvailable: () => true,
    encryptString: (value) => Buffer.from(`protected:${value}`, "utf8"),
    decryptString: (value) => value.toString("utf8").replace(/^protected:/, ""),
  };
  const store = createTokenStore(dir, safeStorage);
  const token = "c".repeat(40);
  await store.set(token);
  const persisted = await fs.readFile(path.join(dir, "backend-token"), "utf8");
  assert.match(persisted, /^safe:v1:/);
  assert.ok(!persisted.includes(token));
  assert.equal(await store.get(), token);
});

test("legacy local and plaintext records are rejected", async () => {
  const dir = await makeTempDir();
  const tokenPath = path.join(dir, "backend-token");
  const safeStorage = {
    isEncryptionAvailable: () => true,
    encryptString: (value) => Buffer.from(value, "utf8"),
    decryptString: (value) => value.toString("utf8"),
  };
  const store = createTokenStore(dir, safeStorage);
  await fs.writeFile(tokenPath, `local:v1:${"a".repeat(80)}`, "utf8");
  assert.equal(await store.get(), null);
  await fs.writeFile(tokenPath, "plaintext-token-that-is-definitely-long-enough", "utf8");
  assert.equal(await store.get(), null);
});

test("token store rejects short persisted values", async () => {
  const dir = await makeTempDir();
  const tokenPath = path.join(dir, "backend-token");
  await fs.writeFile(tokenPath, "short", "utf8");

  const store = createTokenStore(dir);
  assert.equal(await store.get(), null);
});

test("getOrCreateToken is stable across repeated calls", async () => {
  const dir = await makeTempDir();
  const store = createTokenStore(dir);

  const first = await getOrCreateToken(store);
  const second = await getOrCreateToken(store);

  assert.equal(first, second);
  assert.ok(first.length >= 32);
});
