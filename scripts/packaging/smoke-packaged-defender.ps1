param(
  [string]$PackageRoot = ""
)

$ErrorActionPreference = "Stop"

if (-not $PackageRoot) {
  throw "PackageRoot is required. Pass the explicit win-unpacked root to smoke-packaged-defender.ps1."
}
$packagePath = [System.IO.Path]::GetFullPath($PackageRoot)
$resourcesPath = Join-Path $packagePath "resources"
$python = Join-Path $resourcesPath "python-runtime\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  throw "Packaged Python runtime not found: $python"
}

$smokeRoot = Join-Path $env:TEMP ("cml-packaged-defender-" + [guid]::NewGuid().ToString("n"))
$dataDir = Join-Path $smokeRoot "data"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

$env:PYTHONPATH = $resourcesPath
$env:PYTHONNOUSERSITE = "1"
$env:CML_DATA_DIR = $dataDir
$env:CML_DATABASE_PATH = Join-Path $dataDir "cml.sqlite3"
$env:CML_ALLOW_HASH_EMBEDDINGS = "1"
$env:CML_EMBEDDING_PROVIDER = "hash"

$code = @'
import json
import os
from pathlib import Path
from unittest.mock import Mock, patch

from backend.app.core.database import connect, init_db, utc_now
from backend.app.core.quarantine import QuarantineError, defender_scan, ingest_file_through_quarantine

init_db()
root = Path(os.environ["CML_DATA_DIR"])
now = utc_now()
with connect() as conn:
    conn.execute(
        "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("vault-defender-smoke", "Defender smoke", str(root), now, now),
    )

fixture = root / "defender-smoke.txt"
fixture.write_text("packaged defender recovery and quarantine smoke", encoding="utf-8")

with patch(
    "backend.app.core.quarantine._defender_scan_once",
    side_effect=[
        {"status": "unavailable", "classification": "transient", "detail": "scanner busy"},
        {"status": "passed", "classification": "clean", "detail": "clean"},
    ],
), patch("backend.app.core.quarantine.time.sleep"):
    recovered = defender_scan(str(fixture))
if recovered.get("status") != "passed" or recovered.get("attempts") != 2:
    raise SystemExit("Packaged Defender transient retry did not recover.")

parser = Mock()
with patch("backend.app.core.quarantine.platform.system", return_value="Windows"), patch(
    "backend.app.core.quarantine.defender_scan",
    return_value={"status": "unavailable", "classification": "permanent", "detail": "not installed"},
), patch("backend.app.core.quarantine.parse_candidate_file", parser):
    try:
        ingest_file_through_quarantine("vault-defender-smoke", str(fixture))
    except QuarantineError:
        pass
    else:
        raise SystemExit("Packaged import did not fail closed when Defender was unavailable.")
if parser.called:
    raise SystemExit("Packaged fail-closed policy allowed parser entry.")

with connect() as conn:
    blocked = conn.execute(
        "SELECT validation_status, parser_status, defender_status FROM source_quarantine_records ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
if not blocked or blocked["validation_status"] != "blocked" or blocked["parser_status"] != "not_run":
    raise SystemExit("Packaged fail-closed decision was not persisted.")

sandbox_parser = Mock(return_value={"title": fixture.name, "pages": [fixture.read_text(encoding="utf-8")], "parser": {}})
with patch.dict(os.environ, {"CML_SANDBOX_ONLY_ALLOW_DEFENDER_UNAVAILABLE": "1"}), patch(
    "backend.app.core.quarantine.platform.system", return_value="Windows"
), patch(
    "backend.app.core.quarantine.defender_scan",
    return_value={"status": "unavailable", "classification": "permanent", "detail": "not installed"},
), patch("backend.app.core.quarantine.run_parser_worker", sandbox_parser):
    sandboxed = ingest_file_through_quarantine("vault-defender-smoke", str(fixture))
if not sandbox_parser.called:
    raise SystemExit("Packaged warned policy did not force the sandbox parser.")
if "sandbox_only_policy" not in sandboxed["security"]["security_labels"]:
    raise SystemExit("Packaged warned policy did not label the result.")

print(json.dumps({
    "package_root": os.environ.get("PYTHONPATH"),
    "transient_retry_recovered": True,
    "fail_closed_when_unavailable": True,
    "fail_closed_record_persisted": True,
    "sandbox_only_policy_forced_worker": True,
}, indent=2))
'@

$code | & $python -s -
if ($LASTEXITCODE -ne 0) {
  throw "Packaged Defender policy smoke failed."
}
