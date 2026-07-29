const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const progressSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "components", "product", "SourceImportProgress.tsx"),
  "utf8",
);
const sourcesRoute = fs.readFileSync(
  path.join(__dirname, "..", "src", "routes", "_app.sources.tsx"),
  "utf8",
);
const appRoute = fs.readFileSync(
  path.join(__dirname, "..", "src", "routes", "_app.tsx"),
  "utf8",
);
const styles = fs.readFileSync(
  path.join(__dirname, "..", "src", "styles.css"),
  "utf8",
);

test("file import progress persists above app routes with counts and percentage", () => {
  assert.match(appRoute, /<SourceImportProvider>/);
  assert.match(progressSource, /getActiveSourceImportJob/);
  assert.match(progressSource, /getJob\(job\.id\)/);
  assert.match(
    progressSource,
    /progress\.completed_files\.toLocaleString\(\).*progress\.total_files\.toLocaleString\(\).*percent/s,
  );
  assert.match(progressSource, /aria-label=\{`\$\{percent\}% of files processed`\}/);
  assert.match(progressSource, /aria-label="Dismiss file import progress"/);
  assert.match(progressSource, /fixed bottom-4 right-4/);
  assert.match(progressSource, /aria-label="Move file import progress"/);
  assert.match(progressSource, /setPointerCapture\(event\.pointerId\)/);
  assert.match(progressSource, /constrainPosition/);
  assert.match(progressSource, /ArrowLeft/);
  assert.match(progressSource, /ResizeObserver/);
  assert.doesNotMatch(
    styles,
    /\.source-import-popup\s*\{[^}]*\bleft\s*:/,
  );
});

test("file imports use durable jobs with pause, resume, and confirmed stop", () => {
  assert.match(sourcesRoute, /sourceImport\.start\(\{/);
  assert.doesNotMatch(sourcesRoute, /createSourceFromPath/);
  assert.match(progressSource, /pauseSourceImportJob/);
  assert.match(progressSource, /resumeSourceImportJob/);
  assert.match(progressSource, /stopSourceImportJob/);
  assert.match(progressSource, /title="Stop importing files\?"/);
  assert.match(
    progressSource,
    /Files already being processed may finish and stay in your library\./,
  );
});

test("source details consume no default width and open with reduced-motion support", () => {
  assert.match(sourcesRoute, /data-inspector-open=\{Boolean\(inspectorSource\)\}/);
  assert.match(sourcesRoute, /\{inspectorSource \? \(\s*<SourceInspector/s);
  assert.match(sourcesRoute, /aria-label="Close source details"/);
  assert.doesNotMatch(sourcesRoute, /Select a source to inspect it\./);
  assert.match(styles, /\.sources-layout \{\s*grid-template-columns: minmax\(0, 1fr\) 0;/);
  assert.match(
    styles,
    /\.sources-layout\[data-inspector-open="true"\] \{\s*grid-template-columns: minmax\(0, 1fr\) 326px;/,
  );
  assert.match(styles, /\.source-inspector[\s\S]*animation: source-inspector-enter/);
  assert.match(styles, /\.sources-layout \{\s*transition: none;/);
});
