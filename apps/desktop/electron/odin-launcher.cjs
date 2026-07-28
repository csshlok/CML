const childProcess = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const path = require("node:path");

const LAUNCHER_VERSION = 4;

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

function resolveOdinBinDir({ localAppData, appData }) {
  const configured = String(localAppData || "").trim();
  if (configured && path.isAbsolute(configured)) {
    return path.join(path.resolve(configured), "CML", "bin");
  }

  const roamingRoot = path.resolve(String(appData || ""));
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

async function getLauncherStatus({ binDir, pythonPath, resourcesRoot, userPath = process.env.PATH }) {
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
  return {
    version: LAUNCHER_VERSION,
    launcher_path: launcherPath,
    installed,
    needs_repair: Boolean(current) && !installed,
    on_current_path: pathContains(userPath, binDir),
    expected_checksum: launcherChecksum(expected),
  };
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
  };
}

function runLauncher(launcherPath, args, {
  cwd = process.cwd(),
  runner = childProcess.spawnSync,
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
    const result = runner(
      "cmd.exe",
      [
        "/d",
        "/s",
        "/c",
        `start "" powershell.exe -NoLogo -NoProfile -NoExit -EncodedCommand ${encodedCommand}`,
      ],
      {
        cwd,
        encoding: "utf8",
        windowsHide: true,
        timeout: 10_000,
      },
    );
    if (result.error || result.status !== 0) {
      throw new Error("Windows could not open PowerShell for Odin pairing.");
    }
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
  launcherChecksum,
  launcherContents,
  pathContains,
  registerUserPath,
  resolveOdinBinDir,
  runLauncher,
  splitPath,
};
