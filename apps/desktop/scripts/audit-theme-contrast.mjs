#!/usr/bin/env node
// Static regression gate for Phase 0 (THEME-08): reads the machine-readable
// `--cx-<name>-fg/-bg/-min` contrast-pair registry from src/styles.css
// (established in Plan 00-02), resolves each pair's actual computed color
// per theme by walking the var() alias chain down to a literal primitive,
// and fails if any pair's WCAG 2.2 contrast ratio falls below its declared
// minimum (4.5:1 normal text, 3:1 large text/non-text controls/focus).
//
// This deliberately does not hand-copy ratios: the registry only stores
// which semantic tokens to compare and the required threshold, so this
// script always measures the *current* palette, catching any future color
// edit that regresses contrast without anyone updating a hardcoded ratio.

import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const desktopRoot = path.resolve(__dirname, "..");
const stylesCssPath = path.join(desktopRoot, "src", "styles.css");

function extractBlock(css, openBraceIndex) {
  let depth = 0;
  let i = openBraceIndex;
  for (; i < css.length; i += 1) {
    if (css[i] === "{") depth += 1;
    else if (css[i] === "}") {
      depth -= 1;
      if (depth === 0) break;
    }
  }
  if (depth !== 0) {
    throw new Error("Unbalanced braces while extracting a CSS rule block");
  }
  return css.slice(openBraceIndex + 1, i);
}

function parseDeclarations(block) {
  const declarations = {};
  const re = /--([a-zA-Z0-9-]+)\s*:\s*([^;]+);/g;
  let match;
  while ((match = re.exec(block)) !== null) {
    declarations[match[1]] = match[2].trim();
  }
  return declarations;
}

function loadThemeMaps(css) {
  const lightMarker = "\n:root {\n";
  const lightMarkerIndex = css.indexOf(lightMarker);
  if (lightMarkerIndex === -1) {
    throw new Error("Could not locate the light `:root { ... }` block in styles.css");
  }
  const lightOpenBrace = css.indexOf("{", lightMarkerIndex);
  const lightBlock = extractBlock(css, lightOpenBrace);
  const lightMap = parseDeclarations(lightBlock);

  const darkSelector = ':root[data-theme="dark"] {';
  const darkSelectorIndex = css.indexOf(darkSelector);
  if (darkSelectorIndex === -1) {
    throw new Error('Could not locate the `:root.dark, :root[data-theme="dark"] { ... }` block in styles.css');
  }
  const darkOpenBrace = darkSelectorIndex + darkSelector.length - 1;
  const darkBlock = extractBlock(css, darkOpenBrace);
  const darkOverrides = parseDeclarations(darkBlock);

  return {
    light: lightMap,
    dark: { ...lightMap, ...darkOverrides },
  };
}

function resolveValue(raw, map, seen = new Set()) {
  const trimmed = raw.trim();
  const varMatch = /^var\(\s*--([a-zA-Z0-9-]+)\s*(?:,\s*(.+))?\)$/.exec(trimmed);
  if (!varMatch) return trimmed;

  const refName = varMatch[1];
  if (seen.has(refName)) {
    throw new Error(`Circular var() reference detected while resolving --${refName}`);
  }
  const refRaw = map[refName];
  if (refRaw === undefined) {
    if (varMatch[2]) return varMatch[2].trim();
    throw new Error(`Unresolved custom property --${refName} referenced by var(--${refName})`);
  }
  return resolveValue(refRaw, map, new Set(seen).add(refName));
}

function parseColor(value) {
  const hexMatch = /^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$/.exec(value);
  if (hexMatch) {
    let hex = hexMatch[1];
    if (hex.length === 3) {
      hex = hex
        .split("")
        .map((c) => c + c)
        .join("");
    }
    return {
      r: parseInt(hex.slice(0, 2), 16),
      g: parseInt(hex.slice(2, 4), 16),
      b: parseInt(hex.slice(4, 6), 16),
    };
  }

  const rgbMatch = /^rgba?\(([^)]+)\)$/.exec(value);
  if (rgbMatch) {
    const parts = rgbMatch[1]
      .split(/[\s,/]+/)
      .filter(Boolean)
      .map(Number);
    return { r: parts[0], g: parts[1], b: parts[2] };
  }

  throw new Error(`Cannot parse color value: "${value}"`);
}

function relativeLuminance({ r, g, b }) {
  const toLinear = (channel) => {
    const s = channel / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  const [rl, gl, bl] = [r, g, b].map(toLinear);
  return 0.2126 * rl + 0.7152 * gl + 0.0722 * bl;
}

function contrastRatio(colorA, colorB) {
  const lumA = relativeLuminance(colorA);
  const lumB = relativeLuminance(colorB);
  const lighter = Math.max(lumA, lumB);
  const darker = Math.min(lumA, lumB);
  return (lighter + 0.05) / (darker + 0.05);
}

function collectContrastPairs(lightMap) {
  const pairs = new Map();
  const re = /^cx-(.+)-(fg|bg|min)$/;
  for (const name of Object.keys(lightMap)) {
    const match = re.exec(name);
    if (!match) continue;
    const [, baseName, part] = match;
    if (!pairs.has(baseName)) pairs.set(baseName, {});
    pairs.get(baseName)[part] = lightMap[name];
  }
  return pairs;
}

function main() {
  const css = readFileSync(stylesCssPath, "utf8").replace(/\r\n/g, "\n");
  const { light, dark } = loadThemeMaps(css);
  const pairs = collectContrastPairs(light);

  if (pairs.size === 0) {
    console.error("FAIL: no --cx-*-fg/-bg/-min contrast pairs found in styles.css");
    process.exit(1);
  }

  let failures = 0;
  const rows = [];

  for (const [name, { fg, bg, min }] of pairs) {
    if (!fg || !bg || !min) {
      console.error(`FAIL: contrast pair "${name}" is missing one of fg/bg/min`);
      failures += 1;
      continue;
    }
    const minRatio = Number(min);

    for (const [themeName, map] of [
      ["light", light],
      ["dark", dark],
    ]) {
      let ratio;
      let fgColor;
      let bgColor;
      try {
        fgColor = parseColor(resolveValue(fg, map));
        bgColor = parseColor(resolveValue(bg, map));
        ratio = contrastRatio(fgColor, bgColor);
      } catch (error) {
        console.error(`FAIL: ${name} (${themeName}): ${error.message}`);
        failures += 1;
        continue;
      }

      const pass = ratio >= minRatio - 0.005;
      rows.push({ name, theme: themeName, ratio, min: minRatio, pass });
      if (!pass) {
        console.error(
          `FAIL: --cx-${name} (${themeName}) — ${ratio.toFixed(2)}:1 is below the required ${minRatio}:1`,
        );
        failures += 1;
      }
    }
  }

  console.log(`\nContrast Pair Registry — ${pairs.size} pairs x 2 themes = ${rows.length} checks\n`);
  console.log("name".padEnd(24) + "theme".padEnd(8) + "ratio".padEnd(10) + "min".padEnd(6) + "result");
  for (const row of rows) {
    console.log(
      row.name.padEnd(24) +
        row.theme.padEnd(8) +
        `${row.ratio.toFixed(2)}:1`.padEnd(10) +
        `${row.min}:1`.padEnd(6) +
        (row.pass ? "pass" : "FAIL"),
    );
  }

  if (failures > 0) {
    console.error(`\naudit-theme-contrast: ${failures} failure(s).`);
    process.exit(1);
  } else {
    console.log("\naudit-theme-contrast: all pairs pass their declared threshold in both themes.");
  }
}

main();
