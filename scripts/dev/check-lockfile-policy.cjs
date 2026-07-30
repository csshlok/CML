const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..", "..");
const required = path.join(root, "package-lock.json");
const forbidden = [
  path.join(root, "apps", "desktop", "package-lock.json"),
  path.join(root, "apps", "desktop", "bun.lock"),
  path.join(root, "bun.lock"),
  path.join(root, "yarn.lock"),
  path.join(root, "pnpm-lock.yaml"),
];

if (!fs.existsSync(required)) {
  throw new Error("The root package-lock.json is required.");
}
const conflicts = forbidden.filter((candidate) => fs.existsSync(candidate));
if (conflicts.length) {
  throw new Error(
    `npm is the workspace package manager. Remove conflicting lockfiles:\n${conflicts.join("\n")}`,
  );
}

const packageJson = JSON.parse(
  fs.readFileSync(path.join(root, "package.json"), "utf8"),
);
if (!String(packageJson.packageManager || "").startsWith("npm@")) {
  throw new Error("package.json must record the supported npm version.");
}

process.stdout.write("Workspace dependency policy is consistent.\n");
