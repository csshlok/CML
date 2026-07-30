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
  assert.match(progressSource, /import \{ createPortal \} from "react-dom"/);
  assert.match(progressSource, /setPortalRoot\(document\.body\)/);
  assert.match(progressSource, /return createPortal\(/);
  assert.match(progressSource, /data-source-import-popup="true"/);
  assert.match(progressSource, /aria-label="Move file import progress"/);
  assert.match(progressSource, /source-import-drag-handle/);
  assert.match(progressSource, /vault\.source-import-popup\.position\.v1/);
  assert.match(progressSource, /availableWidth/);
  assert.match(progressSource, /localStorage\.setItem/);
  assert.match(progressSource, /window\.addEventListener\("pointermove", moveDragging/);
  assert.match(progressSource, /window\.addEventListener\("pointerup", stopDragging/);
  assert.match(progressSource, /captureTarget\.setPointerCapture/);
  assert.match(progressSource, /data-import-drag-ignore="true"/);
  assert.match(progressSource, /constrainPosition/);
  assert.match(progressSource, /ArrowLeft/);
  assert.match(progressSource, /ResizeObserver/);
  assert.match(styles, /\.source-import-popup\s*\{[^}]*-webkit-app-region:\s*no-drag/s);
  assert.doesNotMatch(
    styles,
    /\.source-import-popup\s*\{[^}]*\bleft\s*:/,
  );
  assert.match(
    styles,
    /\.vault-desktop-content\s*>\s*\*\s*\{[^}]*height:\s*100%/s,
    "the popup must remain portaled because direct route children are forced to full height",
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
