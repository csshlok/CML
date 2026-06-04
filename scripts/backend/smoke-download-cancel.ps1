param(
  [ValidateSet("embedding", "model")]
  [string]$Kind = "embedding",
  [string]$ModelId = "qwen3-4b-q4_k_m",
  [int]$WaitSeconds = 10
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}

$code = @'
import json
import time
from pathlib import Path

KIND = "__KIND__"
MODEL_ID = "__MODEL_ID__"
WAIT_SECONDS = int("__WAIT_SECONDS__")


def wait_until_active(status_fn):
    deadline = time.monotonic() + max(0, WAIT_SECONDS)
    current = status_fn()
    while time.monotonic() < deadline:
        status = current.get("status")
        if status in {"installed", "failed", "cancelled"} or (current.get("bytes_downloaded") or 0) > 0:
            return current
        time.sleep(0.25)
        current = status_fn()
    return current

if KIND == "embedding":
    from backend.app.core.embeddings import (
        cancel_embedding_model_download,
        embedding_download_status,
        start_embedding_model_download,
    )

    state = start_embedding_model_download(str(Path(".tmp") / "embedding-cancel-smoke"))
    observed = wait_until_active(embedding_download_status)
    cancelled = cancel_embedding_model_download()
    final = embedding_download_status()
else:
    from backend.app.core.model_registry import cancel_model_download, model_status, start_model_download

    state = start_model_download(MODEL_ID)
    observed = wait_until_active(lambda: model_status(MODEL_ID).get("download") or {})
    cancelled = cancel_model_download(MODEL_ID)
    final = model_status(MODEL_ID).get("download")

print(json.dumps({
    "kind": KIND,
    "initial_status": state.get("status"),
    "observed_status_before_cancel": observed.get("status"),
    "observed_error_before_cancel": observed.get("error"),
    "cancel_status": cancelled.get("status"),
    "final_status": (final or {}).get("status"),
    "final_error": (final or {}).get("error"),
    "bytes_downloaded": (final or cancelled or {}).get("bytes_downloaded"),
    "progress_percent": (final or cancelled or {}).get("progress_percent"),
    "cancellation_observed": (cancelled.get("status") in {"cancelled", "cancelling"} or (final or {}).get("status") in {"cancelled", "cancelling"}),
}, indent=2))
'@

$code = $code.Replace("__KIND__", $Kind).Replace("__MODEL_ID__", $ModelId).Replace("__WAIT_SECONDS__", "$WaitSeconds")
$code | & $python -
