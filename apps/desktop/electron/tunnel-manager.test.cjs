const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const { EventEmitter } = require("node:events");

const {
  atomicWriteCredentialFile,
  buildMcpCommand,
  buildTunnelArguments,
  classifyTunnelFailure,
  quoteCommandArgument,
  retryDelayMs,
  safeTunnelError,
  validateTunnelConfiguration,
  sameExecutable,
  TunnelManager,
} = require("./tunnel-manager.cjs");

test("tunnel configuration defaults to read-only and validates secret bounds", () => {
  const value = validateTunnelConfiguration({
    tunnelId: "tunnel_0123456789abcdef",
    runtimeApiKey: "sk-runtime-01234567890123456789",
    bridgeToken: "bridge-token-0123456789",
  });
  assert.equal(value.capabilityProfile, "read_only");
  assert.throws(
    () => validateTunnelConfiguration({ tunnelId: "bad", runtimeApiKey: "short", bridgeToken: "short" }),
    /valid tunnel ID/,
  );
});

test("MCP command quotes packaged paths without invoking a shell", () => {
  const command = buildMcpCommand({
    command: "C:\\Program Files\\Vault\\python.exe",
    args: ["-s", "-m", "backend.app.bridge_mcp_stdio"],
  });
  assert.equal(command, '"C:\\\\Program Files\\\\Vault\\\\python.exe" -s -m backend.app.bridge_mcp_stdio');
  assert.equal(quoteCommandArgument("plain"), "plain");
});

test("tunnel arguments use file-backed control credentials and loopback health", () => {
  const args = buildTunnelArguments({
    tunnelId: "tunnel_0123456789abcdef",
    runtimeKeyPath: "C:\\Data\\runtime-key.tmp",
    healthUrlPath: "C:\\Data\\health-url.txt",
    pidPath: "C:\\Data\\tunnel.pid",
    logPath: "C:\\Data\\tunnel.log",
    mcpCommand: "python -m backend.app.bridge_mcp_stdio",
  });
  assert.deepEqual(args.slice(0, 3), ["run", "--control-plane.tunnel-id", "tunnel_0123456789abcdef"]);
  assert.ok(args.includes("file:C:\\Data\\runtime-key.tmp"));
  assert.ok(args.includes("127.0.0.1:0"));
  assert.equal(args.some((value) => value.startsWith("sk-")), false);
});

test("tunnel errors stay simple and do not expose raw process output", () => {
  assert.equal(safeTunnelError(new Error("HTTP 401 secret=abc")), "OpenAI rejected the tunnel credentials.");
  assert.equal(safeTunnelError(new Error("dial tcp C:\\private\\path")), "The tunnel could not connect. Check your network and tunnel details.");
});

test("tunnel failures distinguish permanent credentials from retryable network faults", async () => {
  const appDataDir = await fs.mkdtemp(path.join(os.tmpdir(), "vault-tunnel-failures-"));
  const logPath = path.join(appDataDir, "tunnel.log");
  try {
    await fs.writeFile(logPath, '{"level":"error","message":"control plane returned HTTP 403"}\n');
    assert.deepEqual(await classifyTunnelFailure(new Error("tunnel exited"), logPath), {
      permanent: true,
      code: "permission_denied",
      message: "This tunnel is not allowed. Check its workspace permissions.",
    });
    await fs.writeFile(logPath, '{"level":"error","message":"HTTP 429 rate limited"}\n');
    assert.equal((await classifyTunnelFailure(new Error("tunnel exited"), logPath)).permanent, false);
    assert.equal((await classifyTunnelFailure(new Error("getaddrinfo ENOTFOUND"), "")).code, "dns_error");
    assert.equal((await classifyTunnelFailure(new Error("x509 certificate expired"), "")).code, "tls_error");
    assert.equal((await classifyTunnelFailure(new Error("HTTP 503"), "")).code, "service_unavailable");
    assert.equal((await classifyTunnelFailure(new Error("HTTP 401"), "")).code, "authentication_rejected");
  } finally {
    await fs.rm(appDataDir, { recursive: true, force: true });
  }
});

test("tunnel restart backoff is exponential, jittered, and capped", () => {
  assert.equal(retryDelayMs(0, 0), 1000);
  assert.equal(retryDelayMs(1, 1), 2500);
  assert.equal(retryDelayMs(10, 0), 30000);
  assert.equal(retryDelayMs(10, 1), 37500);
});

test("credentials round trip stores both secrets only through safe storage", async () => {
  const appDataDir = await fs.mkdtemp(path.join(os.tmpdir(), "vault-tunnel-credentials-"));
  const safeStorage = {
    isEncryptionAvailable: () => true,
    encryptString: (value) => Buffer.from(`encrypted:${Buffer.from(value).toString("base64")}`),
    decryptString: (value) => Buffer.from(String(value).replace("encrypted:", ""), "base64").toString(),
  };
  const manager = new TunnelManager({
    appDataDir,
    safeStorage,
    launcherProvider: async () => ({}),
    tunnelBinaryProvider: async () => "",
    environmentProvider: () => ({}),
  });
  await fs.mkdir(manager.root, { recursive: true });
  await manager._writeCredentials("runtime-secret-0123456789", "bridge-secret-0123456789");
  const stored = await fs.readFile(path.join(manager.root, "credentials.bin"), "utf8");
  const recovered = await manager._readCredentials();
  assert.equal(stored.includes("runtime-secret"), false);
  assert.equal(stored.includes("bridge-secret"), false);
  assert.deepEqual(recovered, {
    runtimeApiKey: "runtime-secret-0123456789",
    bridgeToken: "bridge-secret-0123456789",
  });
  await fs.rm(appDataDir, { recursive: true, force: true });
});

test("credential persistence fails closed when OS encryption is unavailable", async () => {
  const appDataDir = await fs.mkdtemp(path.join(os.tmpdir(), "vault-tunnel-no-credentials-"));
  const manager = new TunnelManager({
    appDataDir,
    safeStorage: { isEncryptionAvailable: () => false },
    launcherProvider: async () => ({}),
    tunnelBinaryProvider: async () => "",
    environmentProvider: () => ({}),
  });
  await fs.mkdir(manager.root, { recursive: true });
  await assert.rejects(
    manager._writeCredentials("runtime-secret-0123456789", "bridge-secret-0123456789"),
    /credential protection is unavailable/,
  );
  await assert.rejects(fs.stat(path.join(manager.root, "credentials.bin")));
  await fs.rm(appDataDir, { recursive: true, force: true });
});

test("disk-full credential writes leave the previous credential file intact", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "vault-tunnel-disk-full-"));
  const target = path.join(root, "credentials.bin");
  await fs.writeFile(target, "previous-encrypted-value");
  let renamed = false;
  const failingFileSystem = {
    writeFile: async () => {
      const error = new Error("disk full");
      error.code = "ENOSPC";
      throw error;
    },
    rename: async () => {
      renamed = true;
    },
    unlink: async () => {},
  };

  await assert.rejects(
    atomicWriteCredentialFile(target, Buffer.from("new-encrypted-value"), failingFileSystem),
    (error) => error.code === "ENOSPC",
  );

  assert.equal(renamed, false);
  assert.equal(await fs.readFile(target, "utf8"), "previous-encrypted-value");
  await fs.rm(root, { recursive: true, force: true });
});

test("newer tunnel settings and credentials fail closed with an update action", async () => {
  const appDataDir = await fs.mkdtemp(path.join(os.tmpdir(), "vault-tunnel-newer-schema-"));
  const safeStorage = {
    isEncryptionAvailable: () => true,
    encryptString: (value) => Buffer.from(value),
    decryptString: (value) => value.toString("utf8"),
  };
  const manager = new TunnelManager({
    appDataDir,
    safeStorage,
    launcherProvider: async () => ({ version: 1 }),
    tunnelBinaryProvider: async () => "",
    environmentProvider: () => ({}),
  });
  await fs.mkdir(manager.root, { recursive: true });
  await fs.writeFile(path.join(manager.root, "connection.json"), JSON.stringify({
    schema_version: 99,
    tunnel_id: "tunnel_0123456789abcdef",
    auto_connect: true,
  }));
  assert.equal((await manager.initialize()).detail, "Update Vault before reconnecting this tunnel.");

  await fs.writeFile(path.join(manager.root, "connection.json"), JSON.stringify({
    schema_version: 1,
    tunnel_id: "tunnel_0123456789abcdef",
    auto_connect: false,
  }));
  await fs.writeFile(path.join(manager.root, "credentials.bin"), JSON.stringify({
    schema_version: 99,
    runtime_api_key: "must-not-be-used",
    bridge_token: "must-not-be-used",
  }));
  await assert.rejects(manager.reconnect(""), /Update Vault/);
  await fs.rm(appDataDir, { recursive: true, force: true });
});

test("legacy tunnel metadata is upgraded to the current explicit schema", async () => {
  const appDataDir = await fs.mkdtemp(path.join(os.tmpdir(), "vault-tunnel-legacy-schema-"));
  const manager = new TunnelManager({
    appDataDir,
    safeStorage: null,
    launcherProvider: async () => ({ version: 1 }),
    tunnelBinaryProvider: async () => "",
    environmentProvider: () => ({}),
  });
  await fs.mkdir(manager.root, { recursive: true });
  await fs.writeFile(path.join(manager.root, "connection.json"), JSON.stringify({
    tunnel_id: "tunnel_0123456789abcdef",
    capability_profile: "read_only",
    auto_connect: false,
  }));
  await manager.initialize();
  const migrated = JSON.parse(await fs.readFile(path.join(manager.root, "connection.json"), "utf8"));
  assert.equal(migrated.schema_version, 1);
  assert.equal(migrated.tunnel_id, "tunnel_0123456789abcdef");
  await fs.rm(appDataDir, { recursive: true, force: true });
});

test("tunnel rollout kill switch reconciles state without auto-connecting", async () => {
  const appDataDir = await fs.mkdtemp(path.join(os.tmpdir(), "vault-tunnel-kill-switch-"));
  const safeStorage = {
    isEncryptionAvailable: () => true,
    encryptString: (value) => Buffer.from(value),
    decryptString: (value) => value.toString("utf8"),
  };
  const manager = new TunnelManager({
    appDataDir,
    safeStorage,
    launcherProvider: async () => ({ version: 1 }),
    tunnelBinaryProvider: async () => "",
    environmentProvider: () => ({}),
  });
  await fs.mkdir(manager.root, { recursive: true });
  await fs.writeFile(path.join(manager.root, "connection.json"), JSON.stringify({
    schema_version: 1,
    tunnel_id: "tunnel_0123456789abcdef",
    capability_profile: "read_only",
    auto_connect: true,
  }));
  await manager._writeCredentials("runtime-secret-0123456789", "bridge-secret-0123456789");
  let connectionAttempts = 0;
  manager.connect = async () => {
    connectionAttempts += 1;
  };
  const status = await manager.initialize({ allowAutoConnect: false });
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(connectionAttempts, 0);
  assert.equal(status.detail, "Ready to connect");
  await fs.rm(appDataDir, { recursive: true, force: true });
});

test("an incompatible MCP launcher is refused before tunnel execution", async () => {
  const appDataDir = await fs.mkdtemp(path.join(os.tmpdir(), "vault-tunnel-launcher-version-"));
  const manager = new TunnelManager({
    appDataDir,
    safeStorage: null,
    launcherProvider: async () => ({ version: 2 }),
    tunnelBinaryProvider: async () => {
      throw new Error("must not resolve tunnel binary");
    },
    environmentProvider: () => ({}),
  });
  await assert.rejects(
    manager.connect({
      tunnelId: "tunnel_0123456789abcdef",
      runtimeApiKey: "runtime-key-0123456789",
      bridgeToken: "bridge-token-0123456789",
    }),
    /incompatible/,
  );
  assert.equal(manager.activeConfiguration, null);
  await fs.rm(appDataDir, { recursive: true, force: true });
});

test("permanent failures cancel pending reconnect state", async () => {
  const appDataDir = await fs.mkdtemp(path.join(os.tmpdir(), "vault-tunnel-permanent-"));
  const manager = new TunnelManager({
    appDataDir,
    safeStorage: null,
    launcherProvider: async () => ({}),
    tunnelBinaryProvider: async () => "",
    environmentProvider: () => ({}),
  });
  manager.activeConfiguration = {
    tunnelId: "tunnel_0123456789abcdef",
    runtimeApiKey: "runtime-key-0123456789",
    bridgeToken: "bridge-token-0123456789",
    capabilityProfile: "read_only",
  };
  manager._scheduleRestart();
  manager._disableReconnect();
  assert.equal(manager.activeConfiguration, null);
  assert.equal(manager.restartTimer, null);
  assert.equal(manager.manualStop, true);
  await fs.rm(appDataDir, { recursive: true, force: true });
});

test("startup removes only a verified orphan tunnel process", async () => {
  const appDataDir = await fs.mkdtemp(path.join(os.tmpdir(), "vault-tunnel-orphan-"));
  const expectedBinary = path.join(appDataDir, "tunnel-client.exe");
  const killed = [];
  const manager = new TunnelManager({
    appDataDir,
    safeStorage: null,
    launcherProvider: async () => ({}),
    tunnelBinaryProvider: async () => expectedBinary,
    environmentProvider: () => ({}),
    processPathProvider: async () => expectedBinary,
    processTreeKiller: async (pid) => killed.push(pid),
  });
  await fs.mkdir(manager.root, { recursive: true });
  await fs.writeFile(path.join(manager.root, "owner.json"), JSON.stringify({
    pid: 4321,
    tunnel_binary: expectedBinary,
  }));
  await fs.writeFile(path.join(manager.root, "tunnel.pid"), "4321");
  await manager.initialize();
  assert.deepEqual(killed, [4321]);
  await assert.rejects(fs.stat(path.join(manager.root, "owner.json")));
  assert.equal(sameExecutable(expectedBinary.toUpperCase(), expectedBinary), true);
  await fs.rm(appDataDir, { recursive: true, force: true });
});

test("readiness accepts only a healthy loopback endpoint", async () => {
  const appDataDir = await fs.mkdtemp(path.join(os.tmpdir(), "vault-tunnel-ready-"));
  const healthFile = path.join(appDataDir, "health-url.txt");
  const server = http.createServer((request, response) => {
    response.statusCode = request.url === "/readyz" ? 204 : 404;
    response.end();
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  await fs.writeFile(healthFile, `http://127.0.0.1:${address.port}\n`);
  const manager = new TunnelManager({
    appDataDir,
    safeStorage: null,
    launcherProvider: async () => ({}),
    tunnelBinaryProvider: async () => "",
    environmentProvider: () => ({}),
  });
  const child = new EventEmitter();
  child.exitCode = null;
  try {
    await manager._waitForReady(healthFile, child, 2_000);
    assert.equal(manager.healthUrl, `http://127.0.0.1:${address.port}`);
  } finally {
    await new Promise((resolve) => server.close(resolve));
    await fs.rm(appDataDir, { recursive: true, force: true });
  }
});

test("readiness fails promptly when the tunnel crashes", async () => {
  const appDataDir = await fs.mkdtemp(path.join(os.tmpdir(), "vault-tunnel-crash-"));
  const manager = new TunnelManager({
    appDataDir,
    safeStorage: null,
    launcherProvider: async () => ({}),
    tunnelBinaryProvider: async () => "",
    environmentProvider: () => ({}),
  });
  const child = new EventEmitter();
  child.exitCode = 1;
  await assert.rejects(
    manager._waitForReady(path.join(appDataDir, "missing.txt"), child, 5_000),
    /exited during startup/,
  );
  await fs.rm(appDataDir, { recursive: true, force: true });
});

test("rapid disconnect cancels a pending automatic reconnect", async () => {
  const appDataDir = await fs.mkdtemp(path.join(os.tmpdir(), "vault-tunnel-reconnect-"));
  const manager = new TunnelManager({
    appDataDir,
    safeStorage: null,
    launcherProvider: async () => ({}),
    tunnelBinaryProvider: async () => "",
    environmentProvider: () => ({}),
  });
  let reconnects = 0;
  manager.connect = async () => {
    reconnects += 1;
  };
  manager.activeConfiguration = {
    tunnelId: "tunnel_0123456789abcdef",
    runtimeApiKey: "runtime-key-0123456789",
    bridgeToken: "bridge-token-0123456789",
    capabilityProfile: "read_only",
  };
  manager._scheduleRestart();
  assert.equal(manager.getStatus().detail, "Reconnecting...");
  await manager.disconnect();
  await new Promise((resolve) => setTimeout(resolve, 1_100));
  assert.equal(reconnects, 0);
  assert.equal(manager.getStatus().state, "disconnected");
  await fs.rm(appDataDir, { recursive: true, force: true });
});
