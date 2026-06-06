import fs from "node:fs";
import path from "node:path";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

const repoRoot = process.cwd();
const scanRoots = [
  path.join(repoRoot, "apps", "desktop", "src"),
  path.join(repoRoot, "apps", "desktop", "electron"),
];
const allowedDangerousHtml = new Set([
  path.normalize(path.join("apps", "desktop", "src", "components", "ui", "chart.tsx")),
]);
const bannedPatterns = [
  { name: "direct innerHTML assignment", pattern: /\.innerHTML\s*=/ },
  { name: "direct outerHTML assignment", pattern: /\.outerHTML\s*=/ },
  { name: "insertAdjacentHTML", pattern: /\.insertAdjacentHTML\s*\(/ },
  { name: "document.write", pattern: /\bdocument\.write\s*\(/ },
  { name: "HTML parser construction", pattern: /\bnew\s+DOMParser\s*\(/ },
];

const findings = [];
for (const filePath of walk(scanRoots)) {
  const relative = path.normalize(path.relative(repoRoot, filePath));
  const text = fs.readFileSync(filePath, "utf8");
  if (text.includes("dangerouslySetInnerHTML") && !allowedDangerousHtml.has(relative)) {
    findings.push(`${relative}: dangerouslySetInnerHTML is not allowlisted`);
  }
  for (const banned of bannedPatterns) {
    if (banned.pattern.test(text)) {
      findings.push(`${relative}: ${banned.name} is forbidden for renderer safety`);
    }
  }
}

const chartPath = path.join(repoRoot, "apps", "desktop", "src", "components", "ui", "chart.tsx");
const chartText = fs.readFileSync(chartPath, "utf8");
if (!chartText.includes("isSafeCssColor") || !chartText.includes("cssIdentifier")) {
  findings.push("apps/desktop/src/components/ui/chart.tsx: allowlisted style injection must keep CSS value and selector sanitizers");
}

verifyHostileFixtureRendering(findings);

if (findings.length > 0) {
  console.error("Renderer HTML safety audit failed:");
  for (const finding of findings) {
    console.error(`- ${finding}`);
  }
  process.exit(1);
}

console.log("Renderer HTML safety audit passed.");

function* walk(roots) {
  for (const root of roots) {
    if (!fs.existsSync(root)) continue;
    yield* walkOne(root);
  }
}

function* walkOne(current) {
  const stat = fs.statSync(current);
  if (stat.isDirectory()) {
    const base = path.basename(current);
    if (["node_modules", "dist", "release", "packaging"].includes(base)) return;
    for (const entry of fs.readdirSync(current)) {
      yield* walkOne(path.join(current, entry));
    }
    return;
  }
  if (/\.(cjs|js|jsx|mjs|ts|tsx)$/.test(current)) {
    yield current;
  }
}

function verifyHostileFixtureRendering(outputFindings) {
  const hostileStrings = [
    `<script>window.__cml_xss = true</script>`,
    `<img src=x onerror="window.__cml_xss = true">`,
    `<button onclick="window.__cml_xss = true">Install update</button>`,
    `[safe link](javascript:window.__cml_xss=true)`,
  ];
  const html = renderToStaticMarkup(
    React.createElement(
      "section",
      null,
      hostileStrings.map((value, index) =>
        React.createElement(
          "p",
          { key: index, className: "whitespace-pre-wrap" },
          value,
        ),
      ),
    ),
  );

  if (/<(?:script|img|button)\b/i.test(html) || /\shref=["']javascript:/i.test(html)) {
    outputFindings.push("hostile model/document fixture rendered as executable HTML instead of escaped text");
  }
  if (!html.includes("&lt;script&gt;") || !html.includes("&lt;button")) {
    outputFindings.push("hostile model/document fixture did not preserve escaped visible text");
  }
}
