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

async function temporaryUserData() {
  return fs.mkdtemp(path.join(os.tmpdir(), "cml-setup-state-"));
}

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
