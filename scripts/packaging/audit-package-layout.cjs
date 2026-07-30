const fs = require("node:fs");
const path = require("node:path");
const {
  defaultWritableRoots,
  packageLayoutAudit,
  resolvePackagedHelperPaths,
  verifyHelperManifest,
} = require("../../apps/desktop/electron/helper-integrity.cjs");

async function main() {
  const packageRoot = process.argv[2]
    ? path.resolve(process.argv[2])
    : path.resolve(__dirname, "..", "..", "apps", "desktop", "packaging");
  const resourcesRoot = process.argv[3]
    ? path.resolve(process.argv[3])
    : packageRoot;
  const helperPaths = resolvePackagedHelperPaths(resourcesRoot);
  const manifestReport = await verifyHelperManifest(resourcesRoot);
  const requiredRuntimeDependencies = [
    path.join(resourcesRoot, "python-runtime", "Lib", "site-packages", "turbovec"),
  ];
  const missingRuntimeDependencies = requiredRuntimeDependencies.filter(
    (dependencyPath) => !fs.existsSync(dependencyPath),
  );
  const layoutReport = packageLayoutAudit({
    packageRoot,
    resourcesRoot,
    helperRoots: [
      helperPaths.backendRoot,
      helperPaths.pythonRuntime,
      helperPaths.playwrightRoot,
      helperPaths.llmRuntimeRoot,
      helperPaths.tunnelRuntimeRoot,
    ],
    writableRoots: defaultWritableRoots({
      userDataPath: path.join(packageRoot, "__simulated-userData"),
      activeVaultPath: path.join(packageRoot, "__simulated-vault"),
    }),
    helperManifestPath: helperPaths.helperManifest,
  });
  const report = {
    package_root: packageRoot,
    resources_root: resourcesRoot,
    manifest_ok: manifestReport.ok,
    layout_ok: layoutReport.ok,
    manifest_entry_count: manifestReport.entry_count,
    runtime_dependencies_ok: missingRuntimeDependencies.length === 0,
    missing_runtime_dependencies: missingRuntimeDependencies,
    overlaps: layoutReport.overlaps,
  };
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  if (!manifestReport.ok || !layoutReport.ok || missingRuntimeDependencies.length > 0) {
    process.exitCode = 1;
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
