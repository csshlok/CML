const fs = require("node:fs/promises");
const path = require("node:path");
const { randomUUID } = require("node:crypto");

const SETUP_SCHEMA_VERSION = 2;
const LEGACY_SETUP_SCHEMA_VERSION = 1;
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
    revision: 0,
    phase: "fresh",
    editable_step: 0,
    completed_capabilities: [],
    next_required_action: "complete_profile",
    profile: { display_name: "", avatar_path: "" },
    vault: { id: "", name: "", path: "" },
    chat_setup: { status: "pending", model_id: "" },
    model_storage: { download_root: "" },
    memory_setup: { status: "pending", model_id: "" },
    security_setup: { status: "not_started" },
    model_discovery: {
      status: "not_started",
      operation_id: "",
      scan_all_drives: false,
    },
    recoverable_error: null,
    tour: { status: "pending", step: 0, version: 1 },
    updated_at: new Date(0).toISOString(),
  };
}

function normalizeSetupState(value) {
  if (!value || typeof value !== "object") {
    throw new Error("Setup state must be an object.");
  }
  if (![LEGACY_SETUP_SCHEMA_VERSION, SETUP_SCHEMA_VERSION].includes(value.schema_version)) {
    throw new Error(`Unsupported setup-state schema version: ${value.schema_version}`);
  }
  if (!SETUP_PHASES.includes(value.phase)) {
    throw new Error(`Unsupported setup phase: ${value.phase}`);
  }
  const phaseIndex = SETUP_PHASES.indexOf(value.phase);
  const completedCapabilities = normalizeCompletedCapabilities(
    value.completed_capabilities,
    phaseIndex,
  );
  return {
    schema_version: SETUP_SCHEMA_VERSION,
    revision: Math.max(0, Number.isInteger(value.revision) ? value.revision : 0),
    phase: value.phase,
    editable_step: Math.max(
      0,
      Math.min(6, Number.isInteger(value.editable_step) ? value.editable_step : stepForPhase(value.phase)),
    ),
    completed_capabilities: completedCapabilities,
    next_required_action: stringValue(value.next_required_action) || nextActionForPhase(value.phase),
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
    security_setup: {
      status: capabilityStatus(
        value.security_setup?.status,
        phaseIndex >= SETUP_PHASES.indexOf("security_complete") ? "ready" : "not_started",
      ),
    },
    model_discovery: {
      status: capabilityStatus(value.model_discovery?.status, "not_started"),
      operation_id: stringValue(value.model_discovery?.operation_id),
      scan_all_drives: Boolean(value.model_discovery?.scan_all_drives),
    },
    recoverable_error: normalizeRecoverableError(value.recoverable_error),
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
  const phaseChanged = requestedPhase !== base.phase;
  const hasCompletedPatch = Object.prototype.hasOwnProperty.call(
    patch || {},
    "completed_capabilities",
  );
  const hasStepPatch = Object.prototype.hasOwnProperty.call(patch || {}, "editable_step");
  const hasNextActionPatch = Object.prototype.hasOwnProperty.call(
    patch || {},
    "next_required_action",
  );
  return normalizeSetupState({
    ...base,
    ...patch,
    schema_version: SETUP_SCHEMA_VERSION,
    revision: base.revision + 1,
    completed_capabilities: hasCompletedPatch
      ? patch.completed_capabilities
      : phaseChanged
        ? undefined
        : base.completed_capabilities,
    editable_step: hasStepPatch
      ? patch.editable_step
      : phaseChanged
        ? stepForPhase(requestedPhase)
        : base.editable_step,
    next_required_action: hasNextActionPatch
      ? patch.next_required_action
      : phaseChanged
        ? nextActionForPhase(requestedPhase)
        : base.next_required_action,
    profile: { ...base.profile, ...(patch?.profile || {}) },
    vault: { ...base.vault, ...(patch?.vault || {}) },
    chat_setup: { ...base.chat_setup, ...(patch?.chat_setup || {}) },
    model_storage: { ...base.model_storage, ...(patch?.model_storage || {}) },
    memory_setup: { ...base.memory_setup, ...(patch?.memory_setup || {}) },
    security_setup: { ...base.security_setup, ...(patch?.security_setup || {}) },
    model_discovery: { ...base.model_discovery, ...(patch?.model_discovery || {}) },
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

function capabilityStatus(value, fallback = "pending") {
  const status = stringValue(value);
  return [
    "not_started", "in_progress", "ready", "skipped", "paused",
    "failed_recoverable", "failed_terminal", "pending", "failed", "unknown",
  ].includes(status)
    ? status
    : fallback;
}

function normalizeCompletedCapabilities(value, phaseIndex) {
  if (Array.isArray(value)) {
    return [...new Set(value.map(stringValue).filter(Boolean))];
  }
  const thresholds = [
    ["profile", "profile_complete"],
    ["vault", "vault_committed"],
    ["chat_model", "models_complete"],
    ["memory_search", "memory_complete"],
    ["security", "security_complete"],
    ["setup", "complete"],
  ];
  return thresholds
    .filter(([, phase]) => phaseIndex >= SETUP_PHASES.indexOf(phase))
    .map(([capability]) => capability);
}

function stepForPhase(phase) {
  if (phase === "fresh") return 0;
  if (phase === "profile_complete" || phase === "vault_prepared") return 2;
  if (phase === "vault_committed") return 3;
  if (phase === "models_complete") return 4;
  if (phase === "memory_complete") return 5;
  return 6;
}

function nextActionForPhase(phase) {
  return {
    fresh: "complete_profile",
    profile_complete: "choose_library",
    vault_prepared: "finish_library_setup",
    vault_committed: "choose_chat_model",
    models_complete: "choose_memory_search",
    memory_complete: "protect_library",
    security_complete: "open_vault",
    complete: "none",
    recovery: "recover_setup",
  }[phase] || "recover_setup";
}

function normalizeRecoverableError(value) {
  if (!value || typeof value !== "object") return null;
  const code = stringValue(value.code);
  const message = stringValue(value.message);
  if (!code || !message) return null;
  return {
    code,
    message,
    action: stringValue(value.action),
    diagnostic_id: stringValue(value.diagnostic_id),
  };
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
