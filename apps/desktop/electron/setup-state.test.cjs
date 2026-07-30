const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");

const {
  defaultSetupState,
  mergeSetupState,
  readSetupState,
  resetSetupState,
  setupStatePath,
  updateSetupState,
} = require("./setup-state.cjs");

const temporaryDirectories = new Set();

async function temporaryUserData() {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "cml-setup-state-"));
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

test("new profile starts fresh and resumes durable setup progress", async () => {
  const root = await temporaryUserData();
  assert.equal((await readSetupState(root)).phase, "fresh");

  await updateSetupState(root, {
    phase: "profile_complete",
    profile: { display_name: "Ada" },
  });

  const resumed = await readSetupState(root);
  assert.equal(resumed.phase, "profile_complete");
  assert.equal(resumed.profile.display_name, "Ada");
  assert.equal(resumed.tour.status, "pending");
  assert.equal(resumed.schema_version, 2);
  assert.equal(resumed.revision, 1);
  assert.ok(resumed.completed_capabilities.includes("profile"));
  assert.equal(resumed.next_required_action, "choose_library");
});

test("legacy valid active vault is inferred complete without renderer storage", async () => {
  const root = await temporaryUserData();
  const state = await readSetupState(root, { activeVaultPath: "C:\\Vaults\\Personal" });
  assert.equal(state.phase, "complete");
  assert.equal(state.vault.path, "C:\\Vaults\\Personal");
  assert.equal(state.tour.status, "skipped");
});

test("first-use tour progress and completion persist without changing setup phase", async () => {
  const root = await temporaryUserData();
  await updateSetupState(root, { phase: "complete", tour: { status: "pending", step: 3 } });
  let state = await readSetupState(root);
  assert.equal(state.phase, "complete");
  assert.deepEqual(state.tour, { status: "pending", step: 3, version: 1 });

  await updateSetupState(root, { tour: { status: "completed", step: 5 } });
  state = await readSetupState(root);
  assert.deepEqual(state.tour, { status: "completed", step: 5, version: 1 });
});

test("selected model storage root persists across setup resume", async () => {
  const root = await temporaryUserData();
  await updateSetupState(root, {
    model_storage: { download_root: "D:\\Vault Models" },
  });

  const resumed = await readSetupState(root);
  assert.equal(resumed.model_storage.download_root, "D:\\Vault Models");
});

test("partial profile updates preserve the onboarding name and saved avatar", async () => {
  const root = await temporaryUserData();
  await updateSetupState(root, {
    phase: "profile_complete",
    profile: { display_name: "Ada", avatar_path: "media/avatar-one.png" },
  });

  await updateSetupState(root, {
    profile: { avatar_path: "media/avatar-two.png" },
  });
  let state = await readSetupState(root);
  assert.deepEqual(state.profile, {
    display_name: "Ada",
    avatar_path: "media/avatar-two.png",
  });

  await updateSetupState(root, {
    profile: { display_name: "Ada Lovelace" },
  });
  state = await readSetupState(root);
  assert.deepEqual(state.profile, {
    display_name: "Ada Lovelace",
    avatar_path: "media/avatar-two.png",
  });
});

test("setup state rejects accidental backward transitions", () => {
  const current = {
    ...defaultSetupState(),
    phase: "models_complete",
  };
  assert.throws(
    () => mergeSetupState(current, { phase: "vault_committed" }),
    /cannot move backward/,
  );
});

test("corrupt setup state is quarantined and opens recovery", async () => {
  const root = await temporaryUserData();
  await fs.writeFile(setupStatePath(root), "{broken", "utf8");

  const state = await readSetupState(root);
  const files = await fs.readdir(root);
  assert.equal(state.phase, "recovery");
  assert.ok(files.some((name) => name.startsWith("setup-state.json.corrupt-")));
});

test("reset removes only app setup state and leaves vault data untouched", async () => {
  const root = await temporaryUserData();
  const vaultFile = path.join(root, "Personal", ".vault", "cml.sqlite3");
  await fs.mkdir(path.dirname(vaultFile), { recursive: true });
  await fs.writeFile(vaultFile, "vault-data", "utf8");
  await updateSetupState(root, { phase: "profile_complete" });

  await resetSetupState(root);

  assert.equal((await readSetupState(root)).phase, "fresh");
  assert.equal(await fs.readFile(vaultFile, "utf8"), "vault-data");
});

test("version one setup state migrates to the authoritative capability snapshot", async () => {
  const root = await temporaryUserData();
  await fs.writeFile(
    setupStatePath(root),
    JSON.stringify({
      schema_version: 1,
      phase: "models_complete",
      profile: { display_name: "Ada" },
      vault: { id: "vault-1", name: "Library", path: "C:\\Library" },
      chat_setup: { status: "ready", model_id: "model-1" },
      model_storage: { download_root: "D:\\Models" },
      memory_setup: { status: "pending", model_id: "" },
      updated_at: new Date().toISOString(),
    }),
    "utf8",
  );

  const migrated = await readSetupState(root);

  assert.equal(migrated.schema_version, 2);
  assert.equal(migrated.phase, "models_complete");
  assert.deepEqual(
    migrated.completed_capabilities,
    ["profile", "vault", "chat_model"],
  );
  assert.equal(migrated.next_required_action, "choose_memory_search");
  assert.equal(migrated.security_setup.status, "not_started");
  assert.equal(migrated.model_discovery.status, "not_started");
});
