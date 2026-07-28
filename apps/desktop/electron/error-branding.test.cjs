const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const desktopRoot = path.join(__dirname, "..");

function readDesktopFile(...parts) {
  return fs.readFileSync(path.join(desktopRoot, ...parts), "utf8");
}

test("dedicated error pages use the opening-library wordmark", () => {
  const rootRoute = readDesktopFile("src", "routes", "__root.tsx");
  const serverErrorPage = readDesktopFile("src", "lib", "error-page.ts");
  const repairPage = readDesktopFile("electron", "repair.html");

  assert.match(rootRoute, /<BrandLogo/);
  assert.match(rootRoute, /href:\s*VAULT_OPENING_WORDMARK/);
  assert.match(serverErrorPage, /brand\/Container\.svg/);
  assert.match(repairPage, /dist\/client\/brand\/Container\.svg/);
});

test("legacy app branding and embedded startup artwork are removed", () => {
  const brandDirectory = path.join(desktopRoot, "public", "brand");
  const mainSource = readDesktopFile("electron", "main.cjs");
  const brandSource = readDesktopFile("src", "components", "BrandLogo.tsx");

  assert.equal(fs.existsSync(path.join(brandDirectory, "logo.svg")), false);
  assert.doesNotMatch(mainSource, /startupRepairLogoMarkup|data:image\/png;base64/);
  assert.doesNotMatch(brandSource, /brand\/(?:logo\.svg|Frame 8\.png)|variant/);
});

test("error-page copy is concise and keeps technical details out of the primary message", () => {
  const rootRoute = readDesktopFile("src", "routes", "__root.tsx");
  const serverErrorPage = readDesktopFile("src", "lib", "error-page.ts");
  const repairScript = readDesktopFile("electron", "repair.js");
  const repairPage = readDesktopFile("electron", "repair.html");

  for (const source of [rootRoute, serverErrorPage]) {
    assert.match(source, /This page did not open/);
    assert.match(source, /Return home/);
    assert.doesNotMatch(source, /This page didn't load|Go home/);
  }
  assert.doesNotMatch(repairPage, /Startup repair|Renderer repair/);
  assert.match(repairScript, /Vault could not open/);
});
