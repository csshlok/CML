const assert = require("node:assert/strict");
const fsSync = require("node:fs");
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
  resolveOdinBinDir,
  runLauncher,
} = require("./odin-launcher.cjs");

test("Odin launcher uses absolute packaged paths and preserves the caller working directory", () => {
  const contents = launcherContents({
    pythonPath: "C:\\Program Files\\CML\\resources\\python-runtime\\python.exe",
    resourcesRoot: "C:\\Program Files\\CML\\resources",
  });
  assert.match(contents, /python-runtime\\python\.exe" -s -m backend\.app\.odin_cli %\*/);
  assert.match(contents, /PYTHONPATH=C:\\Program Files\\CML\\resources/);
  assert.match(contents, /PYTHONSAFEPATH=1/);
  assert.match(contents, /CML_ODIN_PAIRING_CONSOLE/);
  assert.match(contents, /start "" powershell\.exe/);
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

test("Odin bin resolves from Windows local app data without unsupported Electron paths", () => {
  assert.equal(
    resolveOdinBinDir({
      localAppData: "C:\\Users\\Person\\AppData\\Local",
      appData: "C:\\Users\\Person\\AppData\\Roaming",
    }),
    path.join("C:\\Users\\Person\\AppData\\Local", "CML", "bin"),
  );
  assert.equal(
    resolveOdinBinDir({
      localAppData: "",
      appData: "C:\\Users\\Person\\AppData\\Roaming",
    }),
    path.join("C:\\Users\\Person\\AppData\\Local", "CML", "bin"),
  );
  assert.equal(
    resolveOdinBinDir({
      localAppData: "relative\\path",
      appData: "C:\\Users\\Person\\AppData\\Roaming",
    }),
    path.join("C:\\Users\\Person\\AppData\\Local", "CML", "bin"),
  );
});

test("the desktop main process only requests supported Electron app paths", () => {
  const mainSource = fsSync.readFileSync(path.join(__dirname, "main.cjs"), "utf8");

  assert.doesNotMatch(mainSource, /getPath\(["']localAppData["']\)/);
  assert.match(mainSource, /getPath\(["']appData["']\)/);
  assert.match(mainSource, /resolveOdinBinDir/);
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

test("visible Odin pairing uses Windows start to create an independent PowerShell console", () => {
  let invocation = null;
  const result = runLauncher("C:\\Users\\Me\\CML\\bin\\odin.cmd", [], {
    cwd: "C:\\Users\\Me",
    visible: true,
    runner(command, args, options) {
      invocation = { command, args, options };
      return { status: 0, stdout: "", stderr: "" };
    },
  });

  assert.deepEqual(result, { started: true });
  assert.equal(invocation.command, "cmd.exe");
  assert.deepEqual(invocation.args.slice(0, 3), ["/d", "/s", "/c"]);
  assert.match(invocation.args[3], /^start "" powershell\.exe /);
  assert.match(invocation.args[3], /-NoExit -EncodedCommand [A-Za-z0-9+/=]+$/);
  assert.equal(invocation.options.windowsHide, true);
  assert.equal(invocation.options.cwd, "C:\\Users\\Me");
});

test("visible Odin pairing reports a failed Windows handoff", () => {
  assert.throws(
    () =>
      runLauncher("C:\\Users\\Me\\CML\\bin\\odin.cmd", [], {
        visible: true,
        runner: () => ({ status: 1, stdout: "", stderr: "failed" }),
      }),
    /could not open PowerShell/i,
  );
});
