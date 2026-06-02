$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}

$code = @'
import json
from backend.app.core.vector_maintenance import (
    activate_embedding_index,
    begin_embedding_index_transition,
    embedding_index_policy,
)

before = embedding_index_policy()
building = begin_embedding_index_transition("sentence-transformers/transition-smoke")
active = activate_embedding_index("sentence-transformers/transition-smoke", "v2-smoke")
after = embedding_index_policy()

print(json.dumps({
    "before": before,
    "building": building,
    "active": active,
    "after": after,
    "atomic_activation_observed": after["active_embedding_model_id"] == "sentence-transformers/transition-smoke"
        and after["active_index_version"] == "v2-smoke"
        and after["building_embedding_model_id"] is None,
}, indent=2))
'@

$code | & $python -
