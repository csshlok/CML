const assert = require("node:assert/strict");
const fsSync = require("node:fs");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const {
  getLauncherStatus,
  installLauncher,
  installWithUv,
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
  assert.match(contents, /set "CML_ODIN_PAIRING_LAUNCHER=%~f0"/);
  assert.match(contents, /& \$env:CML_ODIN_PAIRING_LAUNCHER auth pair/);
  assert.doesNotMatch(contents, /& '%~f0'/);
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
    allowUv: false,
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

test("visible Odin pairing starts an independent PowerShell console without waiting for it", () => {
  let invocation = null;
  let unrefCalled = false;
  const result = runLauncher("C:\\Users\\Me\\CML\\bin\\odin.cmd", [], {
    cwd: "C:\\Users\\Me",
    visible: true,
    visibleRunner(command, args, options) {
      invocation = { command, args, options };
      return {
        pid: 123,
        once() {},
        unref() {
          unrefCalled = true;
        },
      };
    },
  });

  assert.deepEqual(result, { started: true });
  assert.equal(invocation.command, "powershell.exe");
  assert.deepEqual(invocation.args.slice(0, 3), ["-NoLogo", "-NoProfile", "-NoExit"]);
  assert.equal(invocation.args[3], "-EncodedCommand");
  assert.match(invocation.args[4], /^[A-Za-z0-9+/=]+$/);
  assert.equal(invocation.options.windowsHide, false);
  assert.equal(invocation.options.detached, true);
  assert.equal(invocation.options.cwd, "C:\\Users\\Me");
  assert.equal(unrefCalled, true);
});

test("uv installation uses the local backend package and verifies the installed command", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "cml-odin-uv-"));
  const backendRoot = path.join(root, "backend");
  const uvBin = path.join(root, "uv-bin");
  await fs.mkdir(backendRoot, { recursive: true });
  await fs.mkdir(uvBin, { recursive: true });
  await fs.writeFile(path.join(backendRoot, "pyproject.toml"), "[project]\nname='fixture'\nversion='1.0.0'\n", "utf8");
  await fs.writeFile(path.join(uvBin, process.platform === "win32" ? "odin.exe" : "odin"), "", "utf8");
  const invocations = [];
  try {
    const status = await installWithUv({
      resourcesRoot: root,
      runner(command, args, options) {
        invocations.push({ command, args, options });
        if (args.join(" ") === "tool dir --bin") {
          return { status: 0, stdout: uvBin, stderr: "" };
        }
        return { status: 0, stdout: "installed", stderr: "" };
      },
    });
    assert.equal(status.installed, true);
    assert.equal(status.install_method, "uv");
    assert.deepEqual(invocations[0].args.slice(0, 7), [
      "tool",
      "install",
      "--force",
      "--no-deps",
      "--with",
      "psutil",
      backendRoot,
    ]);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test("visible Odin pairing reports a failed Windows handoff", () => {
  assert.throws(
    () =>
      runLauncher("C:\\Users\\Me\\CML\\bin\\odin.cmd", [], {
        visible: true,
        visibleRunner: () => ({ pid: undefined }),
      }),
    /could not open PowerShell/i,
  );
});
