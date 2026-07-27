const fs = require("node:fs/promises");
const path = require("node:path");
const { randomUUID } = require("node:crypto");

const SETUP_SCHEMA_VERSION = 1;
const SETUP_PHASES = Object.freeze([
  "fresh",
  "profile_complete",
  "vault_prepared",
  "vault_committed",
  "models_complete",
  "memory_complete",
  "security_complete",
  "complete",
  "recovery",
]);

function setupStatePath(userDataPath) {
  return path.join(userDataPath, "setup-state.json");
}

function defaultSetupState() {
  return {
    schema_version: SETUP_SCHEMA_VERSION,
    phase: "fresh",
    profile: { display_name: "", avatar_path: "" },
    vault: { id: "", name: "", path: "" },
    chat_setup: { status: "pending", model_id: "" },
    model_storage: { download_root: "" },
    memory_setup: { status: "pending", model_id: "" },
    tour: { status: "pending", step: 0, version: 1 },
    updated_at: new Date(0).toISOString(),
  };
}

function normalizeSetupState(value) {
  if (!value || typeof value !== "object") {
    throw new Error("Setup state must be an object.");
  }
  if (value.schema_version !== SETUP_SCHEMA_VERSION) {
    throw new Error(`Unsupported setup-state schema version: ${value.schema_version}`);
  }
  if (!SETUP_PHASES.includes(value.phase)) {
    throw new Error(`Unsupported setup phase: ${value.phase}`);
  }
  return {
    schema_version: SETUP_SCHEMA_VERSION,
    phase: value.phase,
    profile: {
      display_name: stringValue(value.profile?.display_name),
      avatar_path: stringValue(value.profile?.avatar_path),
    },
    vault: {
      id: stringValue(value.vault?.id),
      name: stringValue(value.vault?.name),
      path: stringValue(value.vault?.path),
    },
    chat_setup: {
      status: capabilityStatus(value.chat_setup?.status),
      model_id: stringValue(value.chat_setup?.model_id),
    },
    model_storage: {
      download_root: stringValue(value.model_storage?.download_root),
    },
    memory_setup: {
      status: capabilityStatus(value.memory_setup?.status),
      model_id: stringValue(value.memory_setup?.model_id),
    },
    tour: {
      status: tourStatus(
        value.tour?.status,
        value.tour ? "pending" : value.phase === "complete" ? "skipped" : "pending",
      ),
      step: Math.max(0, Math.min(5, Number.isInteger(value.tour?.step) ? value.tour.step : 0)),
      version: 1,
    },
    updated_at: validTimestamp(value.updated_at) ? value.updated_at : new Date().toISOString(),
  };
}

function mergeSetupState(current, patch) {
  const base = normalizeSetupState(current);
  const requestedPhase = patch?.phase ?? base.phase;
  if (!SETUP_PHASES.includes(requestedPhase)) {
    throw new Error(`Unsupported setup phase: ${requestedPhase}`);
  }
  const currentIndex = SETUP_PHASES.indexOf(base.phase);
  const requestedIndex = SETUP_PHASES.indexOf(requestedPhase);
  if (
    requestedPhase !== "recovery" &&
    base.phase !== "recovery" &&
    requestedIndex < currentIndex
  ) {
    throw new Error(`Setup phase cannot move backward from ${base.phase} to ${requestedPhase}.`);
  }
  return normalizeSetupState({
    ...base,
    ...patch,
    schema_version: SETUP_SCHEMA_VERSION,
    profile: { ...base.profile, ...(patch?.profile || {}) },
    vault: { ...base.vault, ...(patch?.vault || {}) },
    chat_setup: { ...base.chat_setup, ...(patch?.chat_setup || {}) },
    model_storage: { ...base.model_storage, ...(patch?.model_storage || {}) },
    memory_setup: { ...base.memory_setup, ...(patch?.memory_setup || {}) },
    tour: { ...base.tour, ...(patch?.tour || {}) },
    updated_at: new Date().toISOString(),
  });
}

async function readSetupState(userDataPath, options = {}) {
  const target = setupStatePath(userDataPath);
  try {
    return normalizeSetupState(JSON.parse(await fs.readFile(target, "utf8")));
  } catch (error) {
    if (error?.code === "ENOENT") {
      if (options.activeVaultPath) {
        return normalizeSetupState({
          ...defaultSetupState(),
          phase: "complete",
          vault: { id: "", name: "", path: options.activeVaultPath },
          chat_setup: { status: "unknown", model_id: "" },
          memory_setup: { status: "unknown", model_id: "" },
          tour: { status: "skipped", step: 0, version: 1 },
          updated_at: new Date().toISOString(),
        });
      }
      return defaultSetupState();
    }
    const quarantinePath = `${target}.corrupt-${Date.now()}`;
    try {
      await fs.rename(target, quarantinePath);
    } catch {
      // Recovery remains available even if an antivirus scanner holds the bad file.
    }
    return normalizeSetupState({
      ...defaultSetupState(),
      phase: "recovery",
      updated_at: new Date().toISOString(),
    });
  }
}

async function writeSetupState(userDataPath, nextState) {
  const normalized = normalizeSetupState({
    ...nextState,
    updated_at: new Date().toISOString(),
  });
  await atomicWriteJson(setupStatePath(userDataPath), normalized);
  return normalized;
}

async function updateSetupState(userDataPath, patch, options = {}) {
  const current = await readSetupState(userDataPath, options);
  return writeSetupState(userDataPath, mergeSetupState(current, patch));
}

async function resetSetupState(userDataPath) {
  const target = setupStatePath(userDataPath);
  try {
    await fs.unlink(target);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
  return defaultSetupState();
}

async function atomicWriteJson(targetPath, value) {
  await fs.mkdir(path.dirname(targetPath), { recursive: true });
  const temporaryPath = `${targetPath}.${process.pid}.${randomUUID()}.tmp`;
  try {
    const handle = await fs.open(temporaryPath, "wx");
    try {
      await handle.writeFile(`${JSON.stringify(value, null, 2)}\n`, "utf8");
      await handle.sync();
    } finally {
      await handle.close();
    }
    await fs.rename(temporaryPath, targetPath);
  } finally {
    try {
      await fs.unlink(temporaryPath);
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
  }
}

function stringValue(value) {
  return typeof value === "string" ? value.trim() : "";
}

function capabilityStatus(value) {
  const status = stringValue(value);
  return ["pending", "ready", "skipped", "failed", "unknown"].includes(status)
    ? status
    : "pending";
}

function tourStatus(value, fallback = "pending") {
  const status = stringValue(value);
  return ["pending", "completed", "skipped"].includes(status) ? status : fallback;
}

function validTimestamp(value) {
  return typeof value === "string" && !Number.isNaN(Date.parse(value));
}

module.exports = {
  SETUP_PHASES,
  SETUP_SCHEMA_VERSION,
  atomicWriteJson,
  defaultSetupState,
  mergeSetupState,
  normalizeSetupState,
  readSetupState,
  resetSetupState,
  setupStatePath,
  updateSetupState,
  writeSetupState,
};
