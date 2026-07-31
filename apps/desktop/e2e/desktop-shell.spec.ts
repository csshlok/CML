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
        getSetupState: async () => ({
          phase: "complete",
          profile: { display_name: "Shlok", avatar_path: "" },
        }),
        getMcpFeatureFlags: async () => ({
          chatgpt_mcp_setup: true,
          secure_mcp_tunnel: true,
          chatgpt_mcp_write_tools: true,
          mcp_streaming: false,
          mcp_remote_http: false,
        }),
        getMcpLauncher: async () => null,
        getTunnelStatus: async () => null,
        onTunnelStatusChanged: () => () => undefined,
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

test("default Home places Quick actions in the second section", async ({ page }) => {
  const consoleProblems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      consoleProblems.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => consoleProblems.push(`pageerror: ${error.message}`));

  await page.goto("/home");
  await expect(page).toHaveTitle("Home");
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Ask Vault" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Quick actions" })).toBeAttached();

  const visibleSectionText = await page.locator("main section").evaluateAll((sections) =>
    sections.map((section) => section.textContent?.replace(/\s+/g, " ").trim() ?? ""),
  );
  expect(visibleSectionText[0]).toContain("Ask Vault");
  expect(visibleSectionText[1]).toContain("Add source");
  expect(visibleSectionText[1]).toContain("Start chat");
  expect(consoleProblems).toEqual([]);

  if (process.env.CML_QA_HOME_SCREENSHOT) {
    await page.screenshot({
      path: process.env.CML_QA_HOME_SCREENSHOT,
      fullPage: false,
    });
  }
});

test("Tasks opens on active work and clears stale detail across filters", async ({ page }) => {
  const consoleProblems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      consoleProblems.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => consoleProblems.push(`pageerror: ${error.message}`));

  const now = "2026-07-31T10:00:00Z";
  const makeJob = (overrides: Record<string, unknown>) => ({
    id: "job-default",
    job_type: "source_metadata_enrichment",
    status: "queued",
    payload: "{}",
    result_json: null,
    dedupe_key: null,
    priority: "normal",
    write_scope: "source",
    scope_id: null,
    resource_cost: "normal",
    user_visible: 1,
    cancellable: 1,
    preemptable: 1,
    timeout_seconds: 600,
    started_at: null,
    completed_at: null,
    elapsed_seconds: null,
    estimated_remaining_seconds: null,
    status_detail: "Waiting for an available worker.",
    cancellation_requested: 0,
    cancellation_requested_at: null,
    attempts: 0,
    max_attempts: 3,
    last_error: "",
    error_code: "",
    diagnostic_id: "",
    created_at: now,
    updated_at: now,
    ...overrides,
  });
  const runningJob = makeJob({
    id: "job-running",
    job_type: "refresh_cluster_profile",
    status: "running",
    status_detail: "Refreshed 42 clusters.",
    started_at: now,
    elapsed_seconds: 18,
  });
  const queuedJob = makeJob({
    id: "job-queued",
    job_type: "source_cluster_reconciliation",
  });
  const failedJob = makeJob({
    id: "job-failed",
    job_type: "vault_integrity_check",
    status: "failed",
    status_detail: "Integrity check stopped.",
    last_error: "Integrity check stopped.",
    cancellable: 0,
    preemptable: 0,
    attempts: 1,
  });

  await page.route(`${backendOrigin}/api/v1/jobs/status`, (route) =>
    route.fulfill({
      json: {
        queued: 1,
        paused: 0,
        blocked_by_dependency: 0,
        blocked_setup_required: 0,
        blocked_local_model: 0,
        deferred: 0,
        running: 1,
        succeeded: 0,
        partial_success: 0,
        failed: 1,
        cancelled: 0,
        manual_review: 0,
        running_jobs: [runningJob],
        latest: [runningJob, queuedJob, failedJob],
      },
    }),
  );
  await page.route(
    (url) => url.origin === backendOrigin && url.pathname === "/api/v1/jobs",
    (route) =>
      route.fulfill({
        json: {
          items: [runningJob, queuedJob, failedJob],
          next_cursor: null,
          has_more: false,
        },
      }),
  );
  await page.route(`${backendOrigin}/api/v1/projects/project-run-summary?*`, (route) =>
    route.fulfill({ json: { items: [] } }),
  );

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/tasks");
  await expect(page).toHaveTitle("Tasks");
  await expect(page.getByRole("heading", { name: "Tasks" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Active 2/ })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("Update cluster details", { exact: true })).toBeVisible();
  await expect(page.getByText("Organize analyzed sources", { exact: true })).toBeVisible();
  await expect(page.getByText("Vault Integrity Check", { exact: true })).not.toBeVisible();

  await page.getByText("Organize analyzed sources", { exact: true }).click();
  await expect(page.getByRole("heading", { name: "Job detail" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Organize analyzed sources" })).toBeVisible();

  await page.getByRole("button", { name: /Needs attention 1/ }).click();
  await expect(page.getByText("Vault Integrity Check", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Job detail" })).not.toBeVisible();
  await page.getByText("Vault Integrity Check", { exact: true }).click();
  await expect(page.getByRole("heading", { name: "Vault Integrity Check" })).toBeVisible();
  expect(consoleProblems).toEqual([]);

  if (process.env.CML_QA_TASKS_SCREENSHOT) {
    await page.screenshot({
      path: process.env.CML_QA_TASKS_SCREENSHOT,
      fullPage: false,
    });
  }
});

test("timeline refreshes on demand and once per visible minute", async ({ page }) => {
  const consoleProblems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      consoleProblems.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => consoleProblems.push(`pageerror: ${error.message}`));
  await page.clock.install({ time: new Date("2026-07-31T09:00:00Z") });

  let activityRequests = 0;
  await page.route(`${backendOrigin}/api/v1/vaults`, (route) =>
    route.fulfill({
      json: [{
        id: "vault-timeline",
        name: "Timeline vault",
        path: "T:\\timeline",
        created_at: "2026-07-31T08:00:00Z",
        updated_at: "2026-07-31T08:00:00Z",
      }],
    }),
  );
  await page.route(`${backendOrigin}/api/v1/activity*`, (route) => {
    activityRequests += 1;
    return route.fulfill({
      json: {
        items: [{
          id: `activity-${activityRequests}`,
          kind: "source",
          time: "2026-07-31T08:30:00Z",
          title: `Timeline activity ${activityRequests}`,
          detail: `Refresh response ${activityRequests}`,
          href: "/sources",
        }],
        next_cursor: null,
        has_more: false,
        total: 1,
        limit: 100,
        offset: 0,
      },
    });
  });

  await page.goto("/timeline");
  await expect(page).toHaveTitle("Timeline");
  await expect(page.getByRole("heading", { name: "Timeline" })).toBeVisible();
  await expect(page.getByText("Timeline activity 1")).toBeVisible();
  await expect(page.getByText("Updates automatically every 60 seconds")).toBeVisible();
  expect(activityRequests).toBe(1);

  await page.clock.fastForward(59_000);
  expect(activityRequests).toBe(1);

  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(page.getByText("Timeline activity 2")).toBeVisible();
  expect(activityRequests).toBe(2);

  await page.clock.fastForward(59_000);
  expect(activityRequests).toBe(2);
  await page.clock.fastForward(1_000);
  await expect(page.getByText("Timeline activity 3")).toBeVisible();
  expect(activityRequests).toBe(3);
  expect(consoleProblems).toEqual([]);

  if (process.env.CML_QA_TIMELINE_SCREENSHOT) {
    await page.screenshot({
      path: process.env.CML_QA_TIMELINE_SCREENSHOT,
      fullPage: false,
    });
  }
});

test("Profile shows its library and the Health command opens a draggable latest check", async ({ page }) => {
  const consoleProblems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      consoleProblems.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => consoleProblems.push(`pageerror: ${error.message}`));

  const now = "2026-07-31T10:00:00Z";
  await page.route(
    (url) => url.origin === backendOrigin && url.pathname === "/api/v1/vaults",
    (route) =>
    route.fulfill({
      json: [{
        id: "vault-profile",
        name: "Research Library",
        path: "T:\\research",
        created_at: now,
        updated_at: now,
      }],
    }),
  );
  await page.route(`${backendOrigin}/api/v1/system/unlock/status`, (route) =>
    route.fulfill({
      json: {
        state: "ready",
        vault_id: "vault-profile",
        unlock_mode: "convenience",
        pin_enabled: false,
        message: "Ready",
        verification_error: "",
        updated_at: now,
        ready: true,
        secured_vault_count: 0,
        secured_vault_ids: [],
        has_vendor_recovery: false,
      },
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
        succeeded: 4,
        partial_success: 0,
        failed: 0,
        cancelled: 0,
        manual_review: 0,
        running_jobs: [],
        latest: [],
      },
    }),
  );
  await page.route(`${backendOrigin}/api/v1/models/runtime`, (route) =>
    route.fulfill({ json: { state: "ready", available: true, detail: "Local chat is ready." } }),
  );

  await page.goto("/home");
  await expect(page.locator(".vault-mobile-status").getByText("Ready", { exact: true })).toBeVisible({
    timeout: 15_000,
  });
  await page.goto("/settings?section=profile");
  await expect(page).toHaveTitle("Settings");
  await expect(page.getByText("Library: Research Library", { exact: true })).toBeVisible();
  await expect(page.getByRole("paragraph").filter({ hasText: "T:/research" })).toBeVisible();

  await page.keyboard.press("Control+K");
  const healthCommand = page.getByRole("option", { name: /Health status/ });
  await expect(healthCommand).toBeVisible();
  await healthCommand.click();

  const panel = page.getByRole("dialog", { name: "Health status" });
  await expect(panel).toBeVisible();
  await expect(panel.getByText("Research Library", { exact: true })).toBeVisible();
  await expect(panel.getByText(/Latest check:/)).not.toContainText("not run yet");
  const initial = await panel.boundingBox();
  const handle = panel.getByRole("heading", { name: "Health status" });
  const handleBox = await handle.boundingBox();
  expect(initial).not.toBeNull();
  expect(handleBox).not.toBeNull();
  if (initial && handleBox) {
    await page.mouse.move(handleBox.x + 20, handleBox.y + 10);
    await page.mouse.down();
    await page.mouse.move(handleBox.x - 70, handleBox.y - 60, { steps: 5 });
    await page.mouse.up();
    const moved = await panel.boundingBox();
    expect(moved?.x).toBeLessThan(initial.x);
    expect(moved?.y).toBeLessThan(initial.y);
  }
  expect(consoleProblems).toEqual([]);

  if (process.env.CML_QA_HEALTH_SCREENSHOT) {
    await page.screenshot({ path: process.env.CML_QA_HEALTH_SCREENSHOT, fullPage: false });
  }
});

test("assistant messages render structured Markdown without visible delimiters", async ({ page }) => {
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
            content: "### Database fundamentals\n\n- *External level*: users' views\n  - **Conceptual level**: shared schema\n\nThis is a **bold assessment** with safe <script>text</script>.",
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
  await expect(page.getByRole("heading", { name: "Database fundamentals" })).toBeVisible();
  await expect(page.locator("em", { hasText: "External level" })).toBeVisible();
  await expect(page.locator("li", { hasText: "Conceptual level" })).toBeVisible();
  const strong = page.locator("strong", { hasText: "bold assessment" });
  await expect(strong).toBeVisible();
  const answer = page.locator("p").filter({ hasText: "This is a bold assessment" });
  await expect(answer).toContainText("This is a bold assessment with safe <script>text</script>.");
  await expect(answer).not.toContainText("**");
  await expect(page.getByText("### Database fundamentals", { exact: true })).toHaveCount(0);
  await expect(page.getByText("*External level*", { exact: true })).toHaveCount(0);
  await expect(answer.locator("script")).toHaveCount(0);
  expect(consoleProblems).toEqual([]);

  if (process.env.CML_QA_SCREENSHOT) {
    await page.screenshot({ path: process.env.CML_QA_SCREENSHOT, fullPage: false });
  }
});

test("Sources preserves nested folders inside a grouped folder import", async ({ page }) => {
  const consoleProblems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      consoleProblems.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => consoleProblems.push(`pageerror: ${error.message}`));

  const now = "2026-07-31T10:00:00Z";
  const rootPath = "T:\\folder-x";
  const source = (id: string, title: string, relativePath: string) => ({
    id,
    vault_id: "vault-folders",
    cluster_id: null,
    title,
    source_type: "file",
    state: "indexed",
    ingestion_stage: "ready",
    ingestion_generation: 1,
    ingestion_error_code: "",
    ingestion_status_detail: "",
    ingestion_updated_at: now,
    original_path: `${rootPath}\\${relativePath.replaceAll("/", "\\")}`,
    import_root_path: rootPath,
    import_relative_path: relativePath,
    url: null,
    raw_text: "",
    extracted_text: "",
    summary: `${title} summary`,
    tags: [],
    metadata_quality: "semantic",
    semantic_metadata_version: 1,
    semantic_metadata_updated_at: now,
    cover_image_url: null,
    created_at: now,
    updated_at: now,
  });

  await page.route(`${backendOrigin}/api/v1/vaults`, (route) =>
    route.fulfill({
      json: [{
        id: "vault-folders",
        name: "Folder Library",
        path: "T:\\folder-library",
        created_at: now,
        updated_at: now,
      }],
    }),
  );
  await page.route(
    (url) => url.origin === backendOrigin && url.pathname === "/api/v1/sources/folders/tree",
    (route) =>
      route.fulfill({
        json: {
          root_path: rootPath,
          total_files: 20,
          items: [
            { path: "a", parent_path: "", name: "a", depth: 0, source_count: 8, direct_source_count: 5 },
            { path: "b", parent_path: "", name: "b", depth: 0, source_count: 6, direct_source_count: 6 },
            { path: "c", parent_path: "", name: "c", depth: 0, source_count: 2, direct_source_count: 2 },
            { path: "a/deep", parent_path: "a", name: "deep", depth: 1, source_count: 3, direct_source_count: 3 },
          ],
        },
      }),
  );
  await page.route(
    (url) => url.origin === backendOrigin && url.pathname === "/api/v1/sources/folders",
    (route) =>
      route.fulfill({
        json: {
          items: [{ root_path: rootPath, name: "folder-x", source_count: 20, updated_at: now }],
          total: 1,
          limit: 100,
          offset: 0,
          has_more: false,
        },
      }),
  );
  await page.route(
    (url) => url.origin === backendOrigin && url.pathname === "/api/v1/sources/page",
    (route) => {
      const url = new URL(route.request().url());
      const inFolder = url.searchParams.get("import_root_path") === rootPath;
      const prefix = url.searchParams.get("import_relative_prefix");
      const items = !inFolder
        ? []
        : prefix === "a"
          ? [source("source-a", "a-note.txt", "a/a-note.txt")]
          : [source("source-root", "root-note.txt", "root-note.txt")];
      return route.fulfill({ json: { items, next_cursor: null, has_more: false, total: items.length } });
    },
  );
  await page.route(
    (url) => url.origin === backendOrigin && url.pathname === "/api/v1/sources/count",
    (route) => {
      const url = new URL(route.request().url());
      const total = url.searchParams.has("import_root_path") ? 1 : 0;
      return route.fulfill({ json: { total } });
    },
  );

  await page.goto("/sources");
  await expect(page).toHaveTitle("Sources");
  await page.getByRole("row", { name: "Open folder-x folder" }).click();
  await expect(page.getByRole("heading", { name: "folder-x" })).toBeVisible();
  await expect(page.getByRole("row", { name: "Open a folder" })).toBeVisible();
  await expect(page.getByRole("row", { name: "Open b folder" })).toBeVisible();
  await expect(page.getByRole("row", { name: "Open c folder" })).toBeVisible();
  await expect(page.getByText("root-note.txt", { exact: true })).toBeVisible();

  await page.getByRole("row", { name: "Open a folder" }).click();
  await expect(page.getByRole("heading", { name: "a" })).toBeVisible();
  await expect(page.getByRole("row", { name: "Open deep folder" })).toBeVisible();
  await expect(page.getByText("a-note.txt", { exact: true })).toBeVisible();
  expect(consoleProblems).toEqual([]);

  if (process.env.CML_QA_FOLDERS_SCREENSHOT) {
    await page.screenshot({ path: process.env.CML_QA_FOLDERS_SCREENSHOT, fullPage: false });
  }
});

test("Bridge presents connected AI write-back as a guided workflow", async ({ page }) => {
  const consoleProblems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      consoleProblems.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => consoleProblems.push(`pageerror: ${error.message}`));

  const now = "2026-07-31T10:00:00Z";
  await page.route(`${backendOrigin}/api/v1/bridge/status`, (route) =>
    route.fulfill({
      json: {
        schema_version: 1,
        enabled: true,
        mcp: "available",
        http_api: "available",
        cli: "available",
        allowed_vault_ids: ["vault-bridge"],
        allowed_cluster_ids: [],
        allow_raw_snippets: false,
        allow_cluster_profile: true,
        bridge_token: "",
        approval_requests_pending: 0,
        last_refreshed_at: now,
      },
    }),
  );
  await page.route(`${backendOrigin}/api/v1/vaults`, (route) =>
    route.fulfill({
      json: [{
        id: "vault-bridge",
        name: "Connected Library",
        path: "T:\\connected-library",
        created_at: now,
        updated_at: now,
      }],
    }),
  );

  await page.goto("/bridge");
  await expect(page).toHaveTitle("Bridge");
  await expect(page.getByRole("heading", { name: "Connect AI tools" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Connect", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Access", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Review", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Activity", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Manual tools", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Save useful answers without copying" })).toBeVisible();
  await expect(page.getByText(/Save this answer to Vault/)).toBeVisible();
  await expect(page.getByText("Connections allowed", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Manual tools", exact: true }).click();
  await expect(page.getByText(/fallback for tools that cannot call Vault directly/i)).toBeVisible();
  await expect(page.getByText("Set up an AI connection", { exact: true })).not.toBeVisible();
  expect(consoleProblems).toEqual([]);

  if (process.env.CML_QA_BRIDGE_SCREENSHOT) {
    await page.screenshot({ path: process.env.CML_QA_BRIDGE_SCREENSHOT, fullPage: false });
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
  await page.route(`${backendOrigin}/api/v1/projects/${project.id}/graph/view*`, (route) =>
    route.fulfill({
      json: {
        version: 1,
        project_id: project.id,
        snapshot_id: "snapshot-active",
        indexed_commit: project.indexed_commit,
        mode: "graph",
        direction: "balanced",
        query: "Open the project map.",
        root: "",
        nodes: [],
        edges: [],
        truncated: false,
        limits: { max_nodes: 90, max_depth: 2 },
        warnings: [],
        insights: {
          summary: "No mapped nodes.",
          key_areas: [],
          flows: [],
          node_kinds: {},
          relationship_types: {},
          component_count: 0,
        },
      },
    }),
  );

  await page.goto(`/projects/${project.id}`);
  await expect(page).toHaveTitle("Project");
  await expect(page.getByRole("heading", { name: project.name })).toBeVisible();
  await expect(page.getByText(project.brief)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Ask about this project" })).toBeVisible();
  await expect(page.getByLabel("Ask about this project")).toBeVisible();
  const suggestedQuestions = page
    .getByRole("navigation", { name: "Suggested project questions" })
    .getByRole("button");
  await expect(suggestedQuestions.first()).toContainText("Open the project map.");
  await expect(
    page.getByRole("button", { name: /Explain the application flow starting at src\/main\.ts/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /How is the detected package or workspace in Snapshot semantics organized/ }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Odin freshness" })).toBeVisible();
  await expect(
    page.getByText(/The active Odin snapshot matches the current eligible files\./).first(),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Git repository status" })).toBeVisible();
  await expect(page.getByText(/Git reports 2 changed working-tree paths/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Sync changes" })).toHaveCount(0);
  if (process.env.CML_QA_SCREENSHOT) {
    await suggestedQuestions.first().scrollIntoViewIfNeeded();
    await page.screenshot({ path: process.env.CML_QA_SCREENSHOT, fullPage: false });
  }
  await suggestedQuestions.first().click();
  await expect(page).toHaveURL(/\/project-map\?.*project=project-rendered/);
  await page.goBack();
  await page.getByRole("button", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Project settings" })).toBeVisible();
  expect(consoleProblems).toEqual([]);
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

test("completed import summary disappears after ten seconds", async ({ page }) => {
  const pageErrors: string[] = [];
  const consoleErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.stack || error.message));
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  const now = "2026-07-31T08:00:00Z";
  const job = {
    id: "rendered-import-complete",
    job_type: "source_import_batch",
    status: "partial_success",
    payload: "{}",
    result_json: JSON.stringify({
      total_files: 18,
      completed_files: 18,
      imported_files: 10,
      updated_files: 0,
      failed_files: 8,
      failures: [],
      current_file: "",
      truncated_at: null,
    }),
    dedupe_key: null,
    attempts: 1,
    max_attempts: 3,
    last_error: "",
    created_at: now,
    updated_at: now,
  };
  await page.route(`${backendOrigin}/api/v1/vaults`, (route) =>
    route.fulfill({
      json: [{
        id: "vault-import",
        name: "Import vault",
        path: "T:\\import",
        created_at: now,
        updated_at: now,
      }],
    }),
  );
  await page.route(`${backendOrigin}/api/v1/sources/import-jobs/active*`, (route) =>
    route.fulfill({ json: job }),
  );

  const terminalJobLoaded = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/v1/sources/import-jobs/active",
  );
  await page.goto("/sources");
  await terminalJobLoaded;
  expect(pageErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
  const summary = page.getByText("Import finished: 10 imported, 0 updated, 8 failed.");
  await expect(summary).toBeVisible();
  await expect(summary).toHaveCount(0, { timeout: 11_500 });
});

test("new cluster asks for its name after the action is chosen", async ({ page }) => {
  const now = "2026-07-31T08:00:00Z";
  const clusters: Array<Record<string, unknown>> = [];
  await page.route(`${backendOrigin}/api/v1/vaults`, (route) =>
    route.fulfill({
      json: [{
        id: "vault-clusters",
        name: "Cluster vault",
        path: "T:\\clusters",
        created_at: now,
        updated_at: now,
      }],
    }),
  );
  await page.route(`${backendOrigin}/api/v1/clusters/page*`, (route) =>
    route.fulfill({ json: { items: clusters, next_cursor: null, has_more: false } }),
  );
  await page.route(`${backendOrigin}/api/v1/clusters/suggestions*`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`${backendOrigin}/api/v1/sources/counts-by-cluster*`, (route) =>
    route.fulfill({ json: { items: [] } }),
  );
  await page.route(`${backendOrigin}/api/v1/projects/cluster-membership-summary*`, (route) =>
    route.fulfill({ json: { cluster_ids: [] } }),
  );
  await page.route(`${backendOrigin}/api/v1/sources/latest-by-cluster*`, (route) =>
    route.fulfill({ json: { items: [] } }),
  );
  await page.route(`${backendOrigin}/api/v1/clusters`, async (route) => {
    const payload = route.request().postDataJSON() as { name: string; vault_id: string; color: string };
    const cluster = {
      id: "cluster-created",
      vault_id: payload.vault_id,
      name: payload.name,
      description: "",
      color: payload.color,
      index_status: "empty",
      profile_status: "needs_update",
      cluster_summary: "",
      cluster_glossary: "[]",
      created_at: now,
      updated_at: now,
    };
    clusters.push(cluster);
    return route.fulfill({ json: cluster });
  });

  const clustersLoaded = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/v1/clusters/page",
  );
  await page.goto("/clusters");
  await clustersLoaded;
  await expect(page.getByRole("heading", { name: "Clusters" })).toBeVisible();
  await expect(page.getByLabel("Cluster name")).toHaveCount(0);
  await page.getByRole("button", { name: "New cluster" }).click();
  await expect(page.getByRole("heading", { name: "Create a cluster" })).toBeVisible();
  const name = page.getByLabel("Cluster name");
  await expect(name).toBeFocused();
  if (process.env.CML_QA_CLUSTER_SCREENSHOT) {
    await page.screenshot({ path: process.env.CML_QA_CLUSTER_SCREENSHOT, fullPage: false });
  }
  await name.fill("Research notes");
  await page.getByRole("button", { name: "Create cluster" }).click();
  await expect(page.getByRole("heading", { name: "Create a cluster" })).toHaveCount(0);
  await expect(page.getByText("Research notes", { exact: true })).toBeVisible();
});

test("settings explains passphrase requirements before protected setup", async ({ page }) => {
  const now = "2026-07-31T08:00:00Z";
  let initializeRequests = 0;
  await page.route(`${backendOrigin}/api/v1/vaults`, (route) =>
    route.fulfill({
      json: [{
        id: "vault-unprotected",
        name: "Unprotected vault",
        path: "T:\\unprotected",
        created_at: now,
        updated_at: now,
      }],
    }),
  );
  await page.route(`${backendOrigin}/api/v1/system/unlock/status`, (route) =>
    route.fulfill({
      json: {
        state: "ready",
        ready: true,
        secured_vault_count: 0,
        secured_vault_ids: [],
        vault_id: "vault-unprotected",
        unlock_mode: "strict",
        pin_enabled: false,
        message: "Library ready.",
        verification_error: "",
        updated_at: now,
        has_vendor_recovery: false,
      },
    }),
  );
  await page.route(`${backendOrigin}/api/v1/system/unlock/initialize`, (route) => {
    initializeRequests += 1;
    return route.fulfill({ status: 500, json: { detail: "Should not be called." } });
  });

  const unlockLoaded = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/v1/system/unlock/status",
  );
  const vaultLoaded = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/v1/vaults",
  );
  await page.goto("/settings?section=library");
  await Promise.all([unlockLoaded, vaultLoaded]);
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  await expect(
    page.getByText("Use at least 12 characters. Vault cannot recover it for you."),
  ).toBeVisible();
  const passphrase = page.getByLabel("Create library passphrase");
  await passphrase.fill("too short");
  await expect(passphrase).toHaveValue("too short");
  await expect(page.getByRole("button", { name: "Set passphrase" })).toBeDisabled();
  if (process.env.CML_QA_PASSPHRASE_SCREENSHOT) {
    await page
      .getByText("Use at least 12 characters. Vault cannot recover it for you.")
      .scrollIntoViewIfNeeded();
    await page.screenshot({ path: process.env.CML_QA_PASSPHRASE_SCREENSHOT, fullPage: false });
  }
  expect(initializeRequests).toBe(0);
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
