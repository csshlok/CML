import { expect, test, type Page } from "@playwright/test";

const backendOrigin = "http://127.0.0.1:7343";

async function installDesktopBridge(page: Page) {
  await page.addInitScript(
    ({ origin }) => {
      const state = { maximized: false, fullScreen: false };
      let vaultDeleted = false;
      Object.defineProperty(window, "cmlDesktop", {
        configurable: true,
        value: {
          getBackendUrl: async () => origin,
          getBackendToken: async () => "rendered-shell-test-token",
          getSetupState: async () =>
            vaultDeleted
              ? null
              : {
                  phase: "complete",
                  profile: { display_name: "Shlok", avatar_path: "" },
                },
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
          finalizeActiveVaultDeletion: async () => {
            vaultDeleted = true;
            (window as typeof window & { __vaultDeletionFinalized?: boolean })
              .__vaultDeletionFinalized = true;
            return { deleted: true, path: "T:\\test" };
          },
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
    },
    { origin: backendOrigin },
  );
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
  await page.route(`${backendOrigin}/health`, (route) => route.fulfill({ json: { status: "ok" } }));
  await page.route(`${backendOrigin}/api/v1/system/backend-identity`, (route) =>
    route.fulfill({ json: { service: "cml-backend", api_prefix: "/api/v1" } }),
  );
}

test.beforeEach(async ({ page }) => {
  await installDesktopBridge(page);
  await installBaseRoutes(page);
});

test("capture current Vault surfaces for the in-app help gallery", async ({ page }) => {
  test.setTimeout(90_000);
  const outputDirectory = process.env.CML_CAPTURE_HELP_DIR;
  test.skip(!outputDirectory, "Set CML_CAPTURE_HELP_DIR to regenerate help screenshots.");
  await page.setViewportSize({ width: 1280, height: 800 });
  const now = "2026-08-10T10:00:00Z";
  const vault = { id: "vault-help", name: "Research vault", path: "T:\\Research", created_at: now, updated_at: now };
  const clusters = [
    { id: "cluster-browser", vault_id: vault.id, name: "Browser Start Issues", description: "Startup diagnostics and fixes.", color: "terracotta", index_status: "ready", profile_status: "ready", cluster_summary: "Browser startup logs and recovery notes.", cluster_glossary: "[]", created_at: now, updated_at: now },
    { id: "cluster-research", vault_id: vault.id, name: "Research notes", description: "Product and market research.", color: "sage", index_status: "ready", profile_status: "ready", cluster_summary: "Research reports and interview notes.", cluster_glossary: "[]", created_at: now, updated_at: now },
  ];
  const source = (id: string, title: string, clusterId: string | null, summary: string) => ({
    id, vault_id: vault.id, cluster_id: clusterId, title, source_type: "file", state: "indexed",
    ingestion_stage: "ready", ingestion_generation: 1, ingestion_error_code: null,
    ingestion_status_detail: "Ready", ingestion_updated_at: now, original_path: `T:\\Research\\${title}`,
    import_root_path: "T:\\Research", import_relative_path: title, url: null, raw_text: "",
    extracted_text: summary, summary, tags: ["research"], metadata_quality: "semantic",
    semantic_metadata_version: 2, semantic_metadata_updated_at: now, cover_image_url: null,
    created_at: now, updated_at: now,
  });
  const sources = [
    source("source-log", "browser-start.log", "cluster-browser", "Browser startup failure log and recovery trace."),
    source("source-notes", "startup-notes.md", "cluster-browser", "Notes about renderer startup and authentication recovery."),
    source("source-report", "market-research.pdf", "cluster-research", "Customer interviews and market research findings."),
    source("source-unclustered", "meeting-notes.md", null, "Planning notes waiting for organization."),
  ];
  const makeJob = (id: string, jobType: string, status: string, detail: string) => ({
    id, job_type: jobType, status, payload: "{}", result_json: null, dedupe_key: null,
    priority: "normal", write_scope: "source", scope_id: vault.id, resource_cost: "normal",
    user_visible: 1, cancellable: 1, preemptable: 1, timeout_seconds: 600,
    started_at: status === "running" ? now : null, completed_at: null, elapsed_seconds: 18,
    estimated_remaining_seconds: 42, status_detail: detail, cancellation_requested: 0,
    cancellation_requested_at: null, attempts: 1, max_attempts: 3, last_error: "",
    error_code: "", diagnostic_id: "", created_at: now, updated_at: now,
  });
  const runningJob = makeJob("job-import", "source_import_batch", "running", "Indexed 7 of 10 files.");
  const queuedJob = makeJob("job-organize", "source_cluster_reconciliation", "queued", "Waiting to organize analyzed sources.");

  await page.route(`${backendOrigin}/api/v1/vaults`, (route) => route.fulfill({ json: [vault] }));
  await page.route(`${backendOrigin}/api/v1/sources/page*`, (route) => route.fulfill({ json: { items: sources, next_cursor: null, has_more: false, total: sources.length } }));
  await page.route(`${backendOrigin}/api/v1/sources/count*`, (route) => route.fulfill({ json: { total: sources.length } }));
  await page.route(`${backendOrigin}/api/v1/clusters/page*`, (route) => route.fulfill({ json: { items: clusters, next_cursor: null, has_more: false } }));
  await page.route(`${backendOrigin}/api/v1/clusters/suggestions*`, (route) => route.fulfill({ json: [{ source_id: "source-report", source_title: "market-research.pdf", current_cluster_id: "cluster-research", suggested_cluster_id: "cluster-browser", suggested_cluster_name: "Browser Start Issues", confidence: 0.82, reason: "Source text is closer to this cluster's indexed context." }] }));
  await page.route(`${backendOrigin}/api/v1/sources/counts-by-cluster*`, (route) => route.fulfill({ json: { items: [{ cluster_id: "cluster-browser", state: "indexed", total: 2 }, { cluster_id: "cluster-research", state: "indexed", total: 1 }, { cluster_id: null, state: "indexed", total: 1 }] } }));
  await page.route(`${backendOrigin}/api/v1/sources/latest-by-cluster*`, (route) => route.fulfill({ json: { items: [{ cluster_id: "cluster-browser", state: "indexed", updated_at: now }, { cluster_id: "cluster-research", state: "indexed", updated_at: now }] } }));
  await page.route(`${backendOrigin}/api/v1/projects/cluster-membership-summary*`, (route) => route.fulfill({ json: { cluster_ids: [] } }));
  await page.route(`${backendOrigin}/api/v1/jobs/status`, (route) => route.fulfill({ json: { queued: 1, paused: 0, blocked_by_dependency: 0, blocked_setup_required: 0, blocked_local_model: 0, deferred: 0, running: 1, succeeded: 6, partial_success: 0, failed: 0, cancelled: 0, manual_review: 0, running_jobs: [runningJob], latest: [runningJob, queuedJob] } }));
  await page.route((url) => url.origin === backendOrigin && url.pathname === "/api/v1/jobs", (route) => route.fulfill({ json: { items: [runningJob, queuedJob], next_cursor: null, has_more: false } }));
  await page.route(`${backendOrigin}/api/v1/projects/project-run-summary*`, (route) => route.fulfill({ json: { items: [] } }));
  await page.route(`${backendOrigin}/api/v1/map/overview*`, (route) => route.fulfill({ json: { vault_id: vault.id, nodes: clusters.map((cluster, index) => ({ id: cluster.id, kind: "cluster", label: cluster.name, summary: cluster.cluster_summary, color: cluster.color, state: "ready", source_count: index === 0 ? 2 : 1, fact_count: 0, updated_at: now })), edges: [{ id: "similarity:browser:research", source: "cluster-browser", target: "cluster-research", kind: "similarity", label: "64% similar", direction: "undirected", temporal_state: "current", provenance_ids: ["source-log", "source-report"], updated_at: now, relationship_basis: "semantic_similarity", similarity_score: 0.64, shared_terms: ["research", "recovery"], evidence_labels: ["Shared topics: research, recovery"] }], total: 2, cluster_total: 2, unclustered_count: 1, limit: 160, offset: 0, truncated: false, connection_mode: "similar", relationship_policy: "evidence_and_similarity" } }));

  const capture = async (
    name: string,
    route: string,
    target: ReturnType<typeof page.locator>,
    populated?: ReturnType<typeof page.locator>,
  ) => {
    await page.goto(route);
    await expect(page.locator(".vault-shell")).toBeVisible();
    if (populated) await expect(populated).toBeVisible();
    await expect(target).toBeVisible();
    await target.scrollIntoViewIfNeeded();
    await target.evaluate((element) => element.setAttribute("data-help-capture", ""));
    await page.addStyleTag({ content: `[data-help-capture] { outline: 3px solid #82745f !important; outline-offset: 4px !important; box-shadow: 0 0 0 7px rgb(130 116 95 / 18%) !important; position: relative !important; z-index: 20 !important; }` });
    await page.waitForTimeout(150);
    await page.screenshot({ path: `${outputDirectory}/${name}.png`, fullPage: false });
  };

  await capture("sources-add-files", "/sources", page.getByRole("button", { name: "Add files" }), page.getByText("browser-start.log", { exact: true }));
  await capture("sources-ready", "/sources", page.getByRole("row", { name: /browser-start\.log/ }));
  await capture("clusters-refresh", "/clusters", page.getByRole("button", { name: "Refresh organization" }), page.getByText("Browser Start Issues", { exact: true }));
  await capture("clusters-moves", "/clusters", page.getByRole("button", { name: "Check suggestions" }), page.getByText("Browser Start Issues", { exact: true }));
  await capture("search-query", "/search", page.getByPlaceholder("Search sources, tags, summaries..."));
  await capture("chat-scope", "/chat", page.getByRole("combobox"));
  await capture("chat-send", "/chat", page.getByRole("button", { name: "Send" }));
  await capture("project-add", "/projects", page.getByRole("button", { name: "Add project folder" }).first());
  await capture("map-connections", "/map", page.getByRole("button", { name: "Connections" }));
  await capture("tasks-active", "/tasks", page.getByRole("button", { name: /Active 2/ }));
  await capture("models-manage", "/settings?section=models", page.getByRole("button", { name: "Manage models" }));
  await capture("storage-library", "/settings?section=library", page.getByRole("button", { name: "Library & security" }));
  await capture("connections-install", "/settings?section=connections", page.getByRole("button", { name: "Install Odin" }));
  await capture("settings-health", "/settings?section=health", page.getByRole("button", { name: "System health" }));
});

test("Odin pairing is actionable outside Code Connections", async ({ page }) => {
  test.setTimeout(60_000);
  const consoleProblems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      consoleProblems.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => consoleProblems.push(`pageerror: ${error.message}`));

  const vault = {
    id: "vault-1",
    name: "My Library",
    path: "T:\\test",
    created_at: "2026-08-01T09:00:00Z",
    updated_at: "2026-08-01T09:00:00Z",
  };
  let pending = [
    {
      id: "pairing-1",
      requester_name: "PowerShell on this computer",
      requested_scopes: ["project_read", "project_write"],
      executable_fingerprint: "0123456789abcdef0123456789abcdef",
      expires_at: "2026-08-01T10:00:00Z",
    },
  ];
  let approved = false;
  let cancelled = false;

  await page.route(`${backendOrigin}/api/v1/system/unlock/status`, (route) =>
    route.fulfill({ json: { ready: true, state: "ready", secured_vault_count: 0 } }),
  );
  await page.route(`${backendOrigin}/api/v1/vaults`, (route) => route.fulfill({ json: [vault] }));
  await page.route(
    `${backendOrigin}/api/v1/cli-auth/pairing-challenges?status=pending&limit=20`,
    (route) => route.fulfill({ json: pending }),
  );
  await page.route(
    `${backendOrigin}/api/v1/cli-auth/pairing-challenges/pairing-1/approve`,
    (route) => {
      approved = true;
      pending = [];
      return route.fulfill({
        json: { id: "client-1", display_name: "PowerShell on this computer" },
      });
    },
  );
  await page.route(
    `${backendOrigin}/api/v1/cli-auth/pairing-challenges/pairing-1/deny`,
    (route) => {
      cancelled = true;
      pending = [];
      return route.fulfill({ json: { id: "pairing-1", status: "denied" } });
    },
  );

  await page.goto(`/home?backendUrl=${encodeURIComponent(backendOrigin)}`);
  const pairingNotice = page.getByRole("status").filter({ hasText: "Odin is requesting access" });
  await expect(pairingNotice).toBeVisible({ timeout: 15_000 });
  await expect(pairingNotice).toContainText("PowerShell on this computer");
  await expect(pairingNotice).toContainText("project read, project write");
  await expect(pairingNotice.getByRole("button", { name: "Cancel request" })).toBeVisible();
  if (process.env.CML_QA_ODIN_PAIRING_SCREENSHOT) {
    await page.screenshot({ path: process.env.CML_QA_ODIN_PAIRING_SCREENSHOT, fullPage: false });
  }
  await pairingNotice.getByRole("button", { name: "Approve" }).click();
  await expect.poll(() => approved).toBe(true);
  expect(cancelled).toBe(false);
  await expect(page.getByText("Odin access approved")).toBeVisible();

  await page.goto("/settings?section=connections");
  await expect(page.getByRole("heading", { name: "Install Odin" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Odin code projects" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Odin command-line access" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Odin command reference" })).toBeVisible();
  const guideButton = page.getByRole("link", { name: "How to install and connect" });
  await guideButton.click();
  expect(consoleProblems).toEqual([]);
  await expect(guideButton).toHaveAttribute("aria-expanded", "true");
  const guide = page.getByRole("region", { name: "Install and connect Odin" });
  await expect(guide).toBeVisible();
  await expect(guide.getByText("odin auth pair", { exact: true })).toBeVisible();
  await expect(
    guide.getByText('odin project add . --name "My Project"', { exact: true }),
  ).toBeVisible();
  expect(consoleProblems).toEqual([]);
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
  await expect(page.getByLabel("Filter Home by source type")).toHaveCount(0);
  await expect(page.getByLabel("Sort Home")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Customize Home" })).toBeVisible();

  const visibleSectionText = await page
    .locator("main section")
    .evaluateAll((sections) =>
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

test("Settings opens the searchable visual Help and FAQ workspace", async ({ page }) => {
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"], {
    origin: "http://127.0.0.1:5173",
  });
  const consoleProblems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      consoleProblems.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => consoleProblems.push(`pageerror: ${error.message}`));

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/settings?section=profile");
  await expect(page).toHaveTitle("Settings");
  const helpLink = page.getByRole("link", { name: "Open Help & FAQ" });
  await expect(helpLink).toBeVisible();
  await helpLink.click();

  await expect(page).toHaveURL(/\/help/);
  await expect(page).toHaveTitle("Help & FAQ");
  await expect(page.getByRole("heading", { name: "Help & FAQ" })).toBeVisible();
  await expect(page.getByText("74 practical answers across 13 categories", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "What should I do in my first ten minutes?" }),
  ).toBeVisible();
  await expect(page.getByText("See it in Vault", { exact: true })).toBeVisible();
  await expect(page.getByText("1 of 5", { exact: true })).toBeVisible();
  await expect(page.getByText("Add the first files", { exact: true })).toBeVisible();
  const search = page.getByLabel("Search help");
  await expect.poll(() =>
    search.evaluate((element) => Object.keys(element).some((key) => key.startsWith("__reactProps"))),
  ).toBe(true);
  await page.getByRole("button", { name: "Next walkthrough image" }).click();
  await expect(page.getByText("Confirm indexing", { exact: true })).toBeVisible();
  const walkthroughImage = page
    .getByRole("figure", { name: "Start in Sources walkthrough" })
    .getByRole("img");
  await expect.poll(() => walkthroughImage.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
  const walkthroughBox = await walkthroughImage.boundingBox();
  expect(walkthroughBox).not.toBeNull();
  await page.mouse.move(
    walkthroughBox!.x + walkthroughBox!.width * 0.75,
    walkthroughBox!.y + walkthroughBox!.height / 2,
  );
  await page.mouse.down();
  await page.mouse.move(
    walkthroughBox!.x + walkthroughBox!.width * 0.25,
    walkthroughBox!.y + walkthroughBox!.height / 2,
  );
  await page.mouse.up();
  await expect(page.getByText("Look for moves between clusters", { exact: true })).toBeVisible();
  if (process.env.CML_QA_HELP_GALLERY_SCREENSHOT) {
    await page.screenshot({ path: process.env.CML_QA_HELP_GALLERY_SCREENSHOT, fullPage: false });
  }
  expect(consoleProblems).toEqual([]);

  await page.getByRole("button", { name: /Models & OCR/ }).click();
  await expect(
    page.getByRole("heading", { name: "Why does Vault need chat, embedding, and OCR models?" }),
  ).toBeVisible();
  await expect(
    page
      .getByLabel("Help categories")
      .getByRole("button", { name: "What should I do when Chat says the model is unavailable?" }),
  ).toBeVisible();
  if (process.env.CML_QA_HELP_CATEGORIES_SCREENSHOT) {
    await page.screenshot({
      path: process.env.CML_QA_HELP_CATEGORIES_SCREENSHOT,
      fullPage: false,
    });
  }
  await search.click();
  await search.pressSequentially("TurboVec");
  await expect(page.getByText("1 result", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /When should TurboVec activate/ }).click();
  await expect(page).toHaveURL(/article=odin-turbovec/);
  await expect(page.getByRole("heading", { name: "When should TurboVec activate?" })).toBeVisible();
  await expect(page.getByText("odin doctor", { exact: true })).toBeVisible();
  await expect(page.locator("summary").filter({ hasText: "What Vault does next" })).toBeVisible();
  await page.getByRole("button", { name: "Copy terminal command" }).first().click();
  await expect(page.getByRole("button", { name: "Copy terminal command" }).first()).toContainText("Copied");

  if (process.env.CML_QA_HELP_SCREENSHOT) {
    await page.screenshot({ path: process.env.CML_QA_HELP_SCREENSHOT, fullPage: false });
  }

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/help?article=map-no-connections");
  await expect(page.getByLabel("Choose a help article")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Why does the map show no connections?" })).toBeVisible();
  await expect.poll(() =>
    page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  ).toBe(true);
  expect(consoleProblems).toEqual([]);

  if (process.env.CML_QA_HELP_MOBILE_SCREENSHOT) {
    await page.screenshot({ path: process.env.CML_QA_HELP_MOBILE_SCREENSHOT, fullPage: false });
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
  await expect(page.getByRole("button", { name: /Active 2/ })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
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
      json: [
        {
          id: "vault-timeline",
          name: "Timeline vault",
          path: "T:\\timeline",
          created_at: "2026-07-31T08:00:00Z",
          updated_at: "2026-07-31T08:00:00Z",
        },
      ],
    }),
  );
  await page.route(`${backendOrigin}/api/v1/activity*`, (route) => {
    activityRequests += 1;
    return route.fulfill({
      json: {
        items: [
          {
            id: `activity-${activityRequests}`,
            kind: "source",
            time: "2026-07-31T08:30:00Z",
            title: `Timeline activity ${activityRequests}`,
            detail: `Refresh response ${activityRequests}`,
            href: "/sources",
          },
        ],
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

test("Profile shows its library and the Health command opens a draggable latest check", async ({
  page,
}) => {
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
        json: [
          {
            id: "vault-profile",
            name: "Research Library",
            path: "T:\\research",
            created_at: now,
            updated_at: now,
          },
        ],
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
  await expect(
    page.locator(".vault-mobile-status").getByText("Ready", { exact: true }),
  ).toBeVisible({
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

test("assistant messages render structured Markdown without visible delimiters", async ({
  page,
}) => {
  const consoleProblems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      consoleProblems.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => consoleProblems.push(`pageerror: ${error.message}`));
  const sessionId = "chat-markdown";
  const now = "2026-07-30T10:00:00Z";
  const citationSource = {
    id: "source-citation",
    vault_id: "vault-rendered",
    cluster_id: null,
    title: "Database architecture.md",
    source_type: "file",
    state: "indexed",
    ingestion_stage: "ready",
    ingestion_generation: 1,
    ingestion_error_code: null,
    ingestion_status_detail: "Ready",
    ingestion_updated_at: now,
    original_path: "T:\\rendered\\Database architecture.md",
    import_root_path: null,
    import_relative_path: null,
    url: null,
    raw_text: "",
    extracted_text: "Database architecture has external and conceptual levels.",
    summary: "Database architecture reference",
    tags: [],
    metadata_quality: "semantic",
    semantic_metadata_version: 2,
    semantic_metadata_updated_at: now,
    cover_image_url: null,
    created_at: now,
    updated_at: now,
  };
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
      json: [
        {
          id: "vault-rendered",
          name: "Rendered vault",
          path: "T:\\rendered",
          created_at: now,
          updated_at: now,
        },
      ],
    }),
  );
  await page.route(`${backendOrigin}/api/v1/chat/sessions/${sessionId}/metadata`, (route) =>
    route.fulfill({ json: session }),
  );
  await page.route(`${backendOrigin}/api/v1/chat/sessions/${sessionId}/timeline*`, (route) =>
    route.fulfill({
      json: {
        session_id: sessionId,
        items: [
          ...Array.from({ length: 240 }, (_, index) => ({
            message_type: "user_message",
            sort_key: `${now}:message-user-${String(index).padStart(3, "0")}`,
            id: `message-user-${index}`,
            session_id: sessionId,
            role: "user",
            content: `Earlier message ${index}`,
            clusters_used: [],
            citations: [],
            warnings: [],
            useful: null,
            saved: false,
            created_at: now,
            generation_id: null,
            reply_to_message_id: null,
            generation_state: null,
            attachments: [],
          })),
          {
            message_type: "assistant_message",
            sort_key: `${now}:message-assistant`,
            id: "message-assistant",
            session_id: sessionId,
            role: "assistant",
            content:
              "### Database fundamentals\n\n- *External level*: users' views\n  - **Conceptual level**: shared schema\n\nThis is a **bold assessment** with safe <script>text</script>.",
            clusters_used: [],
            citations: [
              {
                source_id: citationSource.id,
                source_title: citationSource.title,
                snippet: "External and conceptual database levels.",
                page_number: 1,
                state: "current",
                relative_path: null,
                line_start: null,
                line_end: null,
                symbol: null,
                project_snapshot_id: null,
                indexed_commit: null,
              },
            ],
            warnings: [],
            useful: null,
            saved: false,
            created_at: now,
            generation_id: "generation-markdown",
            reply_to_message_id: null,
            generation_state: "completed",
            attachments: [],
          },
        ],
        next_cursor: null,
        latest_cursor: `${now}:message-assistant`,
        has_more: false,
      },
    }),
  );
  await page.route(`${backendOrigin}/api/v1/models/runtime`, (route) =>
    route.fulfill({ json: { state: "ready", available: true } }),
  );
  await page.route(
    (url) => url.origin === backendOrigin && url.pathname === "/api/v1/sources/count",
    (route) => route.fulfill({ json: { total: 9 } }),
  );
  await page.route(
    (url) => url.origin === backendOrigin && url.pathname === "/api/v1/sources",
    (route) => route.fulfill({ json: [citationSource] }),
  );
  await page.route(`${backendOrigin}/api/v1/sources/${citationSource.id}`, (route) =>
    route.fulfill({ json: citationSource }),
  );
  await page.route(`${backendOrigin}/api/v1/sources/${citationSource.id}/stats`, (route) =>
    route.fulfill({
      json: { source_id: citationSource.id, page_count: 1, chunk_count: 1, size_bytes: 128, last_error: null },
    }),
  );
  await page.route(
    (url) => url.origin === backendOrigin && url.pathname === "/api/v1/clusters",
    (route) => route.fulfill({ json: [] }),
  );
  let selectedUnclusteredScope = false;
  await page.route(`${backendOrigin}/api/v1/chat/sessions/${sessionId}`, async (route) => {
    if (route.request().method() !== "PATCH") {
      await route.continue();
      return;
    }
    const update = route.request().postDataJSON();
    selectedUnclusteredScope = update.scope_unclustered === true;
    await route.fulfill({ json: { ...session, ...update } });
  });

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
  const virtualizedTranscript = page.locator("[data-message-virtualizer]");
  await expect(virtualizedTranscript).toBeVisible();
  expect(await virtualizedTranscript.locator(":scope > div").count()).toBeLessThan(30);
  await virtualizedTranscript.evaluate((element) => {
    element.parentElement?.parentElement?.scrollTo({ top: 0 });
  });
  await expect(page.getByText("Earlier message 0", { exact: true })).toBeVisible();
  if (process.env.CML_QA_VIRTUALIZED_CHAT_SCREENSHOT) {
    await page.screenshot({
      path: process.env.CML_QA_VIRTUALIZED_CHAT_SCREENSHOT,
      fullPage: false,
    });
  }
  await page.getByRole("button", { name: "Jump to latest" }).click();
  await expect(page.getByRole("heading", { name: "Database fundamentals" })).toBeVisible();
  await page.getByRole("combobox").click();
  await page.getByRole("option", { name: "Unclustered sources (9)" }).click();
  await expect.poll(() => selectedUnclusteredScope).toBe(true);
  await expect(page.getByPlaceholder("Ask unclustered sources...")).toBeVisible();
  await expect(page.getByText(/send \/ unclustered sources \/ vault retrieval/i)).toBeVisible();
  await page.getByRole("button", { name: /Database architecture\.md/ }).click();
  await page.getByRole("button", { name: "View source" }).click();
  await expect(page).toHaveURL(/\/sources\?source=source-citation/);
  await expect(page.getByRole("heading", { name: "Database architecture.md" })).toBeVisible();
  expect(consoleProblems).toEqual([]);

  if (process.env.CML_QA_SCREENSHOT) {
    await page.screenshot({ path: process.env.CML_QA_SCREENSHOT, fullPage: false });
  }
});

test("project chat displays its real retrieval scope and clears it explicitly", async ({ page }) => {
  const consoleProblems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      consoleProblems.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => consoleProblems.push(`pageerror: ${error.message}`));

  const now = "2026-08-10T10:00:00Z";
  const sessionId = "chat-project-scope";
  const projectId = "project-odin-analyzer";
  const clusterId = "cluster-odin-analyzer";
  const session = {
    id: sessionId,
    vault_id: "vault-project-scope",
    title: "Odin Analyzer questions",
    scope_cluster_id: clusterId,
    scope_project_id: projectId,
    scope_unclustered: false,
    saved: false,
    memory_status: "ready",
    memory_updated_at: now,
    active_generation: false,
    created_at: now,
    updated_at: now,
    messages: [],
  };
  const project = {
    id: projectId,
    vault_id: session.vault_id,
    name: "Odin Analyzer",
    root_path: "T:\\odin-analyzer",
    root_fingerprint: "root-fingerprint",
    discovery_scope: "code",
    primary_cluster_id: clusterId,
    repository_kind: "git",
    git_remote_fingerprint: null,
    default_branch: "main",
    indexed_commit: "abcdef1234567890",
    working_tree_dirty: false,
    changed_file_count: 0,
    auto_sync_enabled: true,
    sync_mode: "automatic",
    change_fingerprint: "change-fingerprint",
    last_change_checked_at: now,
    status: "ready",
    structure_status: "ready",
    retrieval_status: "ready",
    interpretation_status: "ready",
    active_snapshot_id: "snapshot-active",
    active_manifest_snapshot_id: "snapshot-active",
    active_structure_snapshot_id: "snapshot-active",
    active_retrieval_snapshot_id: "snapshot-active",
    candidate_snapshot_id: null,
    active_run_id: null,
    active_snapshot: null,
    brief: "Analyzes Odin projects.",
    languages: { TypeScript: 1 },
    workspace_count: 1,
    entrypoints: ["src/index.ts"],
    source_count: 42,
    created_at: now,
    updated_at: now,
  };
  const cluster = {
    id: clusterId,
    vault_id: session.vault_id,
    name: "Odin Analyzer sources",
    description: "Project source cluster.",
    color: "blue",
    index_status: "ready",
    profile_status: "ready",
    cluster_summary: "Project source cluster.",
    cluster_glossary: "[]",
    created_at: now,
    updated_at: now,
  };

  await page.route(`${backendOrigin}/api/v1/vaults`, (route) =>
    route.fulfill({
      json: [
        {
          id: session.vault_id,
          name: "Project scope vault",
          path: "T:\\project-scope",
          created_at: now,
          updated_at: now,
        },
      ],
    }),
  );
  await page.route(`${backendOrigin}/api/v1/chat/sessions/${sessionId}/metadata`, (route) =>
    route.fulfill({ json: session }),
  );
  await page.route(`${backendOrigin}/api/v1/chat/sessions/${sessionId}/timeline*`, (route) =>
    route.fulfill({
      json: {
        session_id: sessionId,
        items: [],
        next_cursor: null,
        latest_cursor: null,
        has_more: false,
      },
    }),
  );
  await page.route(`${backendOrigin}/api/v1/projects/${projectId}`, (route) =>
    route.fulfill({ json: project }),
  );
  await page.route(
    (url) => url.origin === backendOrigin && url.pathname === "/api/v1/clusters",
    (route) => route.fulfill({ json: [cluster] }),
  );
  await page.route(
    (url) => url.origin === backendOrigin && url.pathname === "/api/v1/sources",
    (route) => route.fulfill({ json: [] }),
  );
  await page.route(`${backendOrigin}/api/v1/models/runtime`, (route) =>
    route.fulfill({ json: { state: "ready", available: true } }),
  );
  await page.route(
    (url) => url.origin === backendOrigin && url.pathname === "/api/v1/sources/count",
    (route) => route.fulfill({ json: { total: 0 } }),
  );
  let scopeUpdate: Record<string, unknown> | null = null;
  await page.route(`${backendOrigin}/api/v1/chat/sessions/${sessionId}`, async (route) => {
    if (route.request().method() !== "PATCH") {
      await route.continue();
      return;
    }
    scopeUpdate = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({ json: { ...session, ...scopeUpdate } });
  });

  await page.goto(`/chat/${sessionId}`);
  const newChatButton = page.getByRole("button", { name: "New chat" });
  await expect.poll(
    () => newChatButton.evaluate((element) =>
      Object.keys(element).some((key) => key.startsWith("__reactProps")),
    ),
    { timeout: 20_000 },
  ).toBe(true);
  await expect(page.getByText("Ask Odin Analyzer.", { exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Scoped to the Odin Analyzer Odin project.")).toBeVisible();
  await expect(page.getByRole("combobox")).toContainText("Odin Analyzer");
  await expect(page.getByPlaceholder("Ask Odin Analyzer...")).toBeVisible();

  await page.getByRole("combobox").click();
  await page.getByRole("option", { name: "All vault context" }).click();
  await expect.poll(() => scopeUpdate).toEqual({
    scope_cluster_id: null,
    scope_project_id: null,
    scope_unclustered: false,
  });
  await expect(page.getByText("Ask across your vault.", { exact: true })).toBeVisible();
  await expect(page.getByPlaceholder("Ask your vault...")).toBeVisible();
  expect(consoleProblems).toEqual([]);

  if (process.env.CML_QA_PROJECT_CHAT_SCOPE_SCREENSHOT) {
    await page.screenshot({
      path: process.env.CML_QA_PROJECT_CHAT_SCOPE_SCREENSHOT,
      fullPage: false,
    });
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
      json: [
        {
          id: "vault-folders",
          name: "Folder Library",
          path: "T:\\folder-library",
          created_at: now,
          updated_at: now,
        },
      ],
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
            {
              path: "a",
              parent_path: "",
              name: "a",
              depth: 0,
              source_count: 8,
              direct_source_count: 5,
            },
            {
              path: "b",
              parent_path: "",
              name: "b",
              depth: 0,
              source_count: 6,
              direct_source_count: 6,
            },
            {
              path: "c",
              parent_path: "",
              name: "c",
              depth: 0,
              source_count: 2,
              direct_source_count: 2,
            },
            {
              path: "a/deep",
              parent_path: "a",
              name: "deep",
              depth: 1,
              source_count: 3,
              direct_source_count: 3,
            },
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
      return route.fulfill({
        json: { items, next_cursor: null, has_more: false, total: items.length },
      });
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

test("cluster detail keeps View all sources scoped to that cluster", async ({ page }) => {
  const consoleProblems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      consoleProblems.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => consoleProblems.push(`pageerror: ${error.message}`));

  const now = "2026-08-10T09:00:00Z";
  const vaultId = "vault-browser-issues";
  const clusterId = "cluster-548963ac-f09f-4504-b091-6391f3a7416e";
  const cluster = {
    id: clusterId,
    vault_id: vaultId,
    name: "Browser Start Issues",
    description: "Browser startup diagnostics and fixes.",
    color: "terracotta",
    index_status: "ready",
    profile_status: "ready",
    cluster_summary: "Tracks browser startup failures.",
    cluster_glossary: "[]",
    created_at: now,
    updated_at: now,
  };
  const source = (id: string, title: string, sourceClusterId: string) => ({
    id,
    vault_id: vaultId,
    cluster_id: sourceClusterId,
    title,
    source_type: "file",
    state: "indexed",
    ingestion_stage: "ready",
    ingestion_generation: 1,
    ingestion_error_code: null,
    ingestion_status_detail: "Ready",
    ingestion_updated_at: now,
    original_path: `T:\\test\\${title}`,
    import_root_path: null,
    import_relative_path: null,
    url: null,
    raw_text: "",
    extracted_text: `${title} explains a browser startup issue.`,
    summary: `${title} summary`,
    tags: [],
    metadata_quality: "semantic",
    semantic_metadata_version: 2,
    semantic_metadata_updated_at: now,
    cover_image_url: null,
    created_at: now,
    updated_at: now,
  });
  const members = [
    source("source-browser-log", "browser-start.log", clusterId),
    source("source-browser-notes", "startup-notes.md", clusterId),
  ];
  const unrelated = source("source-other", "unrelated-cluster.md", "cluster-other");
  const clusterChat = {
    id: "chat-browser",
    vault_id: vaultId,
    title: "Browser startup investigation",
    scope_cluster_id: clusterId,
    scope_project_id: null,
    scope_unclustered: false,
    saved: false,
    memory_status: "idle",
    memory_updated_at: null,
    active_generation: false,
    created_at: now,
    updated_at: now,
    messages: [],
  };
  const unrelatedChat = {
    ...clusterChat,
    id: "chat-other",
    title: "Unrelated cluster conversation",
    scope_cluster_id: "cluster-other",
  };
  const observedPageClusterIds: Array<string | null> = [];
  const observedCountClusterIds: Array<string | null> = [];
  const observedChatClusterIds: Array<string | null> = [];

  await page.route(`${backendOrigin}/api/v1/vaults`, (route) =>
    route.fulfill({
      json: [{ id: vaultId, name: "Active vault", path: "T:\\test", created_at: now, updated_at: now }],
    }),
  );
  await page.route(`${backendOrigin}/api/v1/clusters/${clusterId}`, (route) =>
    route.fulfill({ json: cluster }),
  );
  await page.route(
    (url) => url.origin === backendOrigin && url.pathname === "/api/v1/clusters",
    (route) => route.fulfill({ json: [cluster] }),
  );
  await page.route(
    (url) => url.origin === backendOrigin && url.pathname === "/api/v1/clusters/page",
    (route) => route.fulfill({ json: { items: [cluster], next_cursor: null, has_more: false } }),
  );
  await page.route(`${backendOrigin}/api/v1/clusters/${clusterId}/merge-artifacts`, (route) =>
    route.fulfill({ json: { cluster_id: clusterId, items: [] } }),
  );
  await page.route(
    (url) => url.origin === backendOrigin && url.pathname === "/api/v1/sources",
    (route) => {
      const requestedCluster = new URL(route.request().url()).searchParams.get("cluster_id");
      return route.fulfill({ json: requestedCluster === clusterId ? members : [...members, unrelated] });
    },
  );
  await page.route(
    (url) => url.origin === backendOrigin && url.pathname === "/api/v1/sources/page",
    (route) => {
      const requestedCluster = new URL(route.request().url()).searchParams.get("cluster_id");
      observedPageClusterIds.push(requestedCluster);
      const items = requestedCluster === clusterId ? members : [...members, unrelated];
      return route.fulfill({ json: { items, next_cursor: null, has_more: false, total: items.length } });
    },
  );
  await page.route(
    (url) => url.origin === backendOrigin && url.pathname === "/api/v1/sources/count",
    (route) => {
      const requestedCluster = new URL(route.request().url()).searchParams.get("cluster_id");
      observedCountClusterIds.push(requestedCluster);
      return route.fulfill({ json: { total: requestedCluster === clusterId ? members.length : 3 } });
    },
  );
  await page.route(`${backendOrigin}/api/v1/sources/${members[1].id}`, (route) =>
    route.fulfill({ json: members[1] }),
  );
  await page.route(`${backendOrigin}/api/v1/sources/${members[1].id}/stats`, (route) =>
    route.fulfill({
      json: { source_id: members[1].id, page_count: 1, chunk_count: 2, size_bytes: 256, last_error: null },
    }),
  );
  await page.route(
    (url) => url.origin === backendOrigin && url.pathname === "/api/v1/chat/sessions",
    (route) => {
      const requestedCluster = new URL(route.request().url()).searchParams.get("cluster_id");
      return route.fulfill({
        json: requestedCluster === clusterId ? [clusterChat] : [clusterChat, unrelatedChat],
      });
    },
  );
  await page.route(
    (url) => url.origin === backendOrigin && url.pathname === "/api/v1/chat/sessions/page",
    (route) => {
      const requestedCluster = new URL(route.request().url()).searchParams.get("cluster_id");
      observedChatClusterIds.push(requestedCluster);
      const items = requestedCluster === clusterId ? [clusterChat] : [clusterChat, unrelatedChat];
      return route.fulfill({ json: { items, next_cursor: null, has_more: false, total: items.length } });
    },
  );

  await page.goto(`/clusters/${clusterId}`);
  await expect(page).toHaveTitle("Cluster");
  await expect(page.getByRole("heading", { name: "Browser Start Issues" })).toBeVisible();
  await page.getByRole("button", { name: "Sources", exact: true }).click();
  const clusterSourceSearch = page.getByLabel("Search sources in this cluster");
  await expect(clusterSourceSearch).toBeEditable();
  await clusterSourceSearch.fill("startup-notes");
  await expect(page.getByText("startup-notes.md", { exact: true })).toBeVisible();
  await expect(page.getByText("browser-start.log", { exact: true })).toHaveCount(0);
  await page.getByRole("link", { name: /startup-notes\.md/ }).click();
  await expect.poll(() => {
    const url = new URL(page.url());
    return {
      pathname: url.pathname,
      cluster: url.searchParams.get("cluster"),
      source: url.searchParams.get("source"),
    };
  }).toEqual({ pathname: "/sources", cluster: clusterId, source: members[1].id });
  await expect(page.getByRole("heading", { name: "startup-notes.md" })).toBeVisible();

  await page.goBack();
  await expect(page.getByRole("heading", { name: "Browser Start Issues" })).toBeVisible();
  await page.getByRole("link", { name: "View all sources" }).click();

  await expect(page).toHaveURL(new RegExp(`/sources\\?cluster=${clusterId}`));
  await expect(page).toHaveTitle("Sources");
  await expect(page.getByRole("heading", { name: "Browser Start Issues" })).toBeVisible();
  await expect(page.getByText("2 sources in this cluster.")).toBeVisible();
  await expect(page.getByText("browser-start.log", { exact: true })).toBeVisible();
  await expect(page.getByText("startup-notes.md", { exact: true })).toBeVisible();
  await expect(page.getByText("unrelated-cluster.md", { exact: true })).toHaveCount(0);
  await expect.poll(() => observedPageClusterIds.at(-1)).toBe(clusterId);
  await expect.poll(() => observedCountClusterIds.at(-1)).toBe(clusterId);
  expect(consoleProblems).toEqual([]);

  if (process.env.CML_QA_CLUSTER_SOURCES_SCREENSHOT) {
    await page.screenshot({ path: process.env.CML_QA_CLUSTER_SOURCES_SCREENSHOT, fullPage: false });
  }

  await page.goBack();
  await expect(page.getByRole("heading", { name: "Browser Start Issues" })).toBeVisible();
  await page.getByRole("link", { name: "View all chats" }).click();
  await expect(page).toHaveURL(new RegExp(`/chat\\?cluster=${clusterId}`));
  await expect(page.getByRole("heading", { name: "Ask Browser Start Issues" })).toBeVisible();
  const clusterChatHistory = page
    .getByRole("button", { name: "New chat" })
    .locator("xpath=ancestor::aside");
  await expect(clusterChatHistory.getByText("Browser startup investigation", { exact: true })).toBeVisible();
  await expect(clusterChatHistory.getByText("Unrelated cluster conversation", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("combobox")).toContainText("Browser Start Issues");
  await expect(page.getByPlaceholder("Ask Browser Start Issues...")).toBeVisible();
  await expect.poll(() => observedChatClusterIds.at(-1)).toBe(clusterId);
  expect(consoleProblems).toEqual([]);

  if (process.env.CML_QA_CLUSTER_CHATS_SCREENSHOT) {
    await page.screenshot({ path: process.env.CML_QA_CLUSTER_CHATS_SCREENSHOT, fullPage: false });
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
      json: [
        {
          id: "vault-bridge",
          name: "Connected Library",
          path: "T:\\connected-library",
          created_at: now,
          updated_at: now,
        },
      ],
    }),
  );

  await page.goto("/bridge");
  await expect(page).toHaveTitle("Bridge");
  await expect(page.getByRole("heading", { name: "Connect AI tools" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Connect", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Review", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Activity", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Advanced", exact: true })).toBeVisible();
  await expect(
    page.getByText("Choose what the assistant can access", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Save useful answers without copying" }),
  ).toHaveCount(0);
  await expect(page.getByText("Connections allowed", { exact: true })).toBeVisible();
  if (process.env.CML_QA_BRIDGE_DEFAULT_SCREENSHOT) {
    await page.screenshot({ path: process.env.CML_QA_BRIDGE_DEFAULT_SCREENSHOT, fullPage: false });
  }

  await page.getByRole("button", { name: "Advanced", exact: true }).click();
  await expect(page.getByRole("button", { name: "Connection access", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Manual save", exact: true }).click();
  await expect(page.getByText(/fallback for tools that cannot call Vault directly/i)).toBeVisible();
  await expect(page.getByText("Set up an AI connection", { exact: true })).not.toBeVisible();
  expect(consoleProblems).toEqual([]);

  if (process.env.CML_QA_BRIDGE_SCREENSHOT) {
    await page.screenshot({ path: process.env.CML_QA_BRIDGE_SCREENSHOT, fullPage: false });
  }
});

test("Bridge history can traverse beyond two hundred records", async ({ page }) => {
  const consoleProblems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      consoleProblems.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => consoleProblems.push(`pageerror: ${error.message}`));
  const now = "2026-08-12T10:00:00Z";
  const requests = Array.from({ length: 225 }, (_, index) => ({
    id: `request-${String(index).padStart(3, "0")}`,
    client_id: null,
    client_name: "Long-running client",
    query: `Historical request ${index}`,
    mode: "context",
    decision: "allowed",
    source_count: 1,
    response_bytes: 128,
    created_at: now,
  }));
  const requestedOffsets: number[] = [];

  await page.route(`${backendOrigin}/api/v1/bridge/status`, (route) =>
    route.fulfill({
      json: {
        schema_version: 1,
        enabled: true,
        mcp: "available",
        http_api: "available",
        cli: "available",
        allowed_vault_ids: ["vault-history"],
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
        id: "vault-history",
        name: "History vault",
        path: "T:\\history",
        created_at: now,
        updated_at: now,
      }],
    }),
  );
  await page.route(`${backendOrigin}/api/v1/bridge/requests*`, (route) => {
    const url = new URL(route.request().url());
    const offset = Number(url.searchParams.get("offset") ?? 0);
    const limit = Number(url.searchParams.get("limit") ?? 50);
    requestedOffsets.push(offset);
    return route.fulfill({ json: requests.slice(offset, offset + limit) });
  });

  await page.goto("/bridge");
  await expect(page.getByText("Connections allowed", { exact: true })).toBeVisible();
  expect(consoleProblems).toEqual([]);
  const activityTab = page.getByRole("button", { name: "Activity", exact: true });
  await activityTab.click();
  await expect(activityTab).toHaveAttribute("aria-current", "page");
  await page.getByText("Historical request 0", { exact: true }).scrollIntoViewIfNeeded();
  await expect(page.getByText("Historical request 0", { exact: true })).toBeVisible();

  for (const offset of Array.from({ length: 11 }, (_, index) => (index + 1) * 20)) {
    await page.getByRole("button", { name: "Show more Bridge history" }).click();
    await expect.poll(() => requestedOffsets.at(-1)).toBe(offset);
  }

  await expect(page.getByText("Historical request 224", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Show more Bridge history" })).toHaveCount(0);
  expect(requestedOffsets).toContain(200);
  expect(requestedOffsets).toContain(220);
});

test("project detail distinguishes Odin freshness from Git changes", async ({ page }) => {
  test.setTimeout(90_000);
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
    interpretation_status: "ready",
    active_snapshot_id: "snapshot-active",
    active_manifest_snapshot_id: "snapshot-active",
    active_structure_snapshot_id: "snapshot-active",
    active_retrieval_snapshot_id: "snapshot-active",
    candidate_snapshot_id: null,
    active_run_id: "run-active",
    active_snapshot: null,
    brief: "A rendered project used to verify freshness semantics.",
    languages: { TypeScript: 12 },
    workspace_count: 1,
    entrypoints: ["src/main.ts"],
    source_count: 578,
    created_at: "2026-07-30T08:00:00Z",
    updated_at: "2026-07-30T08:30:00Z",
  };
  const activeRun = {
    id: "run-active",
    project_id: project.id,
    status: "running",
    phase: "retrieval_build",
    eligible_total: 593,
    completed_count: 324,
    phase_total_count: 593,
    phase_completed_count: 324,
    created_at: "2026-07-30T08:30:00Z",
    updated_at: "2026-07-30T08:31:00Z",
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
    repository_changed_paths: [
      "backend/app/core/projects.py",
      "apps/desktop/src/routes/project.tsx",
    ],
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
  const questionSession = {
    id: "chat-project-question",
    vault_id: project.vault_id,
    title: "Snapshot semantics: How does request routing work?",
    scope_cluster_id: project.primary_cluster_id,
    scope_project_id: project.id,
    scope_unclustered: false,
    saved: false,
    memory_status: "ready",
    memory_updated_at: project.updated_at,
    active_generation: false,
    created_at: project.updated_at,
    updated_at: project.updated_at,
    messages: [],
  };
  let questionCreateAttempts = 0;
  let createdQuestionPayload: Record<string, unknown> | null = null;
  let streamedQuestionPayload: Record<string, unknown> | null = null;
  await page.route(`${backendOrigin}/api/v1/vaults`, (route) =>
    route.fulfill({
      json: [{
        id: project.vault_id,
        name: "Rendered project vault",
        path: "T:\\Rendered",
        created_at: project.created_at,
        updated_at: project.updated_at,
      }],
    }),
  );
  await page.route(
    (url) => url.origin === backendOrigin && url.pathname === "/api/v1/chat/sessions",
    async (route) => {
      if (route.request().method() !== "POST") {
        await route.fulfill({ json: [questionSession] });
        return;
      }
      questionCreateAttempts += 1;
      if (questionCreateAttempts === 1) {
        await route.fulfill({
          status: 503,
          json: { detail: "Project question service temporarily unavailable." },
        });
        return;
      }
      createdQuestionPayload = route.request().postDataJSON() as Record<string, unknown>;
      await route.fulfill({ json: questionSession });
    },
  );
  await page.route(
    `${backendOrigin}/api/v1/chat/sessions/${questionSession.id}/metadata`,
    (route) => route.fulfill({ json: questionSession }),
  );
  await page.route(
    `${backendOrigin}/api/v1/chat/sessions/${questionSession.id}/timeline*`,
    (route) => route.fulfill({
      json: {
        session_id: questionSession.id,
        items: [],
        next_cursor: null,
        latest_cursor: null,
        has_more: false,
      },
    }),
  );
  await page.route(`${backendOrigin}/api/v1/chat/context/durable-stream`, async (route) => {
    streamedQuestionPayload = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: [
        "event: meta",
        `data: ${JSON.stringify({ generation_id: "generation-project-question", clusters_used: [], citations: [], coverage_ledger: null, attachments_stored: [], intent: "project_context", runtime_state: null, warnings: [] })}`,
        "",
        "event: token",
        `data: ${JSON.stringify({ text: "The request enters the route and follows the indexed handler." })}`,
        "",
        "event: done",
        `data: ${JSON.stringify({ session_id: questionSession.id, answer: "The request enters the route and follows the indexed handler.", memory_status: "indexed", intent: "project_context", warnings: [] })}`,
        "",
        "",
      ].join("\n"),
    });
  });
  await page.route(`${backendOrigin}/api/v1/projects/${project.id}`, (route) =>
    route.fulfill({ json: project }),
  );
  await page.route(`${backendOrigin}/api/v1/projects/${project.id}/intelligence`, (route) =>
    route.fulfill({ json: {
      id: null,
      contract_version: "odin-project-intelligence-v1",
      project_id: project.id,
      owning_snapshot_id: project.active_snapshot_id,
      structure_snapshot_id: project.active_snapshot_id,
      retrieval_snapshot_id: project.active_snapshot_id,
      indexed_commit: project.indexed_commit,
      generated_at: project.updated_at,
      identity: { name: project.name, repository_kind: "git", purpose: null, purpose_candidates: [], technologies: [] },
      architecture: { indexed_file_count: project.source_count },
      repository_signals: {},
      decisions: {},
      interpretation: { deterministic_synopsis: project.brief, generated_synopsis: null, primary_evidence_ids: [] },
      freshness: {},
      layers: { identity: { status: "partial", version: "test", generated_at: project.updated_at, truncated: false, unknown_reason: { code: "fixture", detail: "No supported root description in this fixture." } } },
      evidence: [],
    } }),
  );
  await page.route(`${backendOrigin}/api/v1/projects/${project.id}/runs*`, (route) =>
    route.fulfill({ json: [activeRun] }),
  );
  await page.route(`${backendOrigin}/api/v1/projects/${project.id}/runs/${activeRun.id}`, (route) =>
    route.fulfill({ json: activeRun }),
  );
  await page.route(`${backendOrigin}/api/v1/projects/${project.id}/links`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`${backendOrigin}/api/v1/projects/${project.id}/changes*`, (route) =>
    route.fulfill({ json: changes }),
  );
  await page.route(`${backendOrigin}/api/v1/projects/${project.id}/reindex`, async (route) => {
    const payload = route.request().postDataJSON();
    expect(payload).toEqual({ layer: "interpretation" });
    await route.fulfill({ json: { project, queued_jobs: 1, layer: "interpretation" } });
  });
  await page.route(`${backendOrigin}/api/v1/clusters*`, (route) => route.fulfill({ json: [] }));
  const graphNodeLimits: number[] = [];
  const graphRequests: Array<{ mode: string; query: string; direction: string; limit: number }> = [];
  await page.route(`${backendOrigin}/api/v1/projects/${project.id}/graph/view*`, (route) => {
    const requestUrl = new URL(route.request().url());
    const requestedLimit = Number(requestUrl.searchParams.get("max_nodes") ?? "90");
    const requestedQuery = requestUrl.searchParams.get("q") ?? "";
    const requestedMode = requestUrl.searchParams.get("mode") ?? "graph";
    const requestedDirection = requestUrl.searchParams.get("direction") ?? "balanced";
    graphNodeLimits.push(requestedLimit);
    graphRequests.push({
      mode: requestedMode,
      query: requestedQuery,
      direction: requestedDirection,
      limit: requestedLimit,
    });
    return route.fulfill({
      json: {
        version: 1,
        project_id: project.id,
        snapshot_id: "snapshot-active",
        indexed_commit: project.indexed_commit,
        mode: requestedMode,
        direction: requestedDirection,
        query: requestedQuery,
        root: "",
        nodes: [{
          id: "node-map-overview",
          qualified_id: "backend.app.api.routes.map.map_overview",
          kind: "function",
          language: "Python",
          label: "map_overview",
          relative_path: "backend/app/api/routes/map.py",
          start_line: 51,
          end_line: 140,
          signature: "map_overview(vault_id)",
          source_id: "source-map",
          matched_terms: ["map", "connections"],
        }, {
          id: "node-map-view",
          qualified_id: "apps.desktop.routes.MapView",
          kind: "function",
          language: "TypeScript",
          label: "MapView",
          relative_path: "apps/desktop/src/routes/_app.map.tsx",
          start_line: 20,
          end_line: 110,
          signature: "MapView()",
          source_id: "source-map-view",
          matched_terms: ["map"],
        }],
        edges: [{
          id: "edge-map-view",
          source: "node-map-view",
          target: "node-map-overview",
          type: "calls",
          confidence: "extracted",
          evidence_source_id: "source-map-view",
          source_line: 48,
        }],
        truncated: requestedLimit < 2000,
        limits: { max_nodes: requestedLimit, max_depth: requestedLimit >= 160 ? 3 : 2 },
        project_totals: { nodes: 10175, edges: 18873 },
        warnings: [],
        insights: {
          summary: "This view connects the map UI to its indexed connection API.",
          key_areas: [{
            id: "node-map-overview",
            label: "map_overview",
            kind: "function",
            relative_path: "backend/app/api/routes/map.py",
            connections: 1,
            why: "Direct question match: map, connections",
          }],
          flows: [],
          node_kinds: {},
          relationship_types: {},
          component_count: 0,
        },
      },
    });
  });
  await page.route(`${backendOrigin}/api/v1/projects/${project.id}/graph/path*`, (route) =>
    route.fulfill({
      json: {
        status: "found",
        path: [
          {
            id: "node-map-view",
            qualified_id: "apps.desktop.routes.MapView",
            display_label: "MapView",
            label: "MapView",
          },
          {
            id: "node-map-overview",
            qualified_id: "backend.app.api.routes.map.map_overview",
            display_label: "map_overview",
            label: "map_overview",
          },
        ],
        edges: [{ id: "edge-map-view", type: "calls" }],
        visited_nodes: 2,
        elapsed_ms: 3,
      },
    }),
  );

  await page.goto(`/projects/${project.id}`);
  await expect(page).toHaveTitle("Project");
  await expect(page.getByRole("heading", { name: project.name })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(project.brief)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Ask Odin" })).toBeVisible();
  await expect(page.getByLabel("Ask about this project")).toBeVisible();
  const progress = page.getByRole("region", { name: "Project indexing progress" });
  await expect(progress).toContainText("Preparing search");
  await expect(progress).toContainText("324 / 593");
  await expect(progress).not.toContainText("Step 3 of 4");
  await expect(progress).not.toContainText("active index remains available");
  if (process.env.CML_QA_OVERVIEW_SCREENSHOT) {
    await page.screenshot({ path: process.env.CML_QA_OVERVIEW_SCREENSHOT, fullPage: false });
  }
  await page.getByText("Suggested questions", { exact: true }).click();
  const suggestedQuestions = page
    .getByRole("navigation", { name: "Suggested project questions" })
    .getByRole("button");
  await expect(suggestedQuestions.first()).toContainText("Open the project map.");
  await expect(
    page.getByRole("button", { name: /Explain the application flow starting at src\/main\.ts/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: /How is the detected package or workspace in Snapshot semantics organized/,
    }),
  ).toBeVisible();
  const generalSuggestedQuestion = page.getByRole("button", {
    name: /Explain the application flow starting at src\/main\.ts/,
  });
  await generalSuggestedQuestion.click();
  await expect(page.getByText("Project question service temporarily unavailable.")).toBeVisible();
  await expect(generalSuggestedQuestion).toBeEnabled();
  await expect(page).toHaveURL(new RegExp(`/projects/${project.id}$`));
  expect(consoleProblems).toEqual([
    "error: Failed to load resource: the server responded with a status of 503 (Service Unavailable)",
  ]);
  consoleProblems.length = 0;
  await page.getByText("Project details", { exact: true }).click();
  await expect(page.getByText("Interpretation").locator("..")).toContainText("ready");
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
  await expect(page.getByRole("heading", { name: "Project map" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Graph" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "Fit map to view" })).toBeVisible();
  await page.getByRole("button", { name: /^map_overview / }).click();
  const nodeDetails = page.locator("aside").filter({
    has: page.getByRole("button", { name: "Close node details" }),
  });
  await expect(nodeDetails.getByText("map_overview(vault_id)", { exact: true })).toBeVisible();
  await expect(
    nodeDetails.getByText("Direct question match: map, connections", { exact: true }),
  ).toBeVisible();
  await nodeDetails.getByRole("button", { name: "Close node details" }).click();

  await page.getByRole("button", { name: "Advanced" }).click();
  await page.getByLabel("Relationship direction").selectOption("outbound");
  await expect.poll(() => graphRequests.at(-1)?.direction).toBe("outbound");
  await page.getByLabel("Path start item").fill("apps.desktop.routes.MapView");
  await page.getByLabel("Path end item").fill("backend.app.api.routes.map.map_overview");
  await page.getByRole("button", { name: "Trace", exact: true }).click();
  await expect(page.getByText(/MapView.*map_overview/)).toBeVisible();
  await expect(page.getByText("Checked 2 items in 3 ms.", { exact: true })).toBeVisible();
  await page.getByLabel("Path start item").fill("changed.item");
  await expect(page.getByText("Checked 2 items in 3 ms.", { exact: true })).toHaveCount(0);

  await page.getByRole("button", { name: "Tree" }).click();
  await expect(page.getByRole("button", { name: "Tree" })).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => graphRequests.at(-1)).toMatchObject({ mode: "tree", limit: 180 });
  await expect(page.getByRole("button", { name: /function\s+map_overview/ })).toBeVisible();
  await page.getByRole("button", { name: /function\s+map_overview/ }).click();
  await expect(page.getByText("backend/app/api/routes/map.py:51", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Graph" }).click();
  await expect.poll(() => graphRequests.at(-1)).toMatchObject({ mode: "graph", limit: 90 });
  await page.getByLabel("Filter project map").fill("Why are map connections shown?");
  await page.getByRole("button", { name: "Show", exact: true }).click();
  await expect(page.getByText(/question-focused items/)).toBeVisible();
  for (const expectedLimit of [160, 240, 300]) {
    await page.getByRole("button", { name: "Show more" }).click();
    await expect.poll(() => graphNodeLimits.at(-1)).toBe(expectedLimit);
  }
  await page.getByRole("button", { name: "Show all relevant" }).click();
  await expect.poll(() => graphNodeLimits.at(-1)).toBe(2000);
  await expect(page.getByText(/complete relevant slice/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Show all relevant" })).toBeDisabled();
  if (process.env.CML_QA_PROJECT_MAP_SCREENSHOT) {
    await page.screenshot({ path: process.env.CML_QA_PROJECT_MAP_SCREENSHOT, fullPage: false });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("heading", { name: "Project map" })).toBeVisible();
  await expect(page.getByLabel("Filter project map")).toBeVisible();
  await expect(page.getByRole("button", { name: "Graph" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Tree" })).toBeVisible();
  if (process.env.CML_QA_PROJECT_MAP_MOBILE_SCREENSHOT) {
    await page.screenshot({ path: process.env.CML_QA_PROJECT_MAP_MOBILE_SCREENSHOT, fullPage: false });
  }
  await page.setViewportSize({ width: 1024, height: 680 });
  await page.goBack();
  await page.getByRole("button", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Project settings" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh interpretation" })).toBeVisible();
  await page.getByRole("button", { name: "Refresh interpretation" }).click();
  await expect(page.getByText("Interpretation refresh queued.")).toBeVisible();
  if (process.env.CML_QA_PROJECT_SETTINGS_SCREENSHOT) {
    await page.screenshot({ path: process.env.CML_QA_PROJECT_SETTINGS_SCREENSHOT, fullPage: false });
  }
  await page.getByLabel("Ask about this project").fill("How does request routing work?");
  await page.getByRole("button", { name: "Ask Odin", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/chat/${questionSession.id}$`));
  await expect.poll(() => createdQuestionPayload).toMatchObject({
    vault_id: project.vault_id,
    scope_cluster_id: project.primary_cluster_id,
    scope_project_id: project.id,
  });
  await expect.poll(() => streamedQuestionPayload).toMatchObject({
    prompt: "How does request routing work?",
    session_id: questionSession.id,
    persist: true,
  });
  await expect(
    page.getByText("The request enters the route and follows the indexed handler.", { exact: true }).first(),
  ).toBeVisible();
  expect(consoleProblems).toEqual([]);
});

test("map Connections mode reveals semantic cluster edges", async ({ page }) => {
  const consoleProblems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      consoleProblems.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => consoleProblems.push(`pageerror: ${error.message}`));

  const vault = {
    id: "vault-map-connections",
    name: "Connected library",
    path: "T:\\connected",
    created_at: "2026-08-01T09:00:00Z",
    updated_at: "2026-08-01T09:00:00Z",
  };
  const nodes = [
    {
      id: "cluster-ethics",
      kind: "cluster",
      label: "Ethical practice",
      summary: "Privacy and professional ethics.",
      color: "sage",
      state: "ready",
      source_count: 2,
      fact_count: 0,
      updated_at: "2026-08-01T09:00:00Z",
    },
    {
      id: "cluster-privacy",
      kind: "cluster",
      label: "Privacy reports",
      summary: "Privacy and surveillance reports.",
      color: "sky",
      state: "ready",
      source_count: 2,
      fact_count: 0,
      updated_at: "2026-08-01T09:00:00Z",
    },
  ];
  const edge = {
    id: "similarity:cluster-ethics:cluster-privacy",
    source: "cluster-ethics",
    target: "cluster-privacy",
    kind: "similarity",
    label: "59% similar",
    direction: "undirected",
    temporal_state: "current",
    provenance_ids: ["source-ethics", "source-privacy"],
    updated_at: "2026-08-01T09:00:00Z",
    relationship_basis: "semantic_similarity",
    similarity_score: 0.59,
    shared_terms: ["privacy", "ethical"],
    evidence_labels: ["Shared topics: privacy, ethical"],
  };

  await page.route(`${backendOrigin}/api/v1/vaults`, (route) => route.fulfill({ json: [vault] }));
  await page.route(`${backendOrigin}/api/v1/map/overview*`, (route) => {
    const url = new URL(route.request().url());
    const connected = url.searchParams.get("connections") === "similar";
    return route.fulfill({
      json: {
        vault_id: vault.id,
        nodes,
        edges: connected ? [edge] : [],
        total: 2,
        cluster_total: 2,
        unclustered_count: 0,
        limit: 160,
        offset: 0,
        truncated: false,
        connection_mode: connected ? "similar" : "current",
        relationship_policy: connected ? "evidence_and_similarity" : "authoritative_only",
      },
    });
  });

  await page.goto("/map");
  await expect(page).toHaveTitle("Map");
  await expect(page.getByRole("heading", { name: "Knowledge map" })).toBeVisible();
  await page.getByRole("button", { name: "Connections" }).click();
  await expect(page.getByText("1 strong local connection.")).toBeVisible();
  await page.getByRole("button", { name: "List" }).click();
  await expect(page.getByText(/1 relationship.*59% similar/).first()).toBeVisible();
  if (process.env.CML_QA_MAP_CONNECTIONS_SCREENSHOT) {
    await page.screenshot({ path: process.env.CML_QA_MAP_CONNECTIONS_SCREENSHOT, fullPage: false });
  }
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
  await expect(page).toHaveURL(/\/home$/);
});

test("window-aware controls never intersect native controls at minimum size", async ({ page }) => {
  await page.goto("/projects");
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();
  await expect(page.getByLabel("Window controls")).toBeVisible();
  await page.mouse.move(512, 1);
  await expect.poll(async () => {
    const bounds = await page.getByTestId("window-chrome").boundingBox();
    return bounds?.y;
  }).toBe(0);

  const geometry = await page.evaluate(() => {
    const safe = document
      .querySelector<HTMLElement>("[data-window-control-safe-zone]")
      ?.getBoundingClientRect();
    const collisions = [...document.querySelectorAll<HTMLElement>(".vault-window-aware > *")]
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        return Boolean(
          safe &&
          rect.right > safe.left &&
          rect.left < safe.right &&
          rect.bottom > safe.top &&
          rect.top < safe.bottom,
        );
      })
      .map((element) => element.textContent?.trim().slice(0, 80) || element.tagName);
    return {
      safe: safe && { left: safe.left, right: safe.right, top: safe.top, bottom: safe.bottom },
      collisions,
    };
  });

  expect(geometry.safe).toEqual({ left: 886, right: 1024, top: 0, bottom: 32 });
  expect(geometry.collisions).toEqual([]);
});

test("requested sidebar artwork renders cleanly in the desktop shell", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/projects");
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();

  const artwork = await page.evaluate(() => {
    const sidebarArtwork = document.querySelector<HTMLImageElement>(".vault-sidebar-wordmark img");
    const wordmark = document.querySelector<HTMLElement>(".vault-sidebar-wordmark");
    const wordmarkRect = wordmark?.getBoundingClientRect();
    return {
      src: sidebarArtwork?.getAttribute("src"),
      width: wordmarkRect?.width,
      height: wordmarkRect?.height,
    };
  });

  expect(artwork).toEqual({ src: "/brand/Frame%208.png", width: 200, height: 96 });
  await page.getByRole("link", { name: "Home", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();

  if (process.env.CML_QA_WINDOW_CHROME_SCREENSHOT) {
    await page.screenshot({
      path: process.env.CML_QA_WINDOW_CHROME_SCREENSHOT,
      fullPage: false,
    });
  }
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
      json: [
        {
          id: "vault-import",
          name: "Import vault",
          path: "T:\\import",
          created_at: now,
          updated_at: now,
        },
      ],
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
      json: [
        {
          id: "vault-clusters",
          name: "Cluster vault",
          path: "T:\\clusters",
          created_at: now,
          updated_at: now,
        },
      ],
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
    const payload = route.request().postDataJSON() as {
      name: string;
      vault_id: string;
      color: string;
    };
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

test("Clusters exposes indexed unclustered sources and opens the complete unclustered view", async ({ page }) => {
  const consoleProblems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      consoleProblems.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => consoleProblems.push(`pageerror: ${error.message}`));

  const now = "2026-08-10T10:00:00Z";
  const vaultId = "vault-unclustered";
  const sources = Array.from({ length: 9 }, (_, index) => ({
    id: `source-unclustered-${index + 1}`,
    vault_id: vaultId,
    cluster_id: null,
    title: `Unclustered indexed source ${index + 1}.md`,
    source_type: "file",
    state: "indexed",
    ingestion_stage: "ready",
    ingestion_generation: 1,
    ingestion_error_code: null,
    ingestion_status_detail: "Ready",
    ingestion_updated_at: now,
    original_path: `T:\\test\\unclustered-${index + 1}.md`,
    import_root_path: null,
    import_relative_path: null,
    url: null,
    raw_text: "",
    extracted_text: `Indexed unclustered source ${index + 1}.`,
    summary: `Unclustered source ${index + 1} summary`,
    tags: [],
    metadata_quality: "semantic",
    semantic_metadata_version: 2,
    semantic_metadata_updated_at: now,
    cover_image_url: null,
    created_at: now,
    updated_at: now,
  }));
  const observedSourceRequests: Array<{ unclustered: string | null; states: string | null }> = [];

  await page.route(`${backendOrigin}/api/v1/vaults`, (route) =>
    route.fulfill({
      json: [{ id: vaultId, name: "Active vault", path: "T:\\test", created_at: now, updated_at: now }],
    }),
  );
  await page.route(`${backendOrigin}/api/v1/clusters/page*`, (route) =>
    route.fulfill({ json: { items: [], next_cursor: null, has_more: false } }),
  );
  await page.route(`${backendOrigin}/api/v1/clusters/suggestions*`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`${backendOrigin}/api/v1/sources/counts-by-cluster*`, (route) =>
    route.fulfill({ json: { items: [{ cluster_id: null, state: "indexed", total: 9 }] } }),
  );
  await page.route(`${backendOrigin}/api/v1/projects/cluster-membership-summary*`, (route) =>
    route.fulfill({ json: { cluster_ids: [] } }),
  );
  await page.route(`${backendOrigin}/api/v1/sources/latest-by-cluster*`, (route) =>
    route.fulfill({ json: { items: [] } }),
  );
  await page.route(
    (url) => url.origin === backendOrigin && url.pathname === "/api/v1/sources/page",
    (route) => {
      const url = new URL(route.request().url());
      observedSourceRequests.push({
        unclustered: url.searchParams.get("unclustered"),
        states: url.searchParams.get("states"),
      });
      return route.fulfill({
        json: { items: sources, next_cursor: null, has_more: false, total: sources.length },
      });
    },
  );
  await page.route(
    (url) => url.origin === backendOrigin && url.pathname === "/api/v1/sources/count",
    (route) => route.fulfill({ json: { total: sources.length } }),
  );

  await page.goto("/clusters");
  await expect(page).toHaveTitle("Clusters");
  await expect(page.getByRole("heading", { name: "Clusters" })).toBeVisible();
  const unclusteredRow = page.getByRole("link", { name: "Open Unclustered sources, 9 sources" });
  await expect(unclusteredRow).toBeVisible();
  await expect(unclusteredRow).toContainText("9");
  await expect(unclusteredRow).toContainText("Needs organization");
  if (process.env.CML_QA_UNCLUSTERED_CLUSTER_SCREENSHOT) {
    await page.screenshot({ path: process.env.CML_QA_UNCLUSTERED_CLUSTER_SCREENSHOT, fullPage: false });
  }

  await unclusteredRow.click();
  await expect(page).toHaveURL(/\/sources\?filter=unclustered/);
  await expect(page).toHaveTitle("Sources");
  await expect(page.getByRole("heading", { name: "Unclustered sources" })).toBeVisible();
  await expect(page.getByText("Showing 9 of 9 sources")).toBeVisible();
  await expect(page.getByText("Unclustered indexed source 1.md", { exact: true })).toBeVisible();
  await expect.poll(() => observedSourceRequests.at(-1)).toEqual({
    unclustered: "true",
    states: null,
  });
  expect(consoleProblems).toEqual([]);
  if (process.env.CML_QA_UNCLUSTERED_SOURCES_SCREENSHOT) {
    await page.screenshot({ path: process.env.CML_QA_UNCLUSTERED_SOURCES_SCREENSHOT, fullPage: false });
  }
});

test("settings explains passphrase requirements before protected setup", async ({ page }) => {
  const now = "2026-07-31T08:00:00Z";
  let initializeRequests = 0;
  await page.route(`${backendOrigin}/api/v1/vaults`, (route) =>
    route.fulfill({
      json: [
        {
          id: "vault-unprotected",
          name: "Unprotected vault",
          path: "T:\\unprotected",
          created_at: now,
          updated_at: now,
        },
      ],
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
  await page.route(`${backendOrigin}/api/v1/jobs/temporal-facts/status*`, (route) =>
    route.fulfill({
      json: {
        vault_id: "vault-unprotected",
        extractor_version: "test",
        session_count: 0,
        indexed_session_count: 0,
        pending_session_count: 0,
        fact_count: 0,
        status_counts: { current: 0 },
        latest_observed_at: null,
      },
    }),
  );

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

test("delete and restart setup survive authorization taking longer than 12 seconds", async ({ page }) => {
  test.setTimeout(45_000);
  const consoleProblems: string[] = [];
  page.on("console", (message) => {
    if (
      (message.type() === "error" || message.type() === "warning") &&
      !message.text().includes("Failed to load resource")
    ) {
      consoleProblems.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => consoleProblems.push(`pageerror: ${error.message}`));
  const now = "2026-08-10T00:00:00Z";
  const vault = {
    id: "vault-delete",
    name: "My Library",
    path: "T:\\test",
    created_at: now,
    updated_at: now,
  };
  let authorizationCompleted = false;
  await page.route(`${backendOrigin}/api/v1/vaults`, (route) =>
    route.fulfill({ json: [vault] }),
  );
  await page.route(`${backendOrigin}/api/v1/system/unlock/status`, (route) =>
    route.fulfill({
      json: {
        state: "ready",
        ready: true,
        secured_vault_count: 0,
        secured_vault_ids: [],
      },
    }),
  );
  await page.route(`${backendOrigin}/api/v1/jobs/temporal-facts/status*`, (route) =>
    route.fulfill({
      json: {
        vault_id: vault.id,
        extractor_version: "test",
        session_count: 0,
        indexed_session_count: 0,
        pending_session_count: 0,
        fact_count: 0,
        status_counts: { current: 0 },
        latest_observed_at: null,
      },
    }),
  );
  await page.route(`${backendOrigin}/api/v1/chat/evidence-retention/policy`, (route) =>
    route.fulfill({
      json: {
        default_keep_latest_snapshots_per_message: 1,
        max_keep_latest_snapshots_per_message: 10,
        default_excerpt_chars: 240,
        deleted_source_state: "tombstoned",
        compacted_state: "compacted",
        query_cache_prune_endpoint: "",
      },
    }),
  );
  await page.route(
    `${backendOrigin}/api/v1/vaults/${vault.id}/delete/authorize`,
    async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 13_000));
      authorizationCompleted = true;
      await route.fulfill({ json: { authorized: true, vault_id: vault.id } });
    },
  );

  await page.goto(`/settings?section=advanced&backendUrl=${encodeURIComponent(backendOrigin)}`);
  await expect(page.getByRole("button", { name: /Delete library/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Restart setup/ })).toBeVisible();
  await page.getByRole("button", { name: /Restart setup/ }).click();
  await expect(page.getByRole("heading", { name: "Wipe this library and restart setup?" })).toBeVisible();
  await page.getByPlaceholder("My Library").fill("My Library");
  if (process.env.CML_QA_VAULT_RESTART_SCREENSHOT) {
    await page.screenshot({
      path: process.env.CML_QA_VAULT_RESTART_SCREENSHOT,
      fullPage: false,
    });
  }
  await page.getByRole("button", { name: "Wipe and restart" }).click();

  await expect.poll(() => authorizationCompleted, { timeout: 20_000 }).toBe(true);
  await expect(page).toHaveURL(/\/onboarding/);
  await expect.poll(() =>
    page.evaluate(() =>
      Boolean(
        (window as typeof window & { __vaultDeletionFinalized?: boolean })
          .__vaultDeletionFinalized,
      ),
    )
  ).toBe(true);
  expect(consoleProblems).toEqual([]);
});

test("Memory history settles completed refreshes and retries failed insight loads", async ({ page }) => {
  test.setTimeout(30_000);
  const consoleProblems: string[] = [];
  page.on("console", (message) => {
    if (
      (message.type() === "error" || message.type() === "warning") &&
      !message.text().includes("Failed to load resource")
    ) {
      consoleProblems.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => consoleProblems.push(`pageerror: ${error.message}`));

  const vault = {
    id: "vault-memory",
    name: "My Library",
    path: "T:\\test",
    created_at: "2026-08-02T09:00:00Z",
    updated_at: "2026-08-02T09:00:00Z",
  };
  let refreshRunning = true;
  let memoryAvailable = false;
  let jobStatusRequests = 0;
  let memoryStatusRequests = 0;
  const memoryJob = {
    id: "memory-refresh-1",
    job_type: "temporal_fact_backfill",
    status: "running",
    created_at: "2026-08-02T09:00:00Z",
    updated_at: "2026-08-02T09:00:01Z",
  };

  await page.route((url) => url.origin === backendOrigin && url.pathname === "/api/v1/system/unlock/status", (route) =>
    route.fulfill({
      json: {
        ready: true,
        state: "ready",
        secured_vault_count: 0,
        secured_vault_ids: [],
      },
    }),
  );
  await page.route(
    (url) => url.origin === backendOrigin && url.pathname === "/api/v1/vaults",
    (route) => route.fulfill({ json: [vault] }),
  );
  await page.route((url) => url.origin === backendOrigin && url.pathname === "/api/v1/jobs/status", (route) =>
    {
      jobStatusRequests += 1;
      return route.fulfill({
      json: {
        queued: 0,
        paused: 0,
        blocked_by_dependency: 0,
        blocked_setup_required: 0,
        blocked_local_model: 0,
        deferred: 0,
        running: refreshRunning ? 1 : 0,
        succeeded: refreshRunning ? 0 : 1,
        partial_success: 0,
        failed: 0,
        cancelled: 0,
        manual_review: 0,
        running_jobs: refreshRunning ? [memoryJob] : [],
        latest: refreshRunning ? [memoryJob] : [{ ...memoryJob, status: "succeeded" }],
      },
      });
    },
  );
  await page.route((url) => url.origin === backendOrigin && url.pathname === "/api/v1/chat/evidence-retention/policy", (route) =>
    route.fulfill({
      json: {
        default_keep_latest_snapshots_per_message: 1,
        max_keep_latest_snapshots_per_message: 10,
        default_excerpt_chars: 240,
        deleted_source_state: "tombstoned",
        compacted_state: "compacted",
        query_cache_prune_endpoint: "",
      },
    }),
  );
  await page.route((url) => url.origin === backendOrigin && url.pathname === "/api/v1/jobs/temporal-facts/status", (route) =>
    {
      memoryStatusRequests += 1;
      return memoryAvailable
      ? route.fulfill({
          json: {
            vault_id: vault.id,
            extractor_version: "test",
            status_counts: { current: 0 },
            speaker_counts: {},
            assertion_kind_counts: {},
            session_count: 0,
            indexed_session_count: 0,
            latest_observed_at: null,
            latest_processed_at: "2026-08-02T09:00:02Z",
          },
        })
      : route.fulfill({ status: 503, json: { detail: "Memory history unavailable" } });
    },
  );
  await page.route((url) => url.origin === backendOrigin && url.pathname === "/api/v1/memory/facts", (route) =>
    memoryAvailable
      ? route.fulfill({ json: [] })
      : route.fulfill({ status: 503, json: { detail: "Memory facts unavailable" } }),
  );

  await page.goto(`/settings?section=library&backendUrl=${encodeURIComponent(backendOrigin)}`);
  const card = page.locator("section").filter({ has: page.getByRole("heading", { name: "Memory history" }) });
  await expect.poll(() => jobStatusRequests).toBeGreaterThan(0);
  await expect.poll(() => memoryStatusRequests).toBeGreaterThan(0);
  expect(consoleProblems).toEqual([]);
  await expect(card).toContainText("Refreshing");
  await expect(card.getByRole("alert")).toContainText("Memory history could not be checked");
  await expect(card.getByRole("button", { name: "Try again" })).toBeVisible();

  refreshRunning = false;
  memoryAvailable = true;
  await card.getByRole("button", { name: "Try again" }).click();
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));

  await expect(card).toContainText("0 of 0 conversations");
  await expect(card).not.toContainText("Refreshing");
  await expect(card.getByRole("button", { name: "Refresh memory history" })).toBeEnabled();
  expect(consoleProblems).toEqual([]);
  if (process.env.CML_QA_MEMORY_HISTORY_SCREENSHOT) {
    await card.screenshot({ path: process.env.CML_QA_MEMORY_HISTORY_SCREENSHOT });
  }
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
    const safe = document
      .querySelector<HTMLElement>("[data-window-control-safe-zone]")
      ?.getBoundingClientRect();
    const collisionCount = [
      ...document.querySelectorAll<HTMLElement>(".vault-window-aware > *"),
    ].filter((element) => {
      const rect = element.getBoundingClientRect();
      return Boolean(
        safe &&
        rect.right > safe.left &&
        rect.left < safe.right &&
        rect.bottom > safe.top &&
        rect.top < safe.bottom,
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
      json: {
        provider: "managed",
        base_url: "",
        model: "",
        available: false,
        detail: "Not started",
      },
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
      json: {
        os: "Windows",
        machine: "x64",
        processor: "Test",
        cpu_count: 8,
        hardware_tier: "balanced",
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
