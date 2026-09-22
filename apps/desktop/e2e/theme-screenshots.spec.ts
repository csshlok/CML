import { expect, test, type Page } from "@playwright/test";

/**
 * Reviewable Phase 0 light/dark baselines.
 *
 * This suite intentionally captures deterministic empty/degraded fixtures rather
 * than real vault content. Populated Project Graph, Knowledge Map, cluster,
 * source-inspector, and chat-generation interactions remain covered by
 * desktop-shell.spec.ts; model downloads, native folder pickers, and the
 * standalone repair document are excluded because they require OS/native
 * process state. The local Electron smoke validates startup/chrome/theme
 * switching separately without checking private user data into screenshots.
 */

const backendOrigin = "http://127.0.0.1:7343";
const themeStorageKey = "cml.theme-preference.v1";

type Theme = "light" | "dark";

const surfaces = [
  { name: "onboarding", path: "/onboarding", marker: "body" },
  { name: "home", path: "/home", marker: ".vault-shell" },
  { name: "sources", path: "/sources", marker: ".vault-shell" },
  { name: "search", path: "/search", marker: ".vault-shell" },
  { name: "chat", path: "/chat", marker: ".vault-shell" },
  { name: "clusters", path: "/clusters", marker: ".vault-shell" },
  { name: "timeline", path: "/timeline", marker: ".vault-shell" },
  { name: "tasks", path: "/tasks", marker: ".vault-shell" },
  { name: "bridge", path: "/bridge", marker: ".vault-shell" },
  { name: "help", path: "/help", marker: ".vault-shell" },
  { name: "settings-profile", path: "/settings?section=profile", marker: ".vault-shell" },
  { name: "settings-library", path: "/settings?section=library", marker: ".vault-shell" },
  { name: "settings-models", path: "/settings?section=models", marker: ".vault-shell" },
  { name: "settings-connections", path: "/settings?section=connections", marker: ".vault-shell" },
  { name: "settings-health", path: "/settings?section=health", marker: ".vault-shell" },
  { name: "settings-advanced", path: "/settings?section=advanced", marker: ".vault-shell" },
  { name: "projects", path: "/projects", marker: ".vault-shell" },
  { name: "project-detail-unavailable", path: "/projects/visual-fixture", marker: ".vault-shell" },
  { name: "project-map-unselected", path: "/project-map", marker: ".vault-shell" },
  { name: "knowledge-map", path: "/map", marker: ".vault-shell" },
] as const;

async function installStableBackendFixture(page: Page) {
  // Playwright resolves matching routes in reverse registration order. Keep the
  // catch-all first so the endpoint-specific fixtures below always win.
  await page.route(`${backendOrigin}/api/v1/**`, (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/count")) return route.fulfill({ json: { count: 0 } });
    if (url.pathname.includes("/page") || url.pathname.endsWith("/folders")) {
      return route.fulfill({
        json: { items: [], next_cursor: null, has_more: false, total: 0 },
      });
    }
    return route.fulfill({
      status: 503,
      json: { detail: "This deterministic visual fixture does not configure this service." },
    });
  });
  await page.route(`${backendOrigin}/health`, (route) =>
    route.fulfill({ json: { status: "ok" } }),
  );
  await page.route(`${backendOrigin}/api/v1/system/backend-identity`, (route) =>
    route.fulfill({ json: { service: "cml-backend", api_prefix: "/api/v1" } }),
  );
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
        updated_at: "2026-09-21T12:00:00Z",
        has_vendor_recovery: false,
      },
    }),
  );
  await page.route(`${backendOrigin}/api/v1/vaults`, (route) => route.fulfill({ json: [] }));
  await page.route(`${backendOrigin}/api/v1/jobs/status*`, (route) =>
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
  await page.route(`${backendOrigin}/api/v1/chat/sessions*`, (route) =>
    route.fulfill({ json: [] }),
  );
}

async function applyStableRendering(page: Page) {
  await page.addStyleTag({
    content: `
      *, *::before, *::after {
        animation-delay: 0s !important;
        animation-duration: 0s !important;
        caret-color: transparent !important;
        transition-delay: 0s !important;
        transition-duration: 0s !important;
      }
    `,
  });
  await page.evaluate(() => {
    document.querySelectorAll("time").forEach((element) => {
      element.setAttribute("data-visual-baseline", "fixed-time");
    });
  });
}

async function waitForBrandArtwork(page: Page) {
  const artwork = page.locator(".vault-brand-art").first();
  if (await artwork.count() === 0) return;
  const source = await artwork.evaluate((element) => {
    const match = getComputedStyle(element).backgroundImage.match(/^url\(["']?(.*?)["']?\)$/);
    return match?.[1] ?? "";
  });
  if (!source) return;
  await page.evaluate(async (url) => {
    const image = new Image();
    image.src = url;
    await image.decode();
  }, source);
}

for (const theme of ["light", "dark"] as const satisfies readonly Theme[]) {
  test.describe(`${theme} visual baseline`, () => {
    for (const surface of surfaces) {
      test(`${surface.name}`, async ({ page }) => {
        if (surface.name === "onboarding") test.slow();
        await installStableBackendFixture(page);
        await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
        await page.addInitScript(
          ([key, preference]) => {
            window.localStorage.setItem(key, JSON.stringify({ version: 1, preference }));
          },
          [themeStorageKey, theme] as const,
        );

        await page.goto(surface.path, { waitUntil: "domcontentloaded" });
        await expect(page.locator(surface.marker).first()).toBeVisible({ timeout: 20_000 });
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
        if (surface.name === "onboarding") {
          await expect(page.getByRole("button", { name: "Start Setup" })).toBeVisible({
            timeout: 45_000,
          });
        }
        if (surface.name === "projects") {
          await expect(page.getByRole("heading", { name: "No projects indexed yet" })).toBeVisible({
            timeout: 20_000,
          });
        }
        await waitForBrandArtwork(page);
        if (theme === "dark" && surface.name === "onboarding") {
          const logo = page.locator(".vault-brand-logo").first();
          await expect(logo).toBeVisible();
          const art = logo.locator(".vault-brand-art");
          await expect
            .poll(() => art.evaluate((element) => getComputedStyle(element).backgroundImage))
            .toContain("Frame%208%20inverted.svg");
        }
        await applyStableRendering(page);
        await page.waitForTimeout(350);

        await expect(page).toHaveScreenshot(`${surface.name}-${theme}.png`, {
          animations: "disabled",
          caret: "hide",
          fullPage: false,
          maxDiffPixelRatio: 0.01,
        });
      });
    }
  });
}
