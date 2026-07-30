param(
  [string]$PackageRoot = "",
  [int]$Port = 7463
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
if (-not $PackageRoot) {
  throw "PackageRoot is required. Pass the explicit win-unpacked root to smoke-packaged-runtime.ps1."
}

$packagePath = [System.IO.Path]::GetFullPath($PackageRoot)
$resourcesPath = Join-Path $packagePath "resources"
$python = Join-Path $resourcesPath "python-runtime\python.exe"
$backendRoot = Join-Path $resourcesPath "backend"
$ocrManifest = Join-Path $backendRoot "bin\ocr\manifest.json"

if (-not (Test-Path -LiteralPath $packagePath)) {
  throw "Packaged app root not found: $packagePath"
}
if (-not (Test-Path -LiteralPath $python)) {
  throw "Packaged Python runtime not found: $python"
}
if (-not (Test-Path -LiteralPath (Join-Path $backendRoot "app\main.py"))) {
  throw "Packaged backend source not found under $backendRoot"
}
if (-not (Test-Path -LiteralPath $ocrManifest)) {
  throw "Packaged OCR manifest not found: $ocrManifest"
}

$smokeRoot = Join-Path $env:TEMP ("cml-packaged-smoke-" + [guid]::NewGuid().ToString("n"))
$dataDir = Join-Path $smokeRoot "data"
$dbPath = Join-Path $dataDir "cml.sqlite3"
$statusPath = Join-Path $smokeRoot "startup-status.json"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

$ocrProbePath = Join-Path $smokeRoot "ocr_probe.py"
@'
import json
from backend.app.core.ocr import ocr_runtime_status
status = ocr_runtime_status()
print(json.dumps(status, sort_keys=True))
if not status.get("image_ocr_available"):
    raise SystemExit("Packaged image OCR is not available.")
if not status.get("pdf_ocr_available"):
    raise SystemExit("Packaged PDF OCR is not available.")
'@ | Set-Content -LiteralPath $ocrProbePath -Encoding UTF8

$env:PYTHONPATH = $resourcesPath
$env:PYTHONNOUSERSITE = "1"
$env:CML_BACKEND_MODE = "pre_vault"
$env:CML_DATA_DIR = $dataDir
$env:CML_DATABASE_PATH = $dbPath
$env:CML_STARTUP_STATUS_PATH = $statusPath
$env:CML_API_TOKEN = "packaged-smoke-token"

$turbovecJson = & $python -I -c "import json; from turbovec import IdMapIndex; print(json.dumps({'available': IdMapIndex is not None}))"
if ($LASTEXITCODE -ne 0) {
  throw "Packaged TurboVec import probe failed."
}
$turbovecStatus = $turbovecJson | ConvertFrom-Json
if (-not $turbovecStatus.available) {
  throw "Packaged TurboVec runtime is unavailable."
}

$ocrJson = & $python -s $ocrProbePath
if ($LASTEXITCODE -ne 0) {
  throw "Packaged OCR probe failed."
}
$ocrStatus = $ocrJson | ConvertFrom-Json

$process = Start-Process `
  -FilePath $python `
  -ArgumentList @("-s", "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "$Port") `
  -WorkingDirectory $resourcesPath `
  -WindowStyle Hidden `
  -PassThru `
  -RedirectStandardOutput (Join-Path $smokeRoot "backend.stdout.log") `
  -RedirectStandardError (Join-Path $smokeRoot "backend.stderr.log")

try {
  $baseUrl = "http://127.0.0.1:$Port"
  $deadline = (Get-Date).AddSeconds(20)
  $health = $null
  while ((Get-Date) -lt $deadline) {
    try {
      $health = Invoke-RestMethod -Uri "$baseUrl/health" -TimeoutSec 2
      break
    } catch {
      Start-Sleep -Milliseconds 300
    }
  }
  if (-not $health -or $health.status -ne "ok") {
    throw "Packaged backend did not become healthy."
  }

  $blockedWithoutToken = $false
  try {
    Invoke-WebRequest -Uri "$baseUrl/api/v1/vaults" -TimeoutSec 5 | Out-Null
  } catch {
    $blockedWithoutToken = [int]$_.Exception.Response.StatusCode -eq 401
  }
  if (-not $blockedWithoutToken) {
    throw "Packaged backend did not block private API access without the local API token."
  }

  $preVaultBlocked = $false
  try {
    Invoke-WebRequest -Uri "$baseUrl/api/v1/vaults" -Headers @{ "x-cml-api-token" = "packaged-smoke-token" } -TimeoutSec 5 | Out-Null
  } catch {
    $preVaultBlocked = [int]$_.Exception.Response.StatusCode -eq 409
  }
  if (-not $preVaultBlocked) {
    throw "Packaged backend did not enforce pre-vault route restrictions."
  }

  $authHeaders = @{ "x-cml-api-token" = "packaged-smoke-token" }
  $models = Invoke-RestMethod -Uri "$baseUrl/api/v1/models" -Headers $authHeaders -TimeoutSec 5
  if (-not $models -or $models.Count -lt 1) {
    throw "Packaged backend did not return local model setup options."
  }
  $runtimeStatus = Invoke-RestMethod -Uri "$baseUrl/api/v1/models/runtime" -Headers $authHeaders -TimeoutSec 5
  if (-not $runtimeStatus.provider) {
    throw "Packaged backend did not return model runtime status."
  }
  $embeddingStatus = Invoke-RestMethod -Uri "$baseUrl/api/v1/models/embeddings" -Headers $authHeaders -TimeoutSec 5
  if (-not $embeddingStatus.provider) {
    throw "Packaged backend did not return embedding runtime status."
  }
  $hashRejected = $false
  try {
    Invoke-WebRequest `
      -Uri "$baseUrl/api/v1/models/embeddings/configure" `
      -Method Post `
      -Headers $authHeaders `
      -ContentType "application/json" `
      -Body (@{ provider = "hash"; cache_dir = ""; model = "hash" } | ConvertTo-Json) `
      -TimeoutSec 5 | Out-Null
  } catch {
    $hashRejected = [int]$_.Exception.Response.StatusCode -eq 400
  }
  if (-not $hashRejected) {
    throw "Packaged backend allowed hash embeddings without explicit dev mode."
  }
  $embeddingCache = Join-Path $smokeRoot "embedding-cache"
  New-Item -ItemType Directory -Force -Path $embeddingCache | Out-Null
  $configuredEmbedding = Invoke-RestMethod `
    -Uri "$baseUrl/api/v1/models/embeddings/configure" `
    -Method Post `
    -Headers $authHeaders `
    -ContentType "application/json" `
    -Body (@{
      provider = "sentence-transformers"
      cache_dir = $embeddingCache
      model = "sentence-transformers/all-MiniLM-L6-v2"
    } | ConvertTo-Json) `
    -TimeoutSec 10
  if ($configuredEmbedding.provider -ne "sentence-transformers" -or $configuredEmbedding.cache_dir -ne $embeddingCache) {
    throw "Packaged backend did not persist embedding setup configuration."
  }

  try {
    $cors = Invoke-WebRequest `
      -Uri "$baseUrl/health" `
      -Method Options `
      -Headers @{
        Origin = "https://evil.example"
        "Access-Control-Request-Method" = "GET"
      } `
      -TimeoutSec 5
    if ($cors.Headers["Access-Control-Allow-Origin"]) {
      throw "Packaged backend allowed an arbitrary CORS origin."
    }
  } catch {
    $statusCode = [int]$_.Exception.Response.StatusCode
    if ($statusCode -lt 400 -or $statusCode -ge 500) {
      throw
    }
  }

  $status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
  if ($status.status -ne "ready") {
    throw "Packaged backend startup status is not ready: $($status | ConvertTo-Json -Compress)"
  }

  [ordered]@{
    package_root = $packagePath
    python_runtime = $python
    backend_healthy = $true
    private_api_requires_token = $true
    pre_vault_routes_blocked = $true
    arbitrary_cors_origin_blocked = $true
    model_setup_options_available = $true
    model_runtime_status_available = $true
    embedding_setup_status_available = $true
    hash_embeddings_blocked_without_dev_mode = $true
    embedding_cache_configurable = $true
    turbovec_runtime_available = [bool]$turbovecStatus.available
    image_ocr_available = [bool]$ocrStatus.image_ocr_available
    pdf_ocr_available = [bool]$ocrStatus.pdf_ocr_available
    pdf_ocr_engine = $ocrStatus.pdf_ocr_engine
    tesseract_path = $ocrStatus.tesseract_path
    ghostscript_path = $ocrStatus.ghostscript_path
    qpdf_path = $ocrStatus.qpdf_path
  } | ConvertTo-Json -Depth 5
} finally {
  if ($process -and -not $process.HasExited) {
    Stop-Process -Id $process.Id -Force
  }
}
