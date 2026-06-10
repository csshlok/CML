param(
  [string]$Model = "sentence-transformers/all-MiniLM-L6-v2",
  [string]$TargetDir = "",
  [string]$Python = ".venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"

if (-not $TargetDir) {
  $TargetDir = Join-Path $env:LOCALAPPDATA "CML\embeddings"
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$pythonPath = Join-Path $repoRoot $Python
if (-not (Test-Path $pythonPath)) {
  $pythonPath = $Python
}

New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null

Write-Host "Installing SentenceTransformers dependency if needed..."
& $pythonPath -m pip install "sentence-transformers==5.5.1"

Write-Host "Downloading embedding model $Model to $TargetDir..."
$env:CML_EMBEDDING_CACHE_DIR = $TargetDir
& $pythonPath -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('$Model', cache_folder=r'$TargetDir'); print('embedding model ready')"

Write-Host ""
Write-Host "To use this model in CML, set:"
Write-Host "CML_EMBEDDING_PROVIDER=sentence-transformers"
Write-Host "CML_EMBEDDING_MODEL=$Model"
Write-Host "CML_EMBEDDING_CACHE_DIR=$TargetDir"
