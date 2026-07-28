const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const { createDroppedFilePathStore } = require("./dropped-files.cjs");

test("external drop paths are captured before the isolated renderer consumes them", () => {
  let dropListener = null;
  let capture = false;
  const target = {
    addEventListener(type, listener, options) {
      assert.equal(type, "drop");
      dropListener = listener;
      capture = options;
    },
  };
  const store = createDroppedFilePathStore(target, (file) => file.nativePath);

  assert.equal(capture, true);
  dropListener({
    dataTransfer: {
      files: [
        { nativePath: "C:\\Documents\\notes.pdf" },
        { nativePath: "C:\\Documents\\journal.txt" },
      ],
    },
  });

  assert.deepEqual(store.consume(), [
    "C:\\Documents\\notes.pdf",
    "C:\\Documents\\journal.txt",
  ]);
  assert.deepEqual(store.consume(), []);
});

test("one unreadable dropped file does not discard the remaining native paths", () => {
  let dropListener = null;
  const target = {
    addEventListener(_type, listener) {
      dropListener = listener;
    },
  };
  const store = createDroppedFilePathStore(target, (file) => {
    if (file.unreadable) throw new Error("not a native Electron File");
    return file.nativePath;
  });

  dropListener({
    dataTransfer: {
      files: [
        { unreadable: true },
        { nativePath: "D:\\Vault imports\\working.md" },
      ],
    },
  });

  assert.deepEqual(store.consume(), ["D:\\Vault imports\\working.md"]);
});

test("the preload captures native files before exposing plain paths to React", () => {
  const preloadSource = fs.readFileSync(
    path.join(__dirname, "preload.cjs"),
    "utf8",
  );

  assert.match(preloadSource, /createDroppedFilePathStore\(window,/);
  assert.match(
    preloadSource,
    /getDroppedFilePaths:\s*\(\)\s*=>\s*droppedFilePaths\.consume\(\)/,
  );
  assert.doesNotMatch(preloadSource, /getDroppedFilePaths:\s*\(files\)/);
});
