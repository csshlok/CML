const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const {
  getLauncherStatus,
  installLauncher,
  launcherContents,
  pathContains,
  registerUserPath,
  runLauncher,
} = require("./odin-launcher.cjs");

test("Odin launcher uses absolute packaged paths and preserves the caller working directory", () => {
  const contents = launcherContents({
    pythonPath: "C:\\Program Files\\CML\\resources\\python-runtime\\python.exe",
    resourcesRoot: "C:\\Program Files\\CML\\resources",
  });
  assert.match(contents, /python-runtime\\python\.exe" -s -m backend\.app\.odin_cli %\*/);
  assert.match(contents, /PYTHONPATH=C:\\Program Files\\CML\\resources/);
  assert.doesNotMatch(contents, /\bcd\b|\bpushd\b|\.venv/);
});

test("Odin launcher installs atomically and detects a launcher that needs repair", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "cml-odin-launcher-"));
  const binDir = path.join(root, "bin");
  const options = {
    binDir,
    pythonPath: path.join(root, "python-runtime", "python.exe"),
    resourcesRoot: root,
  };
  try {
    const installed = await installLauncher({ ...options, registerPath: () => ({ changed: true }) });
    assert.equal(installed.installed, true);
    assert.equal((await getLauncherStatus({ ...options, userPath: binDir })).installed, true);
    await fs.writeFile(installed.launcher_path, "@echo off\r\nbroken\r\n", "utf8");
    const damaged = await getLauncherStatus({ ...options, userPath: binDir });
    assert.equal(damaged.installed, false);
    assert.equal(damaged.needs_repair, true);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test("PATH matching is case-insensitive and does not use prefix matches", () => {
  assert.equal(pathContains("C:\\Tools;C:\\Users\\Me\\CML\\bin", "c:\\users\\me\\cml\\BIN"), true);
  assert.equal(pathContains("C:\\Users\\Me\\CML\\binary", "C:\\Users\\Me\\CML\\bin"), false);
});

test("PATH registration broadcasts the Windows environment change", () => {
  let invocation = null;
  const result = registerUserPath("C:\\Users\\Person\\AppData\\Local\\CML\\bin", (command, args, options) => {
    invocation = { command, args, options };
    return { status: 0, stdout: "", stderr: "" };
  });
  assert.deepEqual(result, { changed: true, supported: true });
  assert.equal(invocation.command, "powershell.exe");
  assert.match(invocation.args.join(" "), /SetEnvironmentVariable/);
  assert.match(invocation.args.join(" "), /SendMessageTimeout/);
  assert.equal(invocation.options.windowsHide, true);
});

test("Odin help probe is bounded and does not invoke a command shell", () => {
  let invocation = null;
  const result = runLauncher("C:\\Users\\Me\\CML\\bin\\odin.cmd", ["--help"], {
    cwd: "C:\\work",
    runner(command, args, options) {
      invocation = { command, args, options };
      return { status: 0, stdout: "help", stderr: "" };
    },
  });
  assert.equal(result.exit_code, 0);
  assert.equal(invocation.command, "cmd.exe");
  assert.deepEqual(invocation.args.slice(0, 3), ["/d", "/s", "/c"]);
  assert.match(invocation.args[3], /odin\.cmd" --help/);
  assert.equal(invocation.options.shell, false);
  assert.equal(invocation.options.cwd, "C:\\work");
});
