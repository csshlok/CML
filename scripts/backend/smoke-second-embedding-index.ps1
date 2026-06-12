param(
  [string]$PrimaryModel = "sentence-transformers/all-MiniLM-L6-v2",
  [string]$SecondaryModel = "sentence-transformers/paraphrase-MiniLM-L3-v2",
  [string]$CacheRoot = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}

if (-not $CacheRoot) {
  $CacheRoot = Join-Path $env:TEMP "cml-embedding-index-smoke"
}

$code = @'
import json
import os
from pathlib import Path

from backend.app.core.embeddings import configure_embedding_runtime, embedding_status, embed_text
from backend.app.core.vector_maintenance import activate_embedding_index, begin_embedding_index_transition, embedding_index_policy

primary = os.environ["CML_PRIMARY_EMBEDDING_MODEL"]
secondary = os.environ["CML_SECONDARY_EMBEDDING_MODEL"]
cache_root = Path(os.environ["CML_EMBEDDING_INDEX_CACHE"])
primary_cache = cache_root / "primary"
secondary_cache = cache_root / "secondary"
primary_cache.mkdir(parents=True, exist_ok=True)
secondary_cache.mkdir(parents=True, exist_ok=True)

results = {"primary_model": primary, "secondary_model": secondary, "cache_root": str(cache_root)}
for label, model, cache in (("primary", primary, primary_cache), ("secondary", secondary, secondary_cache)):
    try:
        from sentence_transformers import SentenceTransformer

        SentenceTransformer(model, cache_folder=str(cache))
        configure_embedding_runtime("sentence-transformers", str(cache), model)
        vector = embed_text(f"{label} embedding smoke")
        results[label] = {"available": True, "dimensions": len(vector), "status": embedding_status()}
    except Exception as exc:
        results[label] = {"available": False, "error": str(exc)}

building = begin_embedding_index_transition(secondary)
active = activate_embedding_index(secondary, "v2-real-cache-smoke")
results["transition"] = {"building": building, "active": active, "after": embedding_index_policy()}
results["real_second_cache_observed"] = results.get("secondary", {}).get("available") is True
print(json.dumps(results, indent=2))
'@

$env:CML_PRIMARY_EMBEDDING_MODEL = $PrimaryModel
$env:CML_SECONDARY_EMBEDDING_MODEL = $SecondaryModel
$env:CML_EMBEDDING_INDEX_CACHE = $CacheRoot
$code | & $python -
