const fs = require("node:fs/promises");
const fsSync = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { spawn } = require("node:child_process");
const { performance } = require("node:perf_hooks");

const TUNNEL_ID_PATTERN = /^tunnel_[A-Za-z0-9_-]{8,128}$/;
const MAX_TUNNEL_LOG_BYTES = 2 * 1024 * 1024;
const TUNNEL_METADATA_SCHEMA_VERSION = 1;
const TUNNEL_CREDENTIAL_SCHEMA_VERSION = 2;
const MCP_LAUNCHER_VERSION = 1;

async function atomicWriteCredentialFile(target, encrypted, fileSystem = fs) {
  const temporary = `${target}.${process.pid}.${Date.now()}.tmp`;
  try {
    await fileSystem.writeFile(temporary, encrypted, { mode: 0o600, flag: "wx" });
    await fileSystem.rename(temporary, target);
  } catch (error) {
    await fileSystem.unlink(temporary).catch(() => {});
    throw error;
  }
}

function validateTunnelConfiguration(configuration) {
  const tunnelId = String(configuration?.tunnelId || "").trim();
  const runtimeApiKey = String(configuration?.runtimeApiKey || "").trim();
  const bridgeToken = String(configuration?.bridgeToken || "").trim();
  const capabilityProfile = configuration?.capabilityProfile === "read_write" ? "read_write" : "read_only";
  if (!TUNNEL_ID_PATTERN.test(tunnelId)) {
    throw new Error("Enter a valid tunnel ID from OpenAI Platform.");
  }
  if (runtimeApiKey.length < 20 || runtimeApiKey.length > 512 || runtimeApiKey.includes("\0")) {
    throw new Error("Enter a valid tunnel runtime key.");
  }
  if (bridgeToken.length < 16 || bridgeToken.length > 512 || bridgeToken.includes("\0")) {
    throw new Error("Create a Vault connection token first.");
  }
  return { tunnelId, runtimeApiKey, bridgeToken, capabilityProfile };
}

function quoteCommandArgument(value) {
  const text = String(value);
  if (!/[\s",]/.test(text)) return text;
  return `"${text.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

function buildMcpCommand(launcher) {
  return [launcher.command, ...(launcher.args || [])].map(quoteCommandArgument).join(" ");
}

function buildTunnelArguments({
  tunnelId,
  runtimeKeyPath,
  healthUrlPath,
  pidPath,
  logPath,
  mcpCommand,
}) {
  return [
    "run",
    "--control-plane.tunnel-id", tunnelId,
    "--control-plane.api-key", `file:${runtimeKeyPath}`,
    "--health.listen-addr", "127.0.0.1:0",
    "--health.url-file", healthUrlPath,
    "--pid.file", pidPath,
    "--mcp.command", `channel=main,command=${mcpCommand}`,
    "--mcp.max-concurrent-requests", "8",
    "--control-plane.max-inflight", "16",
    "--log.file", logPath,
    "--log.format", "json",
  ];
}

class TunnelManager {
  constructor({
    appDataDir,
    safeStorage,
    launcherProvider,
    tunnelBinaryProvider,
    environmentProvider,
    onStatus,
    processPathProvider = inspectProcessPath,
    processTreeKiller = killProcessTree,
  }) {
    this.root = path.join(appDataDir, "mcp-tunnel");
    this.safeStorage = safeStorage;
    this.launcherProvider = launcherProvider;
    this.tunnelBinaryProvider = tunnelBinaryProvider;
    this.environmentProvider = environmentProvider;
    this.onStatus = typeof onStatus === "function" ? onStatus : () => {};
    this.processPathProvider = processPathProvider;
    this.processTreeKiller = processTreeKiller;
    this.child = null;
    this.activeConfiguration = null;
    this.restartTimer = null;
    this.restartAttempt = 0;
    this.manualStop = false;
    this.healthUrl = null;
    this.status = {
      state: "disconnected",
      tunnel_id: "",
      bridge_client_id: "",
      capability_profile: "read_only",
      ready: false,
      detail: "Not connected",
      health_url: "",
      last_connected_at: null,
      last_error_at: null,
    };
  }

  async initialize({ allowAutoConnect = true } = {}) {
    await fs.mkdir(this.root, { recursive: true });
    await this._reconcileOrphan();
    const metadata = await this._readMetadata();
    if (metadata) {
      if (metadata.incompatible) {
        this._publish({
          state: "attention_required",
          ready: false,
          detail: "Update Vault before reconnecting this tunnel.",
        });
        return this.getStatus();
      }
      this._publish({
        tunnel_id: metadata.tunnel_id,
        bridge_client_id: metadata.bridge_client_id,
        capability_profile: metadata.capability_profile,
        detail: "Ready to connect",
      });
      if (metadata.auto_connect && allowAutoConnect) {
        const credentials = await this._readCredentials();
        if (credentials?.incompatible) {
          this._publish({
            state: "attention_required",
            ready: false,
            detail: "Update Vault before reconnecting this tunnel.",
          });
          return this.getStatus();
        }
        if (credentials?.runtimeApiKey && credentials?.bridgeToken) {
          setTimeout(() => {
            void this.connect({
              tunnelId: metadata.tunnel_id,
              runtimeApiKey: credentials.runtimeApiKey,
              bridgeToken: credentials.bridgeToken,
              capabilityProfile: metadata.capability_profile,
              bridgeClientId: metadata.bridge_client_id,
            }, { automatic: true }).catch(() => {
              // The supervised reconnect path publishes an actionable status.
            });
          }, 0);
        }
      }
    }
    return this.getStatus();
  }

  getStatus() {
    return { ...this.status };
  }

  async connect(configuration, { automatic = false } = {}) {
    const normalized = validateTunnelConfiguration(configuration);
    await this.disconnect({ forget: false, preserveConfiguration: automatic });
    this.manualStop = false;
    this.activeConfiguration = normalized;
    if (!automatic) this.restartAttempt = 0;
    await fs.mkdir(this.root, { recursive: true });
    const launcher = await this.launcherProvider(normalized.capabilityProfile);
    if (launcher?.version !== MCP_LAUNCHER_VERSION) {
      this._disableReconnect();
      throw new Error("Vault's MCP launcher is incompatible. Repair or update Vault.");
    }
    const tunnelBinary = await this.tunnelBinaryProvider();
    if (!fsSync.existsSync(tunnelBinary)) {
      throw new Error("Secure MCP Tunnel is missing. Repair Vault and try again.");
    }
    normalized.bridgeClientId = String(configuration?.bridgeClientId || "").trim();
    await this._writeCredentials(normalized.runtimeApiKey, normalized.bridgeToken);
    await this._writeMetadata({
      tunnel_id: normalized.tunnelId,
      bridge_client_id: normalized.bridgeClientId,
      capability_profile: normalized.capabilityProfile,
      bridge_client_id: normalized.bridgeClientId,
      auto_connect: true,
    });
    const runtimeKeyPath = path.join(this.root, "runtime-key.tmp");
    const healthUrlPath = path.join(this.root, "health-url.txt");
    const pidPath = path.join(this.root, "tunnel.pid");
    const logPath = path.join(this.root, "tunnel.log");
    await this._rotateLog(logPath);
    await fs.writeFile(runtimeKeyPath, normalized.runtimeApiKey, { encoding: "utf8", mode: 0o600 });
    await Promise.allSettled([fs.unlink(healthUrlPath), fs.unlink(pidPath)]);
    const mcpCommand = buildMcpCommand(launcher);
    const args = buildTunnelArguments({
      tunnelId: normalized.tunnelId,
      runtimeKeyPath,
      healthUrlPath,
      pidPath,
      logPath,
      mcpCommand,
    });
    const env = {
      ...this.environmentProvider(launcher),
      ...launcher.env,
      CML_BRIDGE_TOKEN: normalized.bridgeToken,
    };
    this._publish({
      state: "connecting",
      ready: false,
      tunnel_id: normalized.tunnelId,
      capability_profile: normalized.capabilityProfile,
      detail: "Connecting to ChatGPT",
      health_url: "",
    });
    const child = spawn(tunnelBinary, args, {
      cwd: launcher.cwd,
      env,
      windowsHide: true,
      stdio: ["ignore", "ignore", "ignore"],
    });
    this.child = child;
    child.once("exit", (code) => {
      if (this.child !== child) return;
      this.child = null;
      this.healthUrl = null;
      this._publish({
        state: code === 0 ? "disconnected" : "attention_required",
        ready: false,
        detail: code === 0 ? "Disconnected" : "Connection stopped. Try again.",
        health_url: "",
        last_error_at: code === 0 ? this.status.last_error_at : new Date().toISOString(),
      });
      if (!this.manualStop && this.activeConfiguration && code !== 0) {
        this._scheduleRestart();
      }
    });
    try {
      await this._writeOwner({
        pid: child.pid,
        tunnel_binary: path.resolve(tunnelBinary),
        started_at: new Date().toISOString(),
      });
      await this._waitForReady(healthUrlPath, child, 30_000);
      await fs.unlink(runtimeKeyPath).catch(() => {});
      this._publish({
        state: "connected",
        ready: true,
        detail: "Connected",
        health_url: this.healthUrl || "",
        last_connected_at: new Date().toISOString(),
      });
      this.restartAttempt = 0;
      return this.getStatus();
    } catch (error) {
      await fs.unlink(runtimeKeyPath).catch(() => {});
      const failure = await classifyTunnelFailure(error, logPath);
      if (failure.permanent) this._disableReconnect();
      await this._stopChild(child);
      this._publish({
        state: "attention_required",
        ready: false,
        detail: failure.message,
        health_url: "",
        last_error_at: new Date().toISOString(),
      });
      throw new Error(this.status.detail);
    }
  }

  async reconnect(bridgeToken) {
    const metadata = await this._readMetadata();
    const credentials = await this._readCredentials();
    if (metadata?.incompatible || credentials?.incompatible) {
      throw new Error("Update Vault before reconnecting this tunnel.");
    }
    if (!metadata || !credentials?.runtimeApiKey || !(bridgeToken || credentials.bridgeToken)) {
      throw new Error("Enter the tunnel details again.");
    }
    return this.connect({
      tunnelId: metadata.tunnel_id,
      runtimeApiKey: credentials.runtimeApiKey,
      bridgeToken: bridgeToken || credentials.bridgeToken,
      capabilityProfile: metadata.capability_profile,
      bridgeClientId: metadata.bridge_client_id,
    });
  }

  async disconnect({ forget = false, preserveConfiguration = false } = {}) {
    this.manualStop = !preserveConfiguration;
    if (this.restartTimer) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
    if (!preserveConfiguration) {
      this.activeConfiguration = null;
      this.restartAttempt = 0;
    }
    const child = this.child;
    this.child = null;
    if (child) await this._stopChild(child);
    this.healthUrl = null;
    await Promise.allSettled([
      fs.unlink(path.join(this.root, "runtime-key.tmp")),
      fs.unlink(path.join(this.root, "health-url.txt")),
      fs.unlink(path.join(this.root, "tunnel.pid")),
      fs.unlink(path.join(this.root, "owner.json")),
    ]);
    if (!forget && !preserveConfiguration) {
      const metadata = await this._readMetadata();
      if (metadata) await this._writeMetadata({ ...metadata, auto_connect: false });
    }
    if (forget) {
      await Promise.allSettled([
        fs.unlink(path.join(this.root, "credentials.bin")),
        fs.unlink(path.join(this.root, "connection.json")),
      ]);
    }
    this._publish({
      state: "disconnected",
      ready: false,
      tunnel_id: forget ? "" : this.status.tunnel_id,
      bridge_client_id: forget ? "" : this.status.bridge_client_id,
      detail: "Disconnected",
      health_url: "",
    });
    return this.getStatus();
  }

  shutdownSync() {
    this.manualStop = true;
    if (this.restartTimer) clearTimeout(this.restartTimer);
    const child = this.child;
    this.child = null;
    if (child && child.exitCode === null) {
      try {
        child.kill();
      } catch {
        // Process exit will reclaim the supervised tunnel if it already stopped.
      }
    }
    for (const fileName of ["runtime-key.tmp", "health-url.txt", "tunnel.pid", "owner.json"]) {
      try {
        fsSync.rmSync(path.join(this.root, fileName), { force: true });
      } catch {
        // Startup reconciliation treats stale runtime files as untrusted.
      }
    }
  }

  async _waitForReady(healthUrlPath, child, timeoutMs) {
    const deadline = performance.now() + timeoutMs;
    while (performance.now() < deadline) {
      if (child.exitCode !== null) throw new Error("Tunnel client exited during startup.");
      if (!this.healthUrl) {
        try {
          const candidate = (await fs.readFile(healthUrlPath, "utf8")).trim();
          const parsed = new URL(candidate);
          if (parsed.protocol === "http:" && ["127.0.0.1", "localhost", "::1"].includes(parsed.hostname)) {
            this.healthUrl = parsed.origin;
          }
        } catch {
          // The health URL file appears after the process binds its loopback listener.
        }
      }
      if (this.healthUrl && await probeReady(`${this.healthUrl}/readyz`, 1_000)) return;
      await delay(200);
    }
    throw new Error("Tunnel startup timed out.");
  }

  _scheduleRestart() {
    if (this.restartTimer || !this.activeConfiguration) return;
    if (this.restartAttempt >= 5) {
      this._publish({
        state: "attention_required",
        ready: false,
        detail: "Connection stopped. Check the tunnel key and network.",
      });
      return;
    }
    const delayMs = retryDelayMs(this.restartAttempt);
    this.restartAttempt += 1;
    this._publish({
      state: "connecting",
      ready: false,
      detail: "Reconnecting...",
    });
    this.restartTimer = setTimeout(async () => {
      this.restartTimer = null;
      const configuration = this.activeConfiguration;
      if (!configuration || this.manualStop) return;
      const credentials = await this._readCredentials().catch(() => null);
      if (credentials?.runtimeApiKey && credentials?.bridgeToken) {
        configuration.runtimeApiKey = credentials.runtimeApiKey;
        configuration.bridgeToken = credentials.bridgeToken;
      }
      void this.connect(configuration, { automatic: true }).catch(() => {
        // connect publishes a safe actionable state; process exits schedule the next retry.
      });
    }, delayMs);
  }

  _disableReconnect() {
    this.manualStop = true;
    this.activeConfiguration = null;
    this.restartAttempt = 0;
    if (this.restartTimer) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
  }

  async _stopChild(child) {
    if (!child || child.exitCode !== null) return;
    child.kill();
    await Promise.race([
      new Promise((resolve) => child.once("exit", resolve)),
      delay(3_000),
    ]);
    if (child.exitCode === null && child.pid) {
      await this.processTreeKiller(child.pid);
    }
  }

  async _writeCredentials(runtimeApiKey, bridgeToken) {
    if (!this.safeStorage?.isEncryptionAvailable?.()) {
      throw new Error("Windows credential protection is unavailable.");
    }
    const encrypted = this.safeStorage.encryptString(JSON.stringify({
      schema_version: TUNNEL_CREDENTIAL_SCHEMA_VERSION,
      runtime_api_key: runtimeApiKey,
      bridge_token: bridgeToken,
    }));
    await atomicWriteCredentialFile(path.join(this.root, "credentials.bin"), encrypted);
  }

  async _readCredentials() {
    try {
      if (!this.safeStorage?.isEncryptionAvailable?.()) return null;
      const encrypted = await fs.readFile(path.join(this.root, "credentials.bin"));
      const decrypted = this.safeStorage.decryptString(encrypted);
      try {
        const parsed = JSON.parse(decrypted);
        if (Number(parsed?.schema_version) > TUNNEL_CREDENTIAL_SCHEMA_VERSION) {
          return { incompatible: true };
        }
        if (parsed?.schema_version === TUNNEL_CREDENTIAL_SCHEMA_VERSION) {
          return {
            runtimeApiKey: String(parsed.runtime_api_key || ""),
            bridgeToken: String(parsed.bridge_token || ""),
          };
        }
      } catch {
        // Version 1 stored only the runtime key.
      }
      return { runtimeApiKey: decrypted, bridgeToken: "" };
    } catch {
      return null;
    }
  }

  async _writeMetadata(metadata) {
    const target = path.join(this.root, "connection.json");
    const temporary = `${target}.tmp`;
    await fs.writeFile(temporary, `${JSON.stringify({ schema_version: TUNNEL_METADATA_SCHEMA_VERSION, ...metadata }, null, 2)}\n`, {
      encoding: "utf8",
      mode: 0o600,
    });
    await fs.rename(temporary, target);
  }

  async _readMetadata() {
    try {
      const parsed = JSON.parse(await fs.readFile(path.join(this.root, "connection.json"), "utf8"));
      const schemaVersion = Number(parsed?.schema_version || 0);
      if (schemaVersion > TUNNEL_METADATA_SCHEMA_VERSION) {
        return { incompatible: true, schema_version: schemaVersion };
      }
      if (!TUNNEL_ID_PATTERN.test(String(parsed.tunnel_id || ""))) return null;
      const metadata = {
        tunnel_id: parsed.tunnel_id,
        capability_profile: parsed.capability_profile === "read_write" ? "read_write" : "read_only",
        bridge_client_id: String(parsed.bridge_client_id || ""),
        auto_connect: Boolean(parsed.auto_connect),
      };
      if (schemaVersion === 0) {
        await this._writeMetadata(metadata);
      }
      return metadata;
    } catch {
      return null;
    }
  }

  async _rotateLog(logPath) {
    try {
      const stat = await fs.stat(logPath);
      if (stat.size <= MAX_TUNNEL_LOG_BYTES) return;
      const previous = `${logPath}.1`;
      await fs.unlink(previous).catch(() => {});
      await fs.rename(logPath, previous);
    } catch {
      // A missing log is the normal first-run state.
    }
  }

  async _writeOwner(owner) {
    const target = path.join(this.root, "owner.json");
    await fs.writeFile(target, `${JSON.stringify(owner)}\n`, { encoding: "utf8", mode: 0o600 });
  }

  async _reconcileOrphan() {
    try {
      const owner = JSON.parse(await fs.readFile(path.join(this.root, "owner.json"), "utf8"));
      const pid = Number(owner.pid);
      const expectedBinary = path.resolve(String(owner.tunnel_binary || ""));
      if (!Number.isSafeInteger(pid) || pid <= 0 || !expectedBinary) return;
      const actualBinary = await this.processPathProvider(pid);
      if (actualBinary && sameExecutable(actualBinary, expectedBinary)) {
        await this.processTreeKiller(pid);
      }
    } catch {
      // Missing or unverifiable stale ownership state is removed without
      // terminating a process we cannot prove belongs to Vault.
    } finally {
      await Promise.allSettled([
        fs.unlink(path.join(this.root, "owner.json")),
        fs.unlink(path.join(this.root, "tunnel.pid")),
        fs.unlink(path.join(this.root, "health-url.txt")),
        fs.unlink(path.join(this.root, "runtime-key.tmp")),
      ]);
    }
  }

  _publish(patch) {
    this.status = { ...this.status, ...patch };
    this.onStatus(this.getStatus());
  }
}

function probeReady(url, timeoutMs) {
  return new Promise((resolve) => {
    const request = http.get(url, { timeout: timeoutMs }, (response) => {
      response.resume();
      resolve(response.statusCode >= 200 && response.statusCode < 300);
    });
    request.on("timeout", () => {
      request.destroy();
      resolve(false);
    });
    request.on("error", () => resolve(false));
  });
}

function inspectProcessPath(pid) {
  if (!Number.isSafeInteger(Number(pid)) || Number(pid) <= 0) return Promise.resolve("");
  return new Promise((resolve) => {
    const command = `(Get-CimInstance Win32_Process -Filter "ProcessId = ${Number(pid)}").ExecutablePath`;
    const child = spawn("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", command], {
      windowsHide: true,
      stdio: ["ignore", "pipe", "ignore"],
    });
    let output = "";
    child.stdout.on("data", (chunk) => {
      if (output.length < 32_768) output += String(chunk);
    });
    child.once("error", () => resolve(""));
    child.once("exit", () => resolve(output.trim()));
  });
}

function killProcessTree(pid) {
  if (!Number.isSafeInteger(Number(pid)) || Number(pid) <= 0) return Promise.resolve();
  return new Promise((resolve) => {
    const killer = spawn("taskkill.exe", ["/PID", String(Number(pid)), "/T", "/F"], {
      windowsHide: true,
      stdio: "ignore",
    });
    const timer = setTimeout(resolve, 3_000);
    killer.once("error", () => {
      clearTimeout(timer);
      resolve();
    });
    killer.once("exit", () => {
      clearTimeout(timer);
      resolve();
    });
  });
}

function sameExecutable(actual, expected) {
  const normalize = (value) => path.resolve(String(value || "")).replaceAll("/", "\\").toLowerCase();
  return Boolean(actual && expected && normalize(actual) === normalize(expected));
}

function safeTunnelError(error) {
  const message = String(error?.message || "").toLowerCase();
  if (message.includes("401") || message.includes("403") || message.includes("api key")) {
    return "OpenAI rejected the tunnel credentials.";
  }
  if (message.includes("timeout")) return "The tunnel could not connect in time.";
  return "The tunnel could not connect. Check your network and tunnel details.";
}

async function classifyTunnelFailure(error, logPath = "") {
  let logTail = "";
  if (logPath) {
    try {
      const stat = await fs.stat(logPath);
      const start = Math.max(0, stat.size - 65_536);
      const handle = await fs.open(logPath, "r");
      try {
        const buffer = Buffer.alloc(stat.size - start);
        await handle.read(buffer, 0, buffer.length, start);
        logTail = buffer.toString("utf8");
      } finally {
        await handle.close();
      }
    } catch {
      // A missing log is normal when the process cannot start.
    }
  }
  const normalized = `${String(error?.message || "")}\n${logTail}`.toLowerCase();
  if (
    /\b401\b|unauthori[sz]ed|invalid (?:api |runtime )?key|expired (?:api |runtime )?key/.test(
      normalized,
    )
  ) {
    return {
      permanent: true,
      code: "authentication_rejected",
      message: "OpenAI rejected the tunnel credentials.",
    };
  }
  if (/\b403\b|forbidden|permission denied|not permitted/.test(normalized)) {
    return {
      permanent: true,
      code: "permission_denied",
      message: "This tunnel is not allowed. Check its workspace permissions.",
    };
  }
  if (/incompatible|unsupported (?:client|version|protocol)/.test(normalized)) {
    return {
      permanent: true,
      code: "version_mismatch",
      message: "Update Vault before reconnecting this tunnel.",
    };
  }
  if (/\b429\b|rate.?limit|too many requests/.test(normalized)) {
    return {
      permanent: false,
      code: "rate_limited",
      message: "OpenAI is busy. Vault will retry shortly.",
    };
  }
  if (/certificate|tls|x509/.test(normalized)) {
    return {
      permanent: false,
      code: "tls_error",
      message: "Secure connection failed. Check the clock and network.",
    };
  }
  if (/dns|no such host|name resolution|getaddrinfo|enotfound/.test(normalized)) {
    return {
      permanent: false,
      code: "dns_error",
      message: "OpenAI could not be reached. Check the network.",
    };
  }
  if (/\b5\d\d\b|connection reset|econnreset/.test(normalized)) {
    return {
      permanent: false,
      code: "service_unavailable",
      message: "OpenAI is unavailable. Vault will retry.",
    };
  }
  return {
    permanent: false,
    code: "tunnel_unavailable",
    message: safeTunnelError(error),
  };
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function retryDelayMs(attempt, randomValue = Math.random()) {
  const cappedAttempt = Math.max(0, Math.min(Number(attempt) || 0, 6));
  const base = Math.min(1_000 * (2 ** cappedAttempt), 30_000);
  const jitter = Math.floor(base * 0.25 * Math.max(0, Math.min(randomValue, 1)));
  return base + jitter;
}

module.exports = {
  atomicWriteCredentialFile,
  TunnelManager,
  buildMcpCommand,
  buildTunnelArguments,
  classifyTunnelFailure,
  quoteCommandArgument,
  retryDelayMs,
  sameExecutable,
  safeTunnelError,
  validateTunnelConfiguration,
};
