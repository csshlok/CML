import { expect, test, type Page } from "@playwright/test";

const backendOrigin = "http://127.0.0.1:7343";

async function installDesktopBridge(page: Page) {
  await page.addInitScript(({ origin }) => {
    const state = { maximized: false, fullScreen: false };
    Object.defineProperty(window, "cmlDesktop", {
      configurable: true,
      value: {
        getBackendUrl: async () => origin,
        getBackendToken: async () => "rendered-shell-test-token",
        notifyRendererReady: async () => undefined,
        windowControls: {
          getState: async () => state,
          onStateChanged: () => () => undefined,
          minimize: async () => undefined,
          toggleMaximize: async () => ({ ...state, maximized: !state.maximized }),
          close: async () => undefined,
        },
      },
    });
  }, { origin: backendOrigin });
}

async function installBaseRoutes(page: Page) {
  await page.route(`${backendOrigin}/api/v1/**`, (route) => {
    const url = new URL(route.request().url());
    const emptyPage = { items: [], next_cursor: null, has_more: false, total: 0 };
    if (url.pathname.endsWith("/vaults")) return route.fulfill({ json: [] });
    if (url.pathname.includes("/page")) return route.fulfill({ json: emptyPage });
    if (url.pathname.endsWith("/count")) return route.fulfill({ json: { count: 0 } });
    if (url.pathname.endsWith("/folders")) return route.fulfill({ json: emptyPage });
    return route.fulfill({ json: [] });
  });
  await page.route(`${backendOrigin}/health`, (route) =>
    route.fulfill({ json: { status: "ok" } }),
  );
  await page.route(`${backendOrigin}/api/v1/system/backend-identity`, (route) =>
    route.fulfill({ json: { service: "cml-backend", api_prefix: "/api/v1" } }),
  );
}

test.beforeEach(async ({ page }) => {
  await installDesktopBridge(page);
  await installBaseRoutes(page);
});

test("assistant messages render bold Markdown without visible delimiters", async ({ page }) => {
  const consoleProblems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      consoleProblems.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => consoleProblems.push(`pageerror: ${error.message}`));
  const sessionId = "chat-markdown";
  const now = "2026-07-30T10:00:00Z";
  const session = {
    id: sessionId,
    vault_id: "vault-rendered",
    title: "Markdown rendering",
    scope_cluster_id: null,
    scope_project_id: null,
    scope_unclustered: false,
    saved: false,
    memory_status: "ready",
    memory_updated_at: now,
    active_generation: false,
    created_at: now,
    updated_at: now,
    messages: [],
  };
  await page.route(`${backendOrigin}/api/v1/vaults`, (route) =>
    route.fulfill({
      json: [{
        id: "vault-rendered",
        name: "Rendered vault",
        path: "T:\\rendered",
        created_at: now,
        updated_at: now,
      }],
    }),
  );
  await page.route(
    `${backendOrigin}/api/v1/chat/sessions/${sessionId}/metadata`,
    (route) => route.fulfill({ json: session }),
  );
  await page.route(
    `${backendOrigin}/api/v1/chat/sessions/${sessionId}/timeline*`,
    (route) =>
      route.fulfill({
        json: {
          session_id: sessionId,
          items: [{
            message_type: "assistant_message",
            sort_key: `${now}:message-assistant`,
            id: "message-assistant",
            session_id: sessionId,
            role: "assistant",
            content: "This is a **bold assessment** with safe <script>text</script>.",
            clusters_used: [],
            citations: [],
            warnings: [],
            useful: null,
            saved: false,
            created_at: now,
            generation_id: "generation-markdown",
            reply_to_message_id: null,
            generation_state: "completed",
            attachments: [],
          }],
          next_cursor: null,
          latest_cursor: `${now}:message-assistant`,
          has_more: false,
        },
      }),
  );
  await page.route(`${backendOrigin}/api/v1/models/runtime`, (route) =>
    route.fulfill({ json: { state: "ready", available: true } }),
  );

  await page.goto(`/chat/${sessionId}`);
  await expect(page).toHaveTitle("Chat");
  const strong = page.locator("strong", { hasText: "bold assessment" });
  await expect(strong).toBeVisible();
  const answer = page.locator("p").filter({ hasText: "This is a bold assessment" });
  await expect(answer).toContainText("This is a bold assessment with safe <script>text</script>.");
  await expect(answer).not.toContainText("**");
  await expect(answer.locator("script")).toHaveCount(0);
  expect(consoleProblems).toEqual([]);

  if (process.env.CML_QA_SCREENSHOT) {
    await page.screenshot({ path: process.env.CML_QA_SCREENSHOT, fullPage: false });
  }
});

test("project detail distinguishes Odin freshness from Git changes", async ({ page }) => {
  const consoleProblems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      consoleProblems.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => consoleProblems.push(`pageerror: ${error.message}`));
  const project = {
    id: "project-rendered",
    vault_id: "vault-rendered",
    name: "Snapshot semantics",
    root_path: "T:\\CML",
    root_fingerprint: "root",
    discovery_scope: "code",
    primary_cluster_id: "cluster-rendered",
    repository_kind: "git",
    git_remote_fingerprint: null,
    default_branch: "main",
    indexed_commit: "0123456789abcdef",
    working_tree_dirty: true,
    changed_file_count: 0,
    auto_sync_enabled: true,
    sync_mode: "automatic",
    change_fingerprint: "fingerprint",
    last_change_checked_at: "2026-07-30T08:30:00Z",
    status: "ready",
    structure_status: "ready",
    retrieval_status: "ready",
    interpretation_status: "unavailable",
    active_snapshot_id: "snapshot-active",
    active_manifest_snapshot_id: "snapshot-active",
    active_structure_snapshot_id: "snapshot-active",
    active_retrieval_snapshot_id: "snapshot-active",
    candidate_snapshot_id: null,
    active_run_id: null,
    active_snapshot: null,
    brief: "A rendered project used to verify freshness semantics.",
    languages: { TypeScript: 12 },
    workspace_count: 1,
    entrypoints: ["src/main.ts"],
    source_count: 578,
    created_at: "2026-07-30T08:00:00Z",
    updated_at: "2026-07-30T08:30:00Z",
  };
  const changes = {
    project_id: project.id,
    changed: false,
    change_fingerprint: "fingerprint",
    previous_fingerprint: "fingerprint",
    fingerprint_changed: false,
    detection_mode: "snapshot_git_delta",
    changed_paths: [],
    change_items: [],
    changed_path_count: 0,
    truncated: false,
    requires_full_scan: false,
    repository_detection_mode: "git_delta",
    repository_changed_paths: ["backend/app/core/projects.py", "apps/desktop/src/routes/project.tsx"],
    repository_change_items: [
      { kind: "modified", path: "backend/app/core/projects.py", previous_path: null },
      { kind: "modified", path: "apps/desktop/src/routes/project.tsx", previous_path: null },
    ],
    repository_changed_path_count: 2,
    repository_truncated: false,
    working_tree_dirty: true,
    last_checked_at: "2026-07-30T08:30:00Z",
    auto_sync_enabled: true,
    sync_mode: "automatic",
  };
  await page.route(`${backendOrigin}/api/v1/projects/${project.id}`, (route) =>
    route.fulfill({ json: project }),
  );
  await page.route(`${backendOrigin}/api/v1/projects/${project.id}/runs*`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`${backendOrigin}/api/v1/projects/${project.id}/links`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`${backendOrigin}/api/v1/projects/${project.id}/changes*`, (route) =>
    route.fulfill({ json: changes }),
  );
  await page.route(`${backendOrigin}/api/v1/clusters*`, (route) =>
    route.fulfill({ json: [] }),
  );

  await page.goto(`/projects/${project.id}`);
  await expect(page).toHaveTitle("Project");
  await expect(page.getByRole("heading", { name: project.name })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Odin freshness" })).toBeVisible();
  await expect(
    page.getByText(/The active Odin snapshot matches the current eligible files\./).first(),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Git repository status" })).toBeVisible();
  await expect(page.getByText(/Git reports 2 changed working-tree paths/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Sync changes" })).toHaveCount(0);
  await page.getByRole("button", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Project settings" })).toBeVisible();
  expect(consoleProblems).toEqual([]);

  if (process.env.CML_QA_SCREENSHOT) {
    await page.screenshot({ path: process.env.CML_QA_SCREENSHOT, fullPage: true });
  }
});

test("unknown routes provide keyboard-focused recovery", async ({ page }) => {
  await page.goto("/this-route-does-not-exist");
  const heading = page.getByRole("heading", { name: "Page not found" });
  await expect(heading).toBeVisible();
  await expect(heading).toBeFocused();
  const recovery = page.getByRole("link", { name: "Return home" });
  await recovery.focus();
  await recovery.press("Enter");
  await expect(page).toHaveURL(/\/onboarding$/);
});

test("window-aware controls never intersect native controls at minimum size", async ({ page }) => {
  await page.goto("/projects");
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();
  await expect(page.getByLabel("Window controls")).toBeVisible();

  const geometry = await page.evaluate(() => {
    const safe = document.querySelector<HTMLElement>("[data-window-control-safe-zone]")
      ?.getBoundingClientRect();
    const collisions = [...document.querySelectorAll<HTMLElement>(".vault-window-aware > *")]
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        return Boolean(
          safe
          && rect.right > safe.left
          && rect.left < safe.right
          && rect.bottom > safe.top
          && rect.top < safe.bottom,
        );
      })
      .map((element) => element.textContent?.trim().slice(0, 80) || element.tagName);
    return {
      safe: safe && { left: safe.left, right: safe.right, top: safe.top, bottom: safe.bottom },
      collisions,
    };
  });

  expect(geometry.safe).toEqual({ left: 874, right: 1024, top: 0, bottom: 44 });
  expect(geometry.collisions).toEqual([]);
});

test("import progress is viewport draggable and restores its saved position", async ({ page }) => {
  const job = {
    id: "rendered-import-1",
    job_type: "source_import_batch",
    status: "running",
    payload: "{}",
    result_json: JSON.stringify({
      total_files: 48,
      completed_files: 6,
      imported_files: 5,
      updated_files: 0,
      failed_files: 1,
      failures: [{ file_name: "locked.pdf", reason: "The PDF is encrypted." }],
      current_file: "Correlation Inference.pdf",
      truncated_at: null,
    }),
    dedupe_key: null,
    attempts: 1,
    max_attempts: 3,
    last_error: "",
    created_at: "2026-07-29T12:00:00Z",
    updated_at: "2026-07-29T12:00:10Z",
  };
  await page.route(`${backendOrigin}/api/v1/sources/import-jobs/active*`, (route) =>
    route.fulfill({ json: job }),
  );
  await page.route(`${backendOrigin}/api/v1/jobs/${job.id}`, (route) =>
    route.fulfill({ json: job }),
  );

  await page.goto("/sources");
  const popup = page.locator("[data-source-import-popup=true]");
  const handle = page.getByRole("button", { name: "Move file import progress" });
  await expect(popup).toBeVisible();
  const initial = await popup.boundingBox();
  const grip = await handle.boundingBox();
  expect(initial).not.toBeNull();
  expect(grip).not.toBeNull();

  await page.mouse.move(grip!.x + grip!.width / 2, grip!.y + grip!.height / 2);
  await page.mouse.down();
  await page.mouse.move(250, 200, { steps: 8 });
  await page.mouse.up();
  const moved = await popup.boundingBox();
  expect(moved!.x).toBeLessThan(initial!.x - 200);
  expect(moved!.y).toBeLessThan(initial!.y - 150);

  const stored = await page.evaluate(() =>
    localStorage.getItem("vault.source-import-popup.position.v1"),
  );
  expect(stored).toBeTruthy();

  await page.reload();
  await expect(popup).toBeVisible();
  const restored = await popup.boundingBox();
  expect(Math.abs(restored!.x - moved!.x)).toBeLessThanOrEqual(2);
  expect(Math.abs(restored!.y - moved!.y)).toBeLessThanOrEqual(2);

  await handle.focus();
  await handle.press("Escape");
  const reset = await popup.boundingBox();
  expect(reset!.x).toBeGreaterThan(650);
  expect(reset!.y).toBeGreaterThan(450);
});

test("locked library reports a wrong passphrase beside the unlock form", async ({ page }) => {
  let locked = true;
  const status = () => ({
    state: locked ? "locked" : "ready",
    ready: !locked,
    secured_vault_count: 1,
    vault_id: "vault-locked",
    secured_vault_ids: ["vault-locked"],
    unlock_mode: "full",
    pin_enabled: false,
    verification_error: "",
    updated_at: "2026-07-29T12:00:00Z",
    has_vendor_recovery: true,
    message: locked ? "Library locked." : "Library ready.",
  });
  await page.route(`${backendOrigin}/api/v1/system/unlock/status`, (route) =>
    route.fulfill({ json: status() }),
  );
  await page.route(`${backendOrigin}/api/v1/system/unlock/passphrase`, async (route) => {
    const payload = route.request().postDataJSON() as { passphrase?: string };
    if (payload.passphrase !== "correct horse") {
      return route.fulfill({
        status: 400,
        json: {
          detail: "Incorrect passphrase. Try again.",
          error: {
            code: "invalid_vault_secret",
            message: "Incorrect passphrase. Try again.",
            action: null,
            diagnostic_id: null,
            retryable: false,
            field_issues: [],
          },
        },
      });
    }
    locked = false;
    return route.fulfill({ json: status() });
  });

  await page.goto(`/home?backendUrl=${encodeURIComponent(backendOrigin)}`);
  await expect(page.getByRole("heading", { name: "Library locked" })).toBeVisible();
  const passphrase = page.getByLabel("Passphrase");
  await passphrase.fill("wrong");
  await page.getByRole("button", { name: "Unlock", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText("Incorrect passphrase. Try again.");
  await expect(passphrase).toBeFocused();

  await passphrase.fill("correct horse");
  await page.getByRole("button", { name: "Unlock", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Library locked" })).toHaveCount(0);
});

test("minimum viewport remains usable with large text and reduced motion", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/projects");
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();
  await page.evaluate(() => {
    document.documentElement.style.fontSize = "200%";
  });
  await page.waitForTimeout(100);

  const layout = await page.evaluate(() => {
    const safe = document.querySelector<HTMLElement>("[data-window-control-safe-zone]")
      ?.getBoundingClientRect();
    const collisionCount = [...document.querySelectorAll<HTMLElement>(".vault-window-aware > *")]
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        return Boolean(
          safe
          && rect.right > safe.left
          && rect.left < safe.right
          && rect.bottom > safe.top
          && rect.top < safe.bottom,
        );
      }).length;
    return {
      collisionCount,
      horizontalOverflow: document.documentElement.scrollWidth - window.innerWidth,
    };
  });
  expect(layout.collisionCount).toBe(0);
  expect(layout.horizontalOverflow).toBeLessThanOrEqual(1);
  await expect(page.getByRole("button", { name: "Add project" })).toBeVisible();
});

test("model loss is visible while enrichment waits for recovery", async ({ page }) => {
  const recoveryJob = {
    id: "model-recovery-1",
    job_type: "model_runtime_recovery",
    status: "running",
    payload: "{}",
    result_json: "{}",
    dedupe_key: "model-runtime-recovery",
    attempts: 1,
    max_attempts: 3,
    last_error: "",
    created_at: "2026-07-29T12:00:00Z",
    updated_at: "2026-07-29T12:00:10Z",
  };
  await page.route(`${backendOrigin}/api/v1/jobs/status`, (route) =>
    route.fulfill({
      json: {
        queued: 0,
        paused: 0,
        blocked_by_dependency: 0,
        blocked_setup_required: 0,
        blocked_local_model: 12,
        deferred: 0,
        running: 1,
        succeeded: 0,
        partial_success: 0,
        failed: 0,
        cancelled: 0,
        manual_review: 0,
        running_jobs: [recoveryJob],
        latest: [recoveryJob],
      },
    }),
  );
  await page.route(`${backendOrigin}/api/v1/models/runtime`, (route) =>
    route.fulfill({
      json: {
        provider: "managed",
        base_url: "http://127.0.0.1:8000",
        model: "local-chat",
        available: false,
        state: "starting",
        detail: "Starting",
        managed: true,
      },
    }),
  );

  await page.goto(`/projects?backendUrl=${encodeURIComponent(backendOrigin)}`);
  await expect(page.getByText("Local model unavailable", { exact: true })).toBeVisible();
  await expect(
    page.getByText(
      "Document descriptions and clustering are paused while Vault restarts the model.",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Open settings" })).toBeVisible();
});

test("settings never starts a computer model scan while polling", async ({ page }) => {
  let discoveryRequests = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/v1/models/discover") {
      discoveryRequests += 1;
    }
  });
  await page.route(`${backendOrigin}/api/v1/system/unlock/status`, (route) =>
    route.fulfill({
      json: {
        state: "ready",
        ready: true,
        secured_vault_count: 0,
        secured_vault_ids: [],
        vault_id: null,
        unlock_mode: "strict",
        pin_enabled: false,
        message: "Ready",
        verification_error: "",
        updated_at: "2026-07-29T12:00:00Z",
        has_vendor_recovery: false,
      },
    }),
  );
  await page.route(`${backendOrigin}/api/v1/models/recommendations`, (route) =>
    route.fulfill({
      json: {
        hardware: {},
        recommended_model_id: "",
        recommended_chat_model_id: "",
        chat_fit_type: "",
        evidence_level: "none",
        confidence: "low",
        warnings: [],
        reasons: [],
        fallback_low_spec: {},
        fallback_fastest: {},
        active_chat_setup: {},
        chat_recommendation: {},
        models: [],
        detected_compatible_models: [],
        detected_compatible_model_count: 0,
        detail: "Scan this computer to find compatible models.",
      },
    }),
  );
  await page.route(`${backendOrigin}/api/v1/models/runtime`, (route) =>
    route.fulfill({
      json: { provider: "managed", base_url: "", model: "", available: false, detail: "Not started" },
    }),
  );
  await page.route(`${backendOrigin}/api/v1/models/embeddings`, (route) =>
    route.fulfill({
      json: {
        provider: "sentence-transformers",
        model: "",
        dimensions: 0,
        available: false,
        detail: "Not configured",
        setup_required: true,
        cache_dir: null,
      },
    }),
  );
  await page.route(`${backendOrigin}/api/v1/models/embeddings/download`, (route) =>
    route.fulfill({
      json: {
        model_id: "embeddings",
        status: "idle",
        bytes_downloaded: 0,
        total_bytes: 0,
        local_path: null,
        file_name: null,
        error: null,
      },
    }),
  );
  await page.route(`${backendOrigin}/api/v1/system/ocr`, (route) =>
    route.fulfill({
      json: {
        available: false,
        image_ocr_available: false,
        pdf_ocr_available: false,
        full_pdf_ocr_available: false,
        missing: [],
      },
    }),
  );
  await page.route(`${backendOrigin}/api/v1/system/hardware`, (route) =>
    route.fulfill({
      json: { os: "Windows", machine: "x64", processor: "Test", cpu_count: 8, hardware_tier: "balanced" },
    }),
  );
  await page.route(`${backendOrigin}/api/v1/jobs/status`, (route) =>
    route.fulfill({
      json: {
        queued: 0,
        paused: 0,
        blocked_by_dependency: 0,
        blocked_setup_required: 0,
        blocked_local_model: 0,
        deferred: 0,
        running: 0,
        succeeded: 0,
        partial_success: 0,
        failed: 0,
        cancelled: 0,
        manual_review: 0,
        running_jobs: [],
        latest: [],
      },
    }),
  );

  await page.goto(`/settings?section=profile&backendUrl=${encodeURIComponent(backendOrigin)}`);
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  await page.waitForTimeout(300);
  expect(discoveryRequests).toBe(0);

  await page.goto(`/settings?section=models&backendUrl=${encodeURIComponent(backendOrigin)}`);
  await expect(page.getByRole("heading", { name: "Local chat model" })).toBeVisible();
  await page.waitForTimeout(1_000);
  expect(discoveryRequests).toBe(0);
  await page.getByRole("button", { name: "Manage models" }).click();
  await expect(page.getByRole("button", { name: /scan this computer/i })).toBeVisible();
  expect(discoveryRequests).toBe(0);
});
