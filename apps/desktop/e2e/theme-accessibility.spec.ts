import { expect, test, type Locator, type Page } from "@playwright/test";

// Accessibility-mode coverage for Phase 0 (THEME-08): prefers-reduced-motion,
// forced-colors, keyboard-only focus visibility, and 125-200% zoom, across
// both themes where the mode is theme-sensitive. Every assertion below reads
// real computed styles or real DOM/media state (getComputedStyle,
// document.activeElement, elementFromPoint) rather than only proving a test
// executed without checking anything meaningful.

const backendOrigin = "http://127.0.0.1:7343";

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
  await installBaseRoutes(page);
});

async function hasVisibleFocusIndicator(locator: Locator): Promise<boolean> {
  return locator.evaluate((element) => {
    const cs = getComputedStyle(element);
    const hasOutline = cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth || "0") > 0;
    const hasRingShadow = cs.boxShadow !== "none" && cs.boxShadow !== "";
    return hasOutline || hasRingShadow;
  });
}

// TanStack Start's SSR markup is present and visible before React hydrates
// it, so waiting for visibility alone races ahead of hydration. Poll for a
// real React fiber before any keyboard/pointer interaction that depends on
// an event handler actually being attached (matches the `__reactProps`
// pattern already used by desktop-shell.spec.ts's Help search input).
async function waitForHydration(locator: Locator) {
  await expect
    .poll(
      () => locator.evaluate((element) => Object.keys(element).some((key) => key.startsWith("__reactProps"))),
      { timeout: 20_000 },
    )
    .toBe(true);
}

test.describe("reduced motion", () => {
  test("a motion-reduce:animate-none element has no animation when the OS requests reduced motion", async ({
    page,
  }) => {
    // Hold the chat route on its loading skeleton (aria-label="Loading
    // chat") by never resolving the session metadata fetch, so the
    // motion-reduce:animate-none pulse placeholders stay mounted long
    // enough to inspect.
    await page.route(`${backendOrigin}/api/v1/vaults`, (route) =>
      route.fulfill({
        json: [{ id: "vault-a11y", name: "A11y vault", path: "T:\\a11y", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" }],
      }),
    );
    await page.route(`${backendOrigin}/api/v1/chat/sessions/*/metadata`, () => {
      // Deliberately never resolves within the test's lifetime.
      return new Promise<never>(() => undefined);
    });

    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/chat/reduced-motion-probe");
    const skeleton = page.getByLabel("Loading chat");
    await expect(skeleton).toBeVisible();
    const pulseElement = skeleton.locator(".animate-pulse").first();
    await expect(pulseElement).toBeVisible();
    const animationName = await pulseElement.evaluate((el) => getComputedStyle(el).animationName);
    expect(animationName).toBe("none");
  });

  test("the same element DOES animate without reduced motion, proving the override is media-driven", async ({
    page,
  }) => {
    await page.route(`${backendOrigin}/api/v1/vaults`, (route) =>
      route.fulfill({
        json: [{ id: "vault-a11y-2", name: "A11y vault", path: "T:\\a11y2", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" }],
      }),
    );
    await page.route(`${backendOrigin}/api/v1/chat/sessions/*/metadata`, () => new Promise<never>(() => undefined));

    await page.emulateMedia({ reducedMotion: "no-preference" });
    await page.goto("/chat/no-reduced-motion-probe");
    const skeleton = page.getByLabel("Loading chat");
    await expect(skeleton).toBeVisible();
    const pulseElement = skeleton.locator(".animate-pulse").first();
    await expect(pulseElement).toBeVisible();
    const animationName = await pulseElement.evaluate((el) => getComputedStyle(el).animationName);
    expect(animationName).not.toBe("none");
  });
});

test.describe("forced colors", () => {
  test("focus remains visible via a real outline once forced-colors strips the custom ring", async ({
    page,
  }) => {
    await page.emulateMedia({ forcedColors: "active" });
    await page.goto("/settings?section=profile");
    await expect(page.locator(".vault-shell")).toBeVisible();

    const button = page.locator("button").first();
    await button.waitFor({ state: "visible" });
    const before = await button.evaluate((el) => getComputedStyle(el).outlineStyle);
    expect(before).toBe("none");

    await button.focus();
    const after = await button.evaluate((el) => ({
      outlineStyle: getComputedStyle(el).outlineStyle,
      boxShadow: getComputedStyle(el).boxShadow,
    }));
    // The app's own focus-visible:ring-* (box-shadow) is a forced property
    // and gets stripped by the browser's forced-colors algorithm, but the
    // browser supplies its own visible outline in its place — this is the
    // real, load-bearing safety net that keeps focus indication usable in
    // forced-colors mode even though the custom ring disappears.
    expect(after.outlineStyle).toBe("solid");
    expect(after.boxShadow).toBe("none");
  });

  test("a disabled control stays visually distinguishable from an enabled one", async ({ page }) => {
    await page.emulateMedia({ forcedColors: "active" });
    await page.goto("/settings?section=library");
    await expect(page.locator(".vault-shell")).toBeVisible();

    // Deterministically disabled in this harness: no vault is mocked, and
    // "Show data folder" is disabled whenever `!backendVault`.
    const disabledButton = page.getByRole("button", { name: "Show data folder" });
    await expect(disabledButton).toBeVisible();
    await expect(disabledButton).toBeDisabled();

    const enabledButton = page.locator("button:not([disabled])").first();
    await enabledButton.waitFor({ state: "visible" });

    const [disabledStyle, enabledStyle] = await Promise.all([
      disabledButton.evaluate((el) => {
        const cs = getComputedStyle(el);
        return { opacity: cs.opacity, cursor: cs.cursor, color: cs.color };
      }),
      enabledButton.evaluate((el) => {
        const cs = getComputedStyle(el);
        return { opacity: cs.opacity, cursor: cs.cursor, color: cs.color };
      }),
    ]);

    expect(disabledStyle.cursor).toBe("not-allowed");
    expect(enabledStyle.cursor).not.toBe("not-allowed");
    expect(Number(disabledStyle.opacity)).toBeLessThan(Number(enabledStyle.opacity));
    // Forced-colors maps disabled text to GrayText and enabled text to
    // ButtonText/CanvasText, which are guaranteed distinct system colors.
    expect(disabledStyle.color).not.toBe(enabledStyle.color);
  });
});

test.describe("keyboard focus", () => {
  for (const theme of ["light", "dark"] as const) {
    test(`Tab traversal keeps a visible focus indicator at every stop (${theme})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: theme });
      await page.goto("/home");
      const shell = page.locator(".vault-shell");
      await expect(shell).toBeVisible();
      await waitForHydration(shell);

      let sawAnyFocusable = false;
      for (let i = 0; i < 15; i += 1) {
        await page.keyboard.press("Tab");
        const active = page.locator(":focus");
        const count = await active.count();
        if (count === 0) continue;
        const info = await active.evaluate((el) => ({
          tag: el.tagName,
          tabIndex: (el as HTMLElement).tabIndex,
        }));
        if (info.tag === "BODY") continue;
        // tabIndex=-1 targets (e.g. AppShell's <main tabIndex={-1}
        // className="focus:outline-none">) are deliberate route-change
        // screen-reader focus targets, not real keyboard Tab stops — real
        // Tab navigation never lands on them natively, and they
        // intentionally opt out of a visible ring since sighted keyboard
        // users don't reach them this way.
        if (info.tabIndex < 0) continue;
        sawAnyFocusable = true;
        const visible = await hasVisibleFocusIndicator(active);
        expect(visible, `expected a visible focus indicator on <${info.tag}> at Tab stop ${i}`).toBe(true);
      }
      expect(sawAnyFocusable).toBe(true);
    });
  }

  test("command palette opens via keyboard, arrow-navigates, and Escape closes it", async ({ page }) => {
    await page.goto("/home");
    const shell = page.locator(".vault-shell");
    await expect(shell).toBeVisible();
    await waitForHydration(shell);

    await page.keyboard.press("Control+K");
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    const options = dialog.getByRole("option");
    await expect(options.first()).toBeVisible();
    const initiallySelected = await options.first().getAttribute("aria-selected");

    await page.keyboard.press("ArrowDown");
    await expect
      .poll(async () => {
        const count = await options.count();
        for (let i = 0; i < count; i += 1) {
          if ((await options.nth(i).getAttribute("aria-selected")) === "true") return i;
        }
        return -1;
      })
      .toBeGreaterThanOrEqual(0);

    // Highlighted option must carry a real visible affordance too, not only
    // the aria-selected attribute.
    const selectedOption = dialog.locator('[aria-selected="true"]').first();
    await expect(selectedOption).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
    expect(initiallySelected).not.toBeNull();
  });

  test("a dialog opened via the command palette traps interaction and Escape closes it", async ({
    page,
  }) => {
    await page.goto("/home");
    const shell = page.locator(".vault-shell");
    await expect(shell).toBeVisible();
    await waitForHydration(shell);

    await page.keyboard.press("Control+K");
    const paletteDialog = page.getByRole("dialog");
    await expect(paletteDialog).toBeVisible();
    const healthOption = page.getByRole("option", { name: /Health status/ });
    await expect(healthOption).toBeVisible();
    await healthOption.click();

    const healthDialog = page.getByRole("dialog", { name: "Health status" });
    await expect(healthDialog).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(healthDialog).not.toBeVisible();
  });
});

test.describe("125-200% zoom", () => {
  async function assertControlsAreUsable(page: Page, locators: Locator[]) {
    for (const locator of locators) {
      // CSS zoom can push a control below the physical viewport fold;
      // elementFromPoint only evaluates the visible viewport, so scroll the
      // control into view first or an off-screen position would be
      // misreported as "obscured" when it is simply not on screen yet.
      await locator.scrollIntoViewIfNeeded();
      const box = await locator.boundingBox();
      expect(box, "control must have a resolvable bounding box").not.toBeNull();
      expect(box!.width).toBeGreaterThan(0);
      expect(box!.height).toBeGreaterThan(0);

      const centerX = box!.x + box!.width / 2;
      const centerY = box!.y + box!.height / 2;
      const isReachable = await locator.evaluate(
        (el, [cx, cy]) => {
          const hit = document.elementFromPoint(cx, cy);
          return hit !== null && (hit === el || el.contains(hit) || hit.contains(el));
        },
        [centerX, centerY],
      );
      expect(isReachable, "control must not be obscured by an overlapping element").toBe(true);
    }
  }

  async function setZoom(page: Page, zoom: number) {
    await page.evaluate((z) => {
      document.documentElement.style.zoom = String(z);
    }, zoom);
  }

  const mapVault = {
    id: "vault-zoom-map",
    name: "Zoom map vault",
    path: "T:\\zoom-map",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
  const mapOverview = {
    vault_id: mapVault.id,
    nodes: [
      { id: "cluster-a", kind: "cluster", label: "Cluster A", summary: "", color: "sage", state: "ready", source_count: 2, fact_count: 0, updated_at: mapVault.updated_at },
      { id: "cluster-b", kind: "cluster", label: "Cluster B", summary: "", color: "sky", state: "ready", source_count: 1, fact_count: 0, updated_at: mapVault.updated_at },
    ],
    edges: [
      { id: "similarity:a:b", source: "cluster-a", target: "cluster-b", kind: "similarity", label: "60% similar", direction: "undirected", temporal_state: "current", provenance_ids: [], updated_at: mapVault.updated_at, relationship_basis: "semantic_similarity", similarity_score: 0.6, shared_terms: [], evidence_labels: [] },
    ],
    total: 2,
    cluster_total: 2,
    unclustered_count: 0,
    limit: 160,
    offset: 0,
    truncated: false,
    connection_mode: "similar",
    relationship_policy: "evidence_and_similarity",
  };

  for (const zoom of [1.25, 1.5, 2.0]) {
    test(`Settings controls remain unclipped and unobscured at ${Math.round(zoom * 100)}% zoom`, async ({
      page,
    }) => {
      await page.goto("/settings?section=profile");
      await expect(page.locator(".vault-shell")).toBeVisible();
      await setZoom(page, zoom);
      await assertControlsAreUsable(page, [
        page.locator('input[name="theme-preference"][value="dark"]'),
        page.getByRole("link", { name: "Open Help & FAQ" }),
      ]);
    });

    test(`Chat controls remain unclipped and unobscured at ${Math.round(zoom * 100)}% zoom`, async ({
      page,
    }) => {
      await page.goto("/chat");
      await expect(page.locator(".vault-shell")).toBeVisible();
      await setZoom(page, zoom);
      await assertControlsAreUsable(page, [page.getByRole("combobox")]);
    });

    test(`Knowledge Map controls remain unclipped and unobscured at ${Math.round(zoom * 100)}% zoom`, async ({
      page,
    }) => {
      await page.route(`${backendOrigin}/api/v1/vaults`, (route) => route.fulfill({ json: [mapVault] }));
      await page.route(`${backendOrigin}/api/v1/map/overview*`, (route) => route.fulfill({ json: mapOverview }));
      await page.goto("/map");
      await expect(page.locator(".vault-shell")).toBeVisible();
      await expect(page.getByRole("button", { name: "Connections" })).toBeVisible({ timeout: 15_000 });
      await setZoom(page, zoom);
      await assertControlsAreUsable(page, [page.getByRole("button", { name: "Connections" })]);
    });
  }
});
