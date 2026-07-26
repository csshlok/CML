param(
  [string]$PackageRoot = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
if (-not $PackageRoot) {
  throw "PackageRoot is required. Pass the explicit win-unpacked root to smoke-packaged-migration-drill.ps1."
}

$packagePath = [System.IO.Path]::GetFullPath($PackageRoot)
$resourcesPath = Join-Path $packagePath "resources"
$python = Join-Path $resourcesPath "python-runtime\python.exe"
$backendRoot = Join-Path $resourcesPath "backend"

if (-not (Test-Path -LiteralPath $python)) {
  throw "Packaged Python runtime not found: $python"
}
if (-not (Test-Path -LiteralPath (Join-Path $backendRoot "app\main.py"))) {
  throw "Packaged backend source not found under $backendRoot"
}

$drillRoot = Join-Path $env:TEMP ("cml-packaged-migration-drill-" + [guid]::NewGuid().ToString("n"))
$dataDir = Join-Path $drillRoot "data"
$dbPath = Join-Path $dataDir "cml.sqlite3"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

$env:PYTHONPATH = $resourcesPath
$env:PYTHONNOUSERSITE = "1"
$env:CML_BACKEND_MODE = "full_vault"
$env:CML_DATA_DIR = $dataDir
$env:CML_DATABASE_PATH = $dbPath
$env:CML_ALLOW_HASH_EMBEDDINGS = "1"
$env:CML_EMBEDDING_PROVIDER = "hash"

$code = @'
import json
from backend.app.core.database import connect, init_db, utc_now
from backend.app.core.startup_repair import startup_repair_summary

init_db()
with connect() as conn:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            error TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO schema_migrations (version, name, started_at, status)
        VALUES (99, 'packaged_interrupted_drill', ?, 'running')
        """,
        (utc_now(),),
    )

summary = startup_repair_summary(apply_recovery=False)
interrupted = summary.get("interrupted_migrations", [])
if not interrupted or interrupted[0].get("version") != 99:
    raise SystemExit("Interrupted packaged migration was not reported.")
if not summary.get("safe_degraded_mode"):
    raise SystemExit("Interrupted packaged migration did not force safe degraded mode.")
if not any("interrupted_migrations_detected" in issue for issue in summary.get("issues", [])):
    raise SystemExit("Interrupted packaged migration did not explain the degraded state.")
print(json.dumps({"drill": "interrupted_migration", "summary": summary}, indent=2))
'@

$code | & $python -s -
if ($LASTEXITCODE -ne 0) {
  throw "Packaged migration drill failed."
}
