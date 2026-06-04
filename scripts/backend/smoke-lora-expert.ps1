param(
  [string]$ReportPath = ".tmp/lora-expert-smoke-report.json",
  [switch]$AllowTestTrainer
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}

if (-not $AllowTestTrainer -and -not $env:CML_LORA_TRAINER_COMMAND) {
  throw "CML_LORA_TRAINER_COMMAND is required for real LoRA smoke. Use -AllowTestTrainer only for CI scaffold validation."
}

$reportFullPath = Join-Path $repoRoot $ReportPath
$reportDir = Split-Path -Parent $reportFullPath
if ($reportDir) {
  New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
}

$env:CML_ALLOW_LORA_TEST_TRAINER = if ($AllowTestTrainer) { "1" } else { "0" }
$env:CML_ALLOW_HASH_EMBEDDINGS = "1"
$env:CML_EMBEDDING_PROVIDER = "hash"
$env:REPORT_PATH = $reportFullPath

$pythonScript = @'
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from backend.app.core.config import get_settings

repo_report = Path(os.environ.get("REPORT_PATH", ".tmp/lora-expert-smoke-report.json"))
work = tempfile.TemporaryDirectory()
os.environ["CML_DATA_DIR"] = work.name
os.environ["CML_DATABASE_PATH"] = str(Path(work.name) / "smoke.sqlite3")
get_settings.cache_clear()

from backend.app.api.routes.clusters import get_expert_status, list_expert_artifacts, queue_expert_retrain
from backend.app.api.routes.sources import create_source
from backend.app.core.background_jobs import run_due_jobs_once
from backend.app.core.database import connect, init_db, utc_now
from backend.app.core.expert_evaluation import build_expert_evaluation_plan, compare_retrieval_vs_adapter
from backend.app.core.training_dataset import build_cluster_dataset
from backend.app.schemas import SourceCreate

init_db()
now = utc_now()
with connect() as conn:
    conn.execute("INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", ("vault-smoke", "Smoke", work.name, now, now))
    conn.execute(
        """
        INSERT INTO clusters (id, vault_id, name, description, color, expert_status, created_at, updated_at)
        VALUES ('cluster-smoke', 'vault-smoke', 'LoRA Smoke', 'Smoke cluster', 'sage', 'retrieval_ready', ?, ?)
        """,
        (now, now),
    )

for index in range(3):
    create_source(
        SourceCreate(
            vault_id="vault-smoke",
            cluster_id="cluster-smoke",
            title=f"LoRA smoke source {index + 1}",
            source_type="note",
            raw_text=(f"lora smoke adapter evidence source {index + 1} strict evaluation retrieval baseline " * 240),
            summary=f"LoRA smoke source {index + 1} contains strict adapter training and evaluation evidence.",
        )
    )

hardware = {"training_supported": True, "hardware_tier": "smoke", "detail": "smoke hardware override"}
with patch("backend.app.core.expert_lifecycle.hardware_status", return_value=hardware), patch("backend.app.core.hardware.hardware_status", return_value=hardware):
    expert_job = queue_expert_retrain("cluster-smoke")
    processed = run_due_jobs_once(limit=10)

dataset = build_cluster_dataset("cluster-smoke")
plan = build_expert_evaluation_plan(dataset)
comparison = compare_retrieval_vs_adapter([60.0, 62.0, 61.0], [66.0, 68.0, 67.0])
artifacts = list_expert_artifacts("cluster-smoke")
status = get_expert_status("cluster-smoke")
report = {
    "processed_jobs": processed,
    "expert_job": expert_job,
    "artifact_count": len(artifacts),
    "expert_status": status,
    "evaluation_plan": {"case_count": plan["case_count"], "categories": plan["categories"]},
    "retrieval_vs_adapter": comparison,
}
repo_report.write_text(json.dumps(report, indent=2), encoding="utf-8")
if not artifacts or not status["searchable"] or not comparison["passes"]:
    raise SystemExit(1)
'@

$pythonScript | & $python -
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

Write-Host "LoRA expert smoke report written to $reportFullPath"
