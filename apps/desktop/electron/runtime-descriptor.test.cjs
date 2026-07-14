const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const {
  createRuntimeDescriptor,
  isLoopbackBackendUrl,
  removeRuntimeDescriptor,
  runtimeDescriptorPath,
  writeRuntimeDescriptor,
} = require("./runtime-descriptor.cjs");

test("runtime descriptors contain identity but no credentials", () => {
  const descriptor = createRuntimeDescriptor({
    backendUrl: "http://127.0.0.1:7343",
    apiPrefix: "/api/v1",
    backendInstanceId: "instance-1",
    backendPid: 12,
    desktopPid: 34,
    now: 0,
    ttlMs: 1000,
  });
  assert.equal(descriptor.backend_instance_id, "instance-1");
  assert.equal(descriptor.expires_at, "1970-01-01T00:00:01.000Z");
  assert.equal("token" in descriptor, false);
  assert.equal("credential" in descriptor, false);
});

test("only HTTP loopback URLs are accepted", () => {
  assert.equal(isLoopbackBackendUrl("http://localhost:7343"), true);
  assert.equal(isLoopbackBackendUrl("https://127.0.0.1:7343"), false);
  assert.equal(isLoopbackBackendUrl("http://192.168.1.4:7343"), false);
});

test("runtime descriptors are atomically written and removed", async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "odin-runtime-"));
  const filePath = runtimeDescriptorPath(directory);
  const descriptor = createRuntimeDescriptor({
    backendUrl: "http://127.0.0.1:7343",
    apiPrefix: "/api/v1",
    backendInstanceId: "instance-1",
    desktopPid: process.pid,
  });
  await writeRuntimeDescriptor(filePath, descriptor);
  assert.deepEqual(JSON.parse(await fs.readFile(filePath, "utf8")), descriptor);
  await removeRuntimeDescriptor(filePath);
  await assert.rejects(fs.access(filePath));
  await fs.rm(directory, { recursive: true, force: true });
});
