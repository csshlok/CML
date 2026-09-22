import { expect, test, type Page } from "@playwright/test";

// Renderer-side theme runtime coverage (THEME-08). These tests exercise the
// dev-web fallback path in src/lib/theme.ts (matchMedia + localStorage),
// which is the exact code path this Playwright suite actually runs against
// (`npm run dev:web`, no packaged Electron). The Electron main-process side
// of the same contract — IPC persistence, OS-change propagation to every
// BrowserWindow, corrupted/missing preference-file recovery — is already
// exhaustively covered at the unit level in electron/theme.test.cjs; this
// suite proves the renderer half: DOM application, pre-paint timing,
// storage-denial resilience, and (via a simulated cmlDesktop bridge) that
// two independent window/document contexts react identically to the same
// broadcast.
//
// Known environment limitation: "packaged file:// load" (the other half of
// the plan's "for both dev and packaged-style loads" requirement) cannot be
// exercised here — this sandbox has no display and cannot launch a packaged
// Electron build. Only the dev-server load path is verified below.

const backendOrigin = "http://127.0.0.1:7343";
const THEME_STORAGE_KEY = "cml.theme-preference.v1";
const APPEARANCE_URL = "/settings?section=profile";

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

const html = (page: Page) => page.locator("html");

// TanStack Start's SSR markup for the Appearance radios is present and
// visible before React hydrates it; clicking too early dispatches a real
// native "change" event with no React fiber attached yet, so it silently
// does nothing (matches the existing `__reactProps` poll pattern used
// elsewhere in this suite, e.g. desktop-shell.spec.ts's Help search input).
async function waitForHydration(locator: ReturnType<Page["locator"]>) {
  await expect
    .poll(
      () => locator.evaluate((element) => Object.keys(element).some((key) => key.startsWith("__reactProps"))),
      { timeout: 20_000 },
    )
    .toBe(true);
}

test.beforeEach(async ({ page }) => {
  await installBaseRoutes(page);
});

test.describe("theme resolution and persistence", () => {
  for (const preference of ["dark", "light", "system"] as const) {
    test(`selecting ${preference} in Settings > Profile persists across reload`, async ({ page }) => {
      // Pin the OS preference so "system" has an unambiguous expected value.
      await page.emulateMedia({ colorScheme: "light" });
      await page.goto(APPEARANCE_URL);
      await expect(page.locator(".vault-shell")).toBeVisible();

      // "system" is the default preference on a fresh load, so selecting it
      // directly would be a same-value no-op (AppearanceSettings.choose()
      // short-circuits when the value hasn't changed) and never exercise
      // the actual write path. Start from a different preference first so
      // every case in this loop performs a real transition.
      const startFrom = preference === "system" ? "light" : "system";
      const startRadio = page.locator(`input[name="theme-preference"][value="${startFrom}"]`);
      await waitForHydration(startRadio);
      if (startFrom !== "system") await startRadio.check();

      const radio = page.locator(`input[name="theme-preference"][value="${preference}"]`);
      await radio.check();
      const expectedResolved = preference === "dark" ? "dark" : "light";
      await expect(html(page)).toHaveAttribute("data-theme", expectedResolved);
      await expect
        .poll(() => page.evaluate(() => document.documentElement.classList.contains("dark")))
        .toBe(expectedResolved === "dark");

      const stored = await page.evaluate(
        (key) => window.localStorage.getItem(key),
        THEME_STORAGE_KEY,
      );
      expect(JSON.parse(stored!).preference).toBe(preference);

      await page.reload();
      await expect(page.locator(".vault-shell")).toBeVisible();
      await expect(html(page)).toHaveAttribute("data-theme", expectedResolved);
      await expect(
        page.locator(`input[name="theme-preference"][value="${preference}"]`),
      ).toBeChecked();
    });
  }

  test("corrupted stored preference falls back to System without blocking startup", async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    await page.addInitScript(
      (key) => window.localStorage.setItem(key, "{not valid json"),
      THEME_STORAGE_KEY,
    );
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await page.goto(APPEARANCE_URL, { waitUntil: "domcontentloaded" });
    await expect(page.locator(".vault-shell")).toBeVisible();
    // System + OS-dark -> resolved dark; the corrupt value never surfaces.
    await expect(html(page)).toHaveAttribute("data-theme", "dark");
    await expect(page.locator('input[name="theme-preference"][value="system"]')).toBeChecked();
    expect(pageErrors).toEqual([]);
  });

  test("a stored preference outside system/light/dark falls back to System", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "light" });
    await page.addInitScript(
      (key) => window.localStorage.setItem(key, JSON.stringify({ version: 1, preference: "purple" })),
      THEME_STORAGE_KEY,
    );
    await page.goto(APPEARANCE_URL, { waitUntil: "domcontentloaded" });
    await expect(page.locator(".vault-shell")).toBeVisible();
    await expect(html(page)).toHaveAttribute("data-theme", "light");
    await expect(page.locator('input[name="theme-preference"][value="system"]')).toBeChecked();
  });

  test("blocked localStorage access falls back to System without blocking startup", async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme: "light" });
    await page.addInitScript(() => {
      Object.defineProperty(window, "localStorage", {
        configurable: true,
        get() {
          throw new DOMException("Storage access is denied in this context.", "SecurityError");
        },
      });
    });
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await page.goto(APPEARANCE_URL, { waitUntil: "domcontentloaded" });
    await expect(page.locator(".vault-shell")).toBeVisible();
    await expect(html(page)).toHaveAttribute("data-theme", "light");
    expect(pageErrors).toEqual([]);
  });
});

test.describe("OS change propagation", () => {
  test("System live-updates on an OS scheme change", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "light" });
    await page.goto(APPEARANCE_URL);
    await expect(page.locator(".vault-shell")).toBeVisible();
    await expect(html(page)).toHaveAttribute("data-theme", "light");

    await page.emulateMedia({ colorScheme: "dark" });
    await expect(html(page)).toHaveAttribute("data-theme", "dark");

    await page.emulateMedia({ colorScheme: "light" });
    await expect(html(page)).toHaveAttribute("data-theme", "light");
  });

  test("explicit Light/Dark overrides ignore subsequent OS scheme changes", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "light" });
    await page.goto(APPEARANCE_URL);
    await expect(page.locator(".vault-shell")).toBeVisible();

    const lightRadio = page.locator('input[name="theme-preference"][value="light"]');
    await waitForHydration(lightRadio);
    await lightRadio.check();
    await expect(html(page)).toHaveAttribute("data-theme", "light");

    await page.emulateMedia({ colorScheme: "dark" });
    await page.waitForTimeout(250); // give a (wrongly) live-updating listener a chance to fire
    await expect(html(page)).toHaveAttribute("data-theme", "light");

    await page.locator('input[name="theme-preference"][value="dark"]').check();
    await expect(html(page)).toHaveAttribute("data-theme", "dark");

    await page.emulateMedia({ colorScheme: "light" });
    await page.waitForTimeout(250);
    await expect(html(page)).toHaveAttribute("data-theme", "dark");
  });
});

test.describe("pre-paint application", () => {
  test("data-theme/.dark/color-scheme are applied before the app-mounted marker appears", async ({
    page,
    request,
  }) => {
    await page.emulateMedia({ colorScheme: "dark" });

    // Structural proof: this is a server-rendered (TanStack Start SSR) page,
    // so the app-mounted markup is already present in the raw HTML — a
    // runtime "did .vault-shell exist yet" race is not meaningful here. What
    // actually proves "before first paint, not a post-mount effect" is that
    // the theme bootstrap is a *synchronous* inline <script> placed in
    // <head>, strictly before <body> in the document source. Browsers
    // execute a blocking, non-deferred head script before parsing (and
    // therefore painting) any body content, so its source position — not
    // its runtime race against React — is what guarantees pre-paint timing
    // regardless of how fast or slow hydration happens to be.
    const response = await request.get(APPEARANCE_URL);
    const rawHtml = await response.text();
    const bootstrapScriptIndex = rawHtml.indexOf("data-theme");
    const bodyIndex = rawHtml.indexOf("<body");
    expect(bootstrapScriptIndex).toBeGreaterThan(-1);
    expect(bodyIndex).toBeGreaterThan(-1);
    expect(bootstrapScriptIndex).toBeLessThan(bodyIndex);

    // Runtime proof: the resolved theme is already correct at
    // DOMContentLoaded (i.e. once that synchronous head script has run),
    // not just eventually once React mounts and an effect runs.
    await page.goto(APPEARANCE_URL, { waitUntil: "domcontentloaded" });
    const themeAtParse = await page.evaluate(() => ({
      theme: document.documentElement.getAttribute("data-theme"),
      dark: document.documentElement.classList.contains("dark"),
      colorScheme: document.documentElement.style.colorScheme,
    }));
    expect(themeAtParse.theme).toBe("dark");
    expect(themeAtParse.dark).toBe(true);
    expect(themeAtParse.colorScheme).toBe("dark");

    await expect(page.locator(".vault-shell")).toBeVisible();
    // Theme must not have changed once the app actually mounted.
    await expect(html(page)).toHaveAttribute("data-theme", "dark");
  });
});

test.describe("multi-window synchronization", () => {
  // The main-process broadcast itself (one setPreference() call reaching
  // every open BrowserWindow) is unit-tested end-to-end in
  // electron/theme.test.cjs ("an OS change while System is active updates
  // every open window identically", "createThemeController setPreference
  // persists, validates, and broadcasts"). What that suite cannot exercise
  // is two real renderer documents; this test simulates the contextBridge
  // delivering an identical snapshot to two independent Playwright browser
  // contexts (standing in for two BrowserWindows) and proves the renderer
  // runtime in each applies it identically and independently.
  test("two window contexts receive and apply the same broadcast identically", async ({
    browser,
  }) => {
    const contextA = await browser.newContext();
    const contextB = await browser.newContext();
    try {
      const pageA = await contextA.newPage();
      const pageB = await contextB.newPage();
      await installBaseRoutes(pageA);
      await installBaseRoutes(pageB);

      for (const page of [pageA, pageB]) {
        await page.addInitScript(() => {
          const listeners = new Set<(snapshot: unknown) => void>();
          (window as unknown as { __cmlThemeListeners: typeof listeners }).__cmlThemeListeners =
            listeners;
          Object.defineProperty(window, "cmlDesktop", {
            configurable: true,
            value: {
              initialTheme: { preference: "system", resolved: "light" },
              getTheme: async () => ({ preference: "system", resolved: "light" }),
              setTheme: async (preference: string) => {
                const resolved = preference === "dark" ? "dark" : preference === "light" ? "light" : "light";
                return { preference, resolved };
              },
              onThemeChanged: (listener: (snapshot: unknown) => void) => {
                listeners.add(listener);
                return () => listeners.delete(listener);
              },
            },
          });
        });
      }

      await pageA.goto(APPEARANCE_URL);
      await pageB.goto(APPEARANCE_URL);
      await expect(pageA.locator(".vault-shell")).toBeVisible();
      await expect(pageB.locator(".vault-shell")).toBeVisible();
      await expect(html(pageA)).toHaveAttribute("data-theme", "light");
      await expect(html(pageB)).toHaveAttribute("data-theme", "light");

      // This is server-rendered content, so ".vault-shell" is already in the
      // DOM before hydration. initializeTheme() (and therefore the
      // onThemeChanged subscription below) only runs from a post-hydration
      // React effect, so wait for that subscription to actually exist
      // before simulating the broadcast — otherwise it fires into an empty
      // listener set.
      for (const page of [pageA, pageB]) {
        await expect
          .poll(() =>
            page.evaluate(
              () =>
                (window as unknown as { __cmlThemeListeners?: Set<unknown> }).__cmlThemeListeners
                  ?.size ?? 0,
            ),
          )
          .toBeGreaterThan(0);
      }

      // Simulate the main process's single controller broadcasting the same
      // new snapshot to every window's preload-installed listener set.
      const broadcastSnapshot = { preference: "dark", resolved: "dark" };
      for (const page of [pageA, pageB]) {
        await page.evaluate((snapshot) => {
          const listeners = (window as unknown as { __cmlThemeListeners: Set<(s: unknown) => void> })
            .__cmlThemeListeners;
          for (const listener of listeners) listener(snapshot);
        }, broadcastSnapshot);
      }

      await expect(html(pageA)).toHaveAttribute("data-theme", "dark");
      await expect(html(pageB)).toHaveAttribute("data-theme", "dark");
      await expect(html(pageA)).toHaveClass(/dark/);
      await expect(html(pageB)).toHaveClass(/dark/);
    } finally {
      await contextA.close();
      await contextB.close();
    }
  });
});
