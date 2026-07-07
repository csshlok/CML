const test = require("node:test");
const assert = require("node:assert/strict");

const { shouldIncludeRuntimeBinary } = require("./generate-helper-manifest.cjs");

test("runtime helper manifest includes startup-critical runtime binaries", () => {
  assert.equal(shouldIncludeRuntimeBinary("python-runtime", "python-runtime/python.exe"), true);
  assert.equal(shouldIncludeRuntimeBinary("python-runtime", "python-runtime/pythonw.exe"), true);
  assert.equal(shouldIncludeRuntimeBinary("python-runtime", "python-runtime/Lib/site-packages/numpy/_core/_multiarray_umath.cp314-win_amd64.pyd"), true);
});

test("runtime helper manifest excludes non-startup console launcher stubs under site-packages", () => {
  assert.equal(
    shouldIncludeRuntimeBinary(
      "python-runtime",
      "python-runtime/Lib/site-packages/pip/_vendor/distlib/t64-arm.exe",
    ),
    false,
  );
  assert.equal(
    shouldIncludeRuntimeBinary(
      "python-runtime",
      "python-runtime/Lib/site-packages/setuptools/cli-arm64.exe",
    ),
    false,
  );
  assert.equal(
    shouldIncludeRuntimeBinary(
      "python-runtime",
      "python-runtime/Lib/site-packages/numpy/bin/protoc.exe",
    ),
    false,
  );
});
