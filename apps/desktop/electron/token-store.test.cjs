const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");

const { createTokenStore, getOrCreateToken } = require("./token-store.cjs");

async function makeTempDir() {
  return fs.mkdtemp(path.join(os.tmpdir(), "cml-token-store-"));
}

test("token store set/get/clear roundtrip", async () => {
  const dir = await makeTempDir();
  const store = createTokenStore(dir);

  await store.set("a".repeat(32));
  assert.equal(await store.get(), "a".repeat(32));

  await store.clear();
  assert.equal(await store.get(), null);
});

test("token store does not persist token as plaintext", async () => {
  const dir = await makeTempDir();
  const store = createTokenStore(dir);
  const token = "b".repeat(40);

  await store.set(token);
  const persisted = await fs.readFile(path.join(dir, "backend-token"), "utf8");

  assert.notEqual(persisted, token);
  assert.equal(await store.get(), token);
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
