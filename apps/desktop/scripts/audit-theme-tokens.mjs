#!/usr/bin/env node
// Static regression gate for Phase 0 (THEME-08): proves the dark/light
// primitive token contract in src/styles.css still has 1:1 key parity, and
// that no file under src/ or electron/ has reintroduced a raw hex/rgb color
// or a Tailwind default-color utility outside the centralized palette
// definitions (styles.css, static-window-chrome.css, graphPalette.ts,
// error-page.ts) or an explicitly documented exception.
//
// Exception mechanism (matches the locked CONTEXT.md decision: "Literal
// colors are allowed only inside the centralized palette definitions or an
// explicitly documented media-preservation exception"):
//   - A file containing a comment matching /theme-literal-color-allowed:\s*file/i
//     anywhere in it is exempt in its entirety (used by the four palette-
//     definition files above).
//   - A single violating line is exempt if that line OR the line immediately
//     above it contains the substring `theme-literal-color-allowed`.
//
// Scope: renderer and Electron source files under apps/desktop/src and
// apps/desktop/electron. Native APIs and last-resort data: documents still
// need concrete colors, but those values must live in the explicitly exempt
// centralized electron/theme.cjs palette rather than leak into main.cjs.

import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const desktopRoot = path.resolve(__dirname, "..");
const stylesCssPath = path.join(desktopRoot, "src", "styles.css");

let failures = 0;

function fail(message) {
  console.error(`FAIL: ${message}`);
  failures += 1;
}

// ---------------------------------------------------------------------------
// Part 1: dark/light primitive token parity in styles.css
// ---------------------------------------------------------------------------

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

function parseDeclarationsWithComments(block) {
  const lines = block.split("\n");
  const declarations = [];
  let commentBuffer = [];
  let inBlockComment = false;

  for (const rawLine of lines) {
    const line = rawLine.trim();

    if (inBlockComment) {
      commentBuffer.push(line);
      if (line.includes("*/")) inBlockComment = false;
      continue;
    }

    if (line.startsWith("/*")) {
      commentBuffer.push(line);
      if (!line.includes("*/")) inBlockComment = true;
      continue;
    }

    const declMatch = /^--([a-zA-Z0-9-]+)\s*:\s*([^;]+);/.exec(line);
    if (declMatch) {
      declarations.push({
        name: declMatch[1],
        value: declMatch[2].trim(),
        comment: commentBuffer.join(" "),
      });
      // Deliberately not cleared here: a single comment often documents a
      // short run of consecutive declarations (e.g. an "invariant across
      // themes" note above both --close-hover-bg and --close-hover-fg). It
      // is cleared on the next comment or blank line instead.
      continue;
    }

    if (line === "") {
      commentBuffer = [];
    }
  }

  return declarations;
}

function isLiteralColorValue(value) {
  return /^#[0-9A-Fa-f]{3,8}$/.test(value) || /^rgba?\(/i.test(value);
}

function checkTokenParity(css) {
  const lightMarker = "\n:root {\n";
  const lightMarkerIndex = css.indexOf(lightMarker);
  if (lightMarkerIndex === -1) {
    fail("Could not locate the light `:root { ... }` primitive block in styles.css");
    return { lightMap: {}, darkMap: {} };
  }
  const lightOpenBrace = css.indexOf("{", lightMarkerIndex);
  const lightBlock = extractBlock(css, lightOpenBrace);

  const darkSelector = ':root[data-theme="dark"] {';
  const darkSelectorIndex = css.indexOf(darkSelector);
  if (darkSelectorIndex === -1) {
    fail('Could not locate the `:root.dark, :root[data-theme="dark"] { ... }` primitive block in styles.css');
    return { lightMap: {}, darkMap: {} };
  }
  const darkOpenBrace = darkSelectorIndex + darkSelector.length - 1;
  const darkBlock = extractBlock(css, darkOpenBrace);

  const lightDecls = parseDeclarationsWithComments(lightBlock);
  const darkDecls = parseDeclarationsWithComments(darkBlock);

  const lightMap = {};
  for (const decl of lightDecls) lightMap[decl.name] = decl.value;
  const darkMap = { ...lightMap };
  for (const decl of darkDecls) darkMap[decl.name] = decl.value;

  const darkNames = new Set(darkDecls.map((d) => d.name));
  const lightNames = new Set(lightDecls.map((d) => d.name));

  let missingDarkCount = 0;
  for (const decl of lightDecls) {
    if (!isLiteralColorValue(decl.value)) continue; // semantic alias, not a primitive
    if (darkNames.has(decl.name)) continue; // parity holds
    if (/invariant/i.test(decl.comment)) continue; // documented cross-theme invariant
    fail(
      `styles.css: primitive --${decl.name} (light value ${decl.value}) has no dark override in ` +
        '":root.dark, :root[data-theme=\\"dark\\"]" and is not documented as an invariant',
    );
    missingDarkCount += 1;
  }

  let orphanDarkCount = 0;
  for (const decl of darkDecls) {
    if (!lightNames.has(decl.name)) {
      fail(`styles.css: dark-only token --${decl.name} has no light counterpart (likely a typo)`);
      orphanDarkCount += 1;
    }
  }

  if (missingDarkCount === 0 && orphanDarkCount === 0) {
    console.log(
      `PASS: token parity — ${lightDecls.length} light declarations, ${darkDecls.length} dark declarations, 0 parity violations`,
    );
  }

  return { lightMap, darkMap };
}

// ---------------------------------------------------------------------------
// Part 2: literal-color / Tailwind-default-color-utility sweep
// ---------------------------------------------------------------------------

const SCAN_ROOTS = ["src", "electron"];
const SCAN_EXTENSIONS = new Set([".ts", ".tsx", ".js", ".cjs", ".css", ".html"]);
const SKIP_DIR_NAMES = new Set(["node_modules", "dist", "__screenshots__"]);
const SKIP_FILE_NAMES = new Set(["routeTree.gen.ts"]);

const TAILWIND_COLOR_FAMILIES =
  "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose";
const TAILWIND_UTILITY_PREFIXES =
  "bg|text|border|ring|ring-offset|fill|stroke|from|via|to|shadow|outline|decoration|caret|divide|accent|placeholder";

const HEX_COLOR_RE = /#(?:[0-9A-Fa-f]{8}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{4}|[0-9A-Fa-f]{3})\b/g;
const RGB_FUNCTION_RE = /\brgba?\(/gi;
const NAMED_CSS_COLOR_DECLARATION_RE =
  /\b(?:color|background|background-color|border-color|fill|stroke)\s*:\s*(?:red|blue|green|yellow|black|white|gray|grey|orange|purple|pink|brown|cyan|magenta)\b/gi;
const TAILWIND_SHADED_UTILITY_RE = new RegExp(
  `\\b(?:${TAILWIND_UTILITY_PREFIXES})-(?:${TAILWIND_COLOR_FAMILIES})-[0-9]{2,3}\\b`,
  "g",
);
const TAILWIND_BLACK_WHITE_UTILITY_RE = new RegExp(
  `\\b(?:${TAILWIND_UTILITY_PREFIXES})-(?:white|black)(?:/[0-9]{1,3})?\\b`,
  "g",
);

const WHOLE_FILE_EXEMPT_RE = /theme-literal-color-allowed:\s*file\b/i;
const LINE_EXEMPT_MARKER = "theme-literal-color-allowed";
const EXEMPTION_LOOKBACK_LINES = 6;

function findLineViolations(line) {
  const matches = [];
  for (const re of [
    HEX_COLOR_RE,
    RGB_FUNCTION_RE,
    NAMED_CSS_COLOR_DECLARATION_RE,
    TAILWIND_SHADED_UTILITY_RE,
    TAILWIND_BLACK_WHITE_UTILITY_RE,
  ]) {
    re.lastIndex = 0;
    let match;
    while ((match = re.exec(line)) !== null) {
      matches.push(match[0]);
    }
  }
  return matches;
}

function walk(dir, files) {
  let entries;
  try {
    entries = readdirSync(dir);
  } catch {
    return;
  }
  for (const entry of entries) {
    if (SKIP_DIR_NAMES.has(entry) || SKIP_FILE_NAMES.has(entry)) continue;
    const full = path.join(dir, entry);
    const stats = statSync(full);
    if (stats.isDirectory()) {
      walk(full, files);
    } else if (SCAN_EXTENSIONS.has(path.extname(entry))) {
      files.push(full);
    }
  }
}

function sweepLiteralColors() {
  const files = [];
  for (const root of SCAN_ROOTS) {
    walk(path.join(desktopRoot, root), files);
  }

  let violationCount = 0;
  let scannedCount = 0;
  let exemptFileCount = 0;

  for (const file of files) {
    const relPath = path.relative(desktopRoot, file).split(path.sep).join("/");
    const content = readFileSync(file, "utf8").replace(/\r\n/g, "\n");

    if (WHOLE_FILE_EXEMPT_RE.test(content)) {
      exemptFileCount += 1;
      continue;
    }

    scannedCount += 1;
    const lines = content.split("\n");
    for (let i = 0; i < lines.length; i += 1) {
      const line = lines[i];
      const matches = findLineViolations(line);
      if (matches.length === 0) continue;

      // Look back a few lines so a multi-line comment (or an attribute
      // line separated from its wrapping tag) can still carry the marker
      // for the violation it documents.
      const lookbackStart = Math.max(0, i - EXEMPTION_LOOKBACK_LINES);
      const nearbyExempt = lines
        .slice(lookbackStart, i + 1)
        .some((candidate) => candidate.includes(LINE_EXEMPT_MARKER));
      if (nearbyExempt) continue;

      for (const matched of matches) {
        fail(`${relPath}:${i + 1}: literal/un-themed color "${matched}" — ${line.trim()}`);
        violationCount += 1;
      }
    }
  }

  if (violationCount === 0) {
    console.log(
      `PASS: literal-color sweep — ${scannedCount} files scanned, ${exemptFileCount} centralized-palette files exempted, 0 violations`,
    );
  }
}

// ---------------------------------------------------------------------------

const css = readFileSync(stylesCssPath, "utf8").replace(/\r\n/g, "\n");
checkTokenParity(css);
sweepLiteralColors();

if (failures > 0) {
  console.error(`\naudit-theme-tokens: ${failures} failure(s).`);
  process.exit(1);
} else {
  console.log("\naudit-theme-tokens: all checks passed.");
}
