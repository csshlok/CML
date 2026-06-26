param(
  [Parameter(Mandatory = $true)]
  [string]$ReportPath,
  [string]$OutputPath = ".tmp/lora-proof.json"
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}

$reportFullPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $ReportPath))
$outputFullPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutputPath))
$env:CML_LORA_PROOF_REPORT_PATH = $reportFullPath
$env:CML_LORA_PROOF_OUTPUT_PATH = $outputFullPath

$pythonScript = @'
import json
import os
from pathlib import Path

from backend.app.core.lora_proof import write_lora_smoke_proof

proof = write_lora_smoke_proof(
    Path(os.environ["CML_LORA_PROOF_REPORT_PATH"]),
    Path(os.environ["CML_LORA_PROOF_OUTPUT_PATH"]),
)
print(
    json.dumps(
        {
            "output_path": os.environ["CML_LORA_PROOF_OUTPUT_PATH"],
            "public_gate": proof["public_gate"],
            "baseline_score": proof["benchmark"]["baseline_score"],
            "bundle_with_expert_score": proof["benchmark"]["bundle_with_expert_score"],
            "quality_delta": proof["benchmark"]["quality_delta"],
            "bundle_release_gate": proof["benchmark"]["bundle_release_gate"],
        },
        indent=2,
    )
)
'@

$pythonScript | & $python -
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}
