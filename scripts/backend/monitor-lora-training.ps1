param(
  [string]$WorkDir = "T:\cml-lora-sample-vault-1p5b-10e",
  [int]$RefreshSeconds = 5
)

$ErrorActionPreference = "Stop"

function Get-LatestAdapterDir {
  param([string]$ExpertsRoot)
  if (-not (Test-Path $ExpertsRoot)) {
    return $null
  }
  return Get-ChildItem -LiteralPath $ExpertsRoot -Directory |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
}

function Get-LatestTrainerEntry {
  param([string]$TrainerLogPath)
  if (-not (Test-Path $TrainerLogPath)) {
    return $null
  }
  $line = Get-Content -LiteralPath $TrainerLogPath -Tail 1 -ErrorAction SilentlyContinue
  if (-not $line) {
    return $null
  }
  try {
    return $line | ConvertFrom-Json
  } catch {
    return $null
  }
}

function Get-TrainerStateSummary {
  param([string]$AdapterDir)
  if (-not (Test-Path $AdapterDir)) {
    return $null
  }
  $statePath = Get-ChildItem -LiteralPath $AdapterDir -Recurse -Filter trainer_state.json -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 -ExpandProperty FullName
  if (-not $statePath) {
    return $null
  }
  $script = @'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
log_history = list(payload.get("log_history") or [])
eval_entries = [item for item in log_history if isinstance(item, dict) and "eval_loss" in item]
latest_eval = eval_entries[-1] if eval_entries else None
summary = {
    "state_path": str(path),
    "best_metric": payload.get("best_metric"),
    "best_model_checkpoint": payload.get("best_model_checkpoint"),
    "latest_eval_loss": None if latest_eval is None else latest_eval.get("eval_loss"),
    "latest_eval_epoch": None if latest_eval is None else latest_eval.get("epoch"),
    "latest_eval_runtime": None if latest_eval is None else latest_eval.get("eval_runtime"),
    "eval_count": len(eval_entries),
}
print(json.dumps(summary))
'@
  $raw = @"
$script
"@
  $result = $raw | python - $statePath
  if (-not $result) {
    return $null
  }
  try {
    return $result | ConvertFrom-Json
  } catch {
    return $null
  }
}

function Get-SqliteSummary {
  param([string]$DbPath)
  if (-not (Test-Path $DbPath)) {
    return $null
  }

  $script = @'
import json
import sqlite3
import sys

db_path = sys.argv[1]
conn = sqlite3.connect(db_path)
cur = conn.cursor()

payload = {
    "cluster": None,
    "job": None,
    "source_count": None,
}

try:
    row = cur.execute(
        "select id, expert_status, updated_at from clusters order by updated_at desc limit 1"
    ).fetchone()
    if row:
        payload["cluster"] = {
            "id": row[0],
            "expert_status": row[1],
            "updated_at": row[2],
        }
except Exception:
    pass

try:
    row = cur.execute(
        "select id, action, status, failure_code, detail, updated_at from cluster_expert_jobs order by updated_at desc limit 1"
    ).fetchone()
    if row:
        payload["job"] = {
            "id": row[0],
            "action": row[1],
            "status": row[2],
            "failure_code": row[3],
            "detail": row[4],
            "updated_at": row[5],
        }
except Exception:
    pass

try:
    row = cur.execute("select count(*) from sources").fetchone()
    if row:
        payload["source_count"] = row[0]
except Exception:
    pass

conn.close()
print(json.dumps(payload))
'@

  $raw = @"
$script
"@
  $result = $raw | python - $DbPath
  if (-not $result) {
    return $null
  }
  try {
    return $result | ConvertFrom-Json
  } catch {
    return $null
  }
}

function Format-ProgressBar {
  param([double]$Percent)
  $normalized = [Math]::Max(0, [Math]::Min(100, $Percent))
  $slots = 24
  $filled = [int][Math]::Round(($normalized / 100.0) * $slots)
  return ("[" + ("#" * $filled).PadRight($slots, ".") + "]")
}

while ($true) {
  $dbPath = Join-Path $WorkDir "smoke.sqlite3"
  $expertsRoot = Join-Path $WorkDir "experts\cluster-smoke"
  $latestAdapter = Get-LatestAdapterDir -ExpertsRoot $expertsRoot
  $trainerLogPath = if ($latestAdapter) { Join-Path $latestAdapter.FullName "trainer_log.jsonl" } else { $null }
  $stderrPath = if ($latestAdapter) { Join-Path $latestAdapter.FullName "trainer.stderr.log" } else { $null }
  $stdoutPath = if ($latestAdapter) { Join-Path $latestAdapter.FullName "trainer.stdout.log" } else { $null }
  $configPath = if ($latestAdapter) { Join-Path $latestAdapter.FullName "training-config.json" } else { $null }

  $summary = Get-SqliteSummary -DbPath $dbPath
  $trainer = if ($trainerLogPath) { Get-LatestTrainerEntry -TrainerLogPath $trainerLogPath } else { $null }
  $trainerState = if ($latestAdapter) { Get-TrainerStateSummary -AdapterDir $latestAdapter.FullName } else { $null }
  $config = $null
  if ($configPath -and (Test-Path $configPath)) {
    try {
      $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    } catch {
      $config = $null
    }
  }

  Clear-Host
  Write-Host "CML LoRA Training Monitor" -ForegroundColor Cyan
  Write-Host ("Time: " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
  Write-Host ("WorkDir: " + $WorkDir)
  Write-Host ""

  if ($summary -and $summary.cluster) {
    Write-Host ("Cluster: " + $summary.cluster.id)
    Write-Host ("Status : " + $summary.cluster.expert_status)
    Write-Host ("Sources: " + $summary.source_count)
    Write-Host ("Updated: " + $summary.cluster.updated_at)
  } else {
    Write-Host "Cluster: not initialized yet"
  }

  if ($summary -and $summary.job) {
    Write-Host ("Job    : " + $summary.job.action + " / " + $summary.job.status)
    if ($summary.job.failure_code) {
      Write-Host ("Failure: " + $summary.job.failure_code) -ForegroundColor Yellow
    }
  }

  Write-Host ""
  if ($latestAdapter) {
    Write-Host ("Adapter : " + $latestAdapter.Name)
  } else {
    Write-Host "Adapter : not created yet"
  }

  if ($config) {
    Write-Host ("Epochs  : " + $config.num_train_epochs)
    Write-Host ("Base    : " + $config.base_model)
    if ($config.eval_steps) {
      Write-Host ("Eval    : every " + $config.eval_steps + " steps")
    }
    if ($config.early_stopping_steps) {
      Write-Host ("Stop    : after " + $config.early_stopping_steps + " non-improving evals")
    }
  }

  if ($trainer) {
    $percent = [double]($trainer.percentage)
    Write-Host ("Progress: " + (Format-ProgressBar -Percent $percent) + " " + ("{0:N2}" -f $percent) + "%")
    Write-Host ("Epoch   : " + ("{0:N3}" -f [double]$trainer.epoch))
    Write-Host ("Steps   : " + $trainer.current_steps + " / " + $trainer.total_steps)
    Write-Host ("LR      : " + $trainer.lr)
    Write-Host ("Loss    : " + $trainer.loss)
    Write-Host ("Elapsed : " + $trainer.elapsed_time)
    Write-Host ("Remain  : " + $trainer.remaining_time)
  } else {
    Write-Host "Progress: waiting for trainer_log.jsonl"
  }

  if ($trainerState -and $trainerState.eval_count -gt 0) {
    Write-Host ("Val loss: " + $trainerState.latest_eval_loss)
    Write-Host ("Val ep  : " + $trainerState.latest_eval_epoch)
    if ($trainerState.best_metric -ne $null) {
      Write-Host ("Best val: " + $trainerState.best_metric)
    }
    if ($trainerState.best_model_checkpoint) {
      Write-Host ("Best ckpt: " + [System.IO.Path]::GetFileName($trainerState.best_model_checkpoint))
    }
  }

  if ($stderrPath -and (Test-Path $stderrPath)) {
    $stderrTail = Get-Content -LiteralPath $stderrPath -Tail 5 -ErrorAction SilentlyContinue
    if ($stderrTail) {
      Write-Host ""
      Write-Host "Recent stderr:" -ForegroundColor DarkYellow
      $stderrTail | ForEach-Object { Write-Host $_ }
    }
  }

  if ($summary -and $summary.job -and $summary.job.detail) {
    Write-Host ""
    Write-Host "Job detail:" -ForegroundColor DarkCyan
    Write-Host $summary.job.detail
  }

  Write-Host ""
  Write-Host ("Refresh every " + $RefreshSeconds + "s. Press Ctrl+C to stop.") -ForegroundColor DarkGray
  Start-Sleep -Seconds $RefreshSeconds
}
