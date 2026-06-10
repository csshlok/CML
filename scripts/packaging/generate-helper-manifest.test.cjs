const test = require("node:test");
const assert = require("node:assert/strict");

const { shouldIncludeRuntimeBinary } = require("./generate-helper-manifest.cjs");

test("runtime helper manifest includes startup-critical runtime binaries", () => {
  assert.equal(shouldIncludeRuntimeBinary("expert-python-runtime", "expert-python-runtime/python.exe"), true);
  assert.equal(shouldIncludeRuntimeBinary("expert-python-runtime", "expert-python-runtime/Lib/site-packages/torch/_C.cp314-win_amd64.pyd"), true);
  assert.equal(shouldIncludeRuntimeBinary("expert-python-runtime", "expert-python-runtime/Lib/site-packages/torch/lib/torch_cpu.dll"), true);
});

test("runtime helper manifest excludes non-startup console launcher stubs under site-packages", () => {
  assert.equal(
    shouldIncludeRuntimeBinary(
      "expert-python-runtime",
      "expert-python-runtime/Lib/site-packages/pip/_vendor/distlib/t64-arm.exe",
    ),
    false,
  );
  assert.equal(
    shouldIncludeRuntimeBinary(
      "expert-python-runtime",
      "expert-python-runtime/Lib/site-packages/setuptools/cli-arm64.exe",
    ),
    false,
  );
  assert.equal(
    shouldIncludeRuntimeBinary(
      "expert-python-runtime",
      "expert-python-runtime/Lib/site-packages/torch/bin/protoc.exe",
    ),
    false,
  );
});
