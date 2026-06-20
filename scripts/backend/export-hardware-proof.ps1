param(
  [string]$OutputPath = ".tmp/hardware-proof.json"
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}

$outputFullPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutputPath))
$outputDir = Split-Path -Parent $outputFullPath
if ($outputDir) {
  New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
}

$env:CML_HARDWARE_PROOF_OUTPUT_PATH = $outputFullPath
$env:CML_HARDWARE_PROOF_COMMAND = "powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backend\export-hardware-proof.ps1 -OutputPath $OutputPath"

$pythonScript = @'
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from backend.app.core.hardware import hardware_status

output_path = Path(os.environ["CML_HARDWARE_PROOF_OUTPUT_PATH"])
status = hardware_status()
proof = {
    "generated_at": datetime.now(UTC).isoformat(),
    "command": os.environ.get("CML_HARDWARE_PROOF_COMMAND", ""),
    "hardware_status": status,
    "avx2_proof_present": status.get("avx2") is not None,
    "avx2_supported": status.get("avx2") is True,
}
output_path.write_text(json.dumps(proof, indent=2), encoding="utf-8")
print(json.dumps(proof, indent=2))
'@

$pythonScript | & $python -
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}
