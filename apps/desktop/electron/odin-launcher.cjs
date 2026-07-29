const childProcess = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const path = require("node:path");

const LAUNCHER_VERSION = 5;

function quoteCmd(value) {
  return `"${String(value).replaceAll('"', '""')}"`;
}

function launcherContents({ pythonPath, resourcesRoot }) {
  const python = quoteCmd(path.resolve(pythonPath));
  const backendRoot = path.resolve(resourcesRoot);
  return [
    "@echo off",
    "setlocal",
    `set "PYTHONPATH=${backendRoot}"`,
    'set "PYTHONHOME="',
    'set "PYTHONNOUSERSITE=1"',
    'set "PYTHONSAFEPATH=1"',
    `set "CML_ODIN_LAUNCHER_VERSION=${LAUNCHER_VERSION}"`,
    'set "CML_ODIN_PAIRING_LAUNCHER=%~f0"',
    'if /I "%~1"=="auth" if /I "%~2"=="pair" if not defined CML_ODIN_PAIRING_CONSOLE (',
    `  start "" powershell.exe -NoLogo -NoProfile -NoExit -Command "$env:CML_ODIN_PAIRING_CONSOLE='1'; & $env:CML_ODIN_PAIRING_LAUNCHER auth pair"`,
    "  exit /b %ERRORLEVEL%",
    ")",
    `${python} -s -m backend.app.odin_cli %*`,
    "exit /b %ERRORLEVEL%",
    "",
  ].join("\r\n");
}

function launcherChecksum(contents) {
  return crypto.createHash("sha256").update(contents, "utf8").digest("hex");
}

function splitPath(value) {
  return String(value || "")
    .split(";")
    .map((item) => item.trim().replace(/^"|"$/g, ""))
    .filter(Boolean);
}

function pathContains(pathValue, target) {
  const expected = path.resolve(target).toLowerCase();
  return splitPath(pathValue).some((item) => path.resolve(item).toLowerCase() === expected);
}

function resolveOdinBinDir({ localAppData, appData, userData, homeDir }) {
  const configured = String(localAppData || "").trim();
  if (configured && path.isAbsolute(configured)) {
    return path.join(path.resolve(configured), "CML", "bin");
  }

  const fallbackRoot = String(appData || userData || homeDir || "").trim();
  if (!fallbackRoot || !path.isAbsolute(fallbackRoot)) {
    throw new Error("Windows could not find a writable folder for Odin.");
  }
  const roamingRoot = path.resolve(fallbackRoot);
  const localRoot =
    path.basename(roamingRoot).toLowerCase() === "roaming"
      ? path.join(path.dirname(roamingRoot), "Local")
      : roamingRoot;
  return path.join(localRoot, "CML", "bin");
}

function powershellPathScript() {
  return [
    "$target = [IO.Path]::GetFullPath($args[0])",
    "$current = [Environment]::GetEnvironmentVariable('Path', 'User')",
    "$parts = @($current -split ';' | Where-Object {",
    "  if (-not $_) { return $false }",
    "  try { return [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($_)) -ne $target }",
    "  catch { return $true }",
    "})",
    "$next = (@($target) + $parts) -join ';'",
    "if ($next.Length -gt 30000) { throw 'The user PATH is too long to add Odin safely.' }",
    "[Environment]::SetEnvironmentVariable('Path', $next, 'User')",
    "Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public static class CmlEnvironment { [DllImport(\"user32.dll\", CharSet=CharSet.Unicode, SetLastError=true)] public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint msg, IntPtr wParam, string lParam, uint flags, uint timeout, out IntPtr result); }'",
    "$broadcastResult = [IntPtr]::Zero",
    "[void][CmlEnvironment]::SendMessageTimeout([IntPtr]0xffff, 0x1a, [IntPtr]::Zero, 'Environment', 2, 5000, [ref]$broadcastResult)",
  ].join("; ");
}

function registerUserPath(binDir, runner = childProcess.spawnSync) {
  if (process.platform !== "win32") {
    return { changed: false, supported: false };
  }
  const result = runner(
    "powershell.exe",
    ["-NoProfile", "-NonInteractive", "-Command", powershellPathScript(), path.resolve(binDir)],
    { encoding: "utf8", windowsHide: true, timeout: 15_000 },
  );
  if (result.error || result.status !== 0) {
    throw new Error("Odin was installed, but Windows could not add it to your user PATH.");
  }
  return { changed: true, supported: true };
}

async function getLauncherStatus({
  binDir,
  pythonPath,
  resourcesRoot,
  userPath = process.env.PATH,
  allowUv = true,
}) {
  const launcherPath = path.join(path.resolve(binDir), "odin.cmd");
  const expected = launcherContents({ pythonPath, resourcesRoot });
  let installed = false;
  let current = "";
  try {
    current = await fs.readFile(launcherPath, "utf8");
    installed = current === expected;
  } catch {
    installed = false;
  }
  if (!installed && allowUv) {
    const uvStatus = await getUvLauncherStatus();
    if (uvStatus.installed) return uvStatus;
  }
  return {
    version: LAUNCHER_VERSION,
    launcher_path: launcherPath,
    installed,
    needs_repair: Boolean(current) && !installed,
    on_current_path: pathContains(userPath, binDir),
    expected_checksum: launcherChecksum(expected),
    install_method: "vault",
  };
}

async function getUvLauncherStatus(runner = null) {
  const result = runner
    ? runner("uv", ["tool", "dir", "--bin"], {
        encoding: "utf8",
        windowsHide: true,
        timeout: 10_000,
      })
    : await runUvToolBin();
  if (result.error || result.status !== 0) {
    return { installed: false, install_method: "uv", uv_available: false };
  }
  const binDir = String(result.stdout || "").trim();
  for (const name of process.platform === "win32" ? ["odin.exe", "odin.cmd"] : ["odin"]) {
    const launcherPath = path.join(binDir, name);
    try {
      await fs.access(launcherPath);
      return {
        version: LAUNCHER_VERSION,
        launcher_path: launcherPath,
        installed: true,
        needs_repair: false,
        on_current_path: pathContains(process.env.PATH, binDir),
        install_method: "uv",
        uv_available: true,
      };
    } catch {
      // Try the next platform launcher name.
    }
  }
  return { installed: false, install_method: "uv", uv_available: true };
}

function runUvToolBin() {
  return new Promise((resolve) => {
    let stdout = "";
    let stderr = "";
    const child = childProcess.spawn("uv", ["tool", "dir", "--bin"], {
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    const timeout = setTimeout(() => child.kill(), 3_000);
    child.stdout?.on("data", (chunk) => {
      stdout += String(chunk);
    });
    child.stderr?.on("data", (chunk) => {
      stderr += String(chunk);
    });
    child.once("error", (error) => {
      clearTimeout(timeout);
      resolve({ error, status: 1, stdout, stderr });
    });
    child.once("close", (status) => {
      clearTimeout(timeout);
      resolve({ status, stdout, stderr });
    });
  });
}

async function installLauncher({ binDir, pythonPath, resourcesRoot, registerPath = registerUserPath }) {
  const resolvedBin = path.resolve(binDir);
  const launcherPath = path.join(resolvedBin, "odin.cmd");
  const contents = launcherContents({ pythonPath, resourcesRoot });
  await fs.mkdir(resolvedBin, { recursive: true });
  const temporary = `${launcherPath}.${process.pid}.${crypto.randomUUID()}.tmp`;
  await fs.writeFile(temporary, contents, { encoding: "utf8", flag: "wx" });
  await fs.rename(temporary, launcherPath);
  registerPath(resolvedBin);
  return {
    version: LAUNCHER_VERSION,
    launcher_path: launcherPath,
    installed: true,
    needs_repair: false,
    on_current_path: pathContains(process.env.PATH, resolvedBin),
    available_in_new_shell: true,
    checksum: launcherChecksum(contents),
    install_method: "vault",
  };
}

async function installWithUv({ resourcesRoot, runner = childProcess.spawnSync }) {
  const backendRoot = path.join(path.resolve(resourcesRoot), "backend");
  await fs.access(path.join(backendRoot, "pyproject.toml"));
  const result = runner(
    "uv",
    ["tool", "install", "--force", "--no-deps", "--with", "psutil", backendRoot],
    {
      encoding: "utf8",
      windowsHide: true,
      timeout: 180_000,
      maxBuffer: 512 * 1024,
    },
  );
  if (result.error?.code === "ENOENT") {
    throw new Error("uv is not installed or is not available on PATH.");
  }
  if (result.error || result.status !== 0) {
    const detail = String(result.stderr || result.stdout || "").trim().slice(0, 500);
    throw new Error(detail || "uv could not install Odin.");
  }
  const status = await getUvLauncherStatus(runner);
  if (!status.installed) {
    throw new Error("uv finished, but the Odin command was not found.");
  }
  return status;
}

function runLauncher(launcherPath, args, {
  cwd = process.cwd(),
  runner = childProcess.spawnSync,
  visibleRunner = childProcess.spawn,
  visible = false,
} = {}) {
  const safeArgs = Array.isArray(args) ? args.map(String) : [];
  if (!visible && (safeArgs.length !== 1 || safeArgs[0] !== "--help")) {
    throw new Error("Only the Odin help probe can run silently.");
  }
  if (visible) {
    const powershellCommand =
      `$env:CML_ODIN_PAIRING_CONSOLE='1'; & ${quotePowerShell(path.resolve(launcherPath))} auth pair`;
    const encodedCommand = Buffer.from(powershellCommand, "utf16le").toString("base64");
    const child = visibleRunner(
      "powershell.exe",
      ["-NoLogo", "-NoProfile", "-NoExit", "-EncodedCommand", encodedCommand],
      {
        cwd,
        detached: true,
        stdio: "ignore",
        windowsHide: false,
      },
    );
    if (!child || child.pid === undefined) {
      throw new Error("Windows could not open PowerShell for Odin pairing.");
    }
    child.once?.("error", () => {});
    child.unref?.();
    return { started: true };
  }
  const command = `""${path.resolve(launcherPath).replaceAll('"', '""')}" --help"`;
  const result = runner("cmd.exe", ["/d", "/s", "/c", command], {
    cwd,
    encoding: "utf8",
    windowsHide: true,
    timeout: 20_000,
    maxBuffer: 256 * 1024,
    shell: false,
  });
  return {
    exit_code: Number.isInteger(result.status) ? result.status : 1,
    stdout: String(result.stdout || "").slice(0, 32_000),
    stderr: String(result.stderr || "").slice(0, 32_000),
  };
}

function quotePowerShell(value) {
  return `'${String(value).replaceAll("'", "''")}'`;
}

module.exports = {
  LAUNCHER_VERSION,
  getLauncherStatus,
  installLauncher,
  installWithUv,
  launcherChecksum,
  launcherContents,
  pathContains,
  registerUserPath,
  resolveOdinBinDir,
  runLauncher,
  splitPath,
};
