param(
  [Parameter(Mandatory = $false)]
  [string]$OutputPath = "",
  [Parameter(Mandatory = $false)]
  [switch]$Refresh
)

$refreshLiteral = if ($Refresh) { "True" } else { "False" }

$payload = @"
import json
from backend.app.core.hardware import hardware_status
from backend.app.core.llm_runtime import runtime_status
from backend.app.core.model_registry import active_model_pair_status, list_models, model_recommendations
from backend.app.core.model_recommender.diagnostics import export_recommendation_diagnostics

result = {
    "hardware": hardware_status(),
    "runtime": runtime_status(),
    "active_pair": active_model_pair_status(),
    "models": list_models(),
    "recommendations": model_recommendations(refresh=$refreshLiteral),
    "diagnostics": export_recommendation_diagnostics(refresh=$refreshLiteral),
}
print(json.dumps(result, indent=2))
"@

if ($OutputPath) {
  $directory = Split-Path -Parent $OutputPath
  if ($directory) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
  }
  $payload | .venv\Scripts\python.exe - | Set-Content -Path $OutputPath -Encoding utf8
}
else {
  $payload | .venv\Scripts\python.exe -
}
