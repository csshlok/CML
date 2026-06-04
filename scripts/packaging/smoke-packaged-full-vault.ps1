param(
  [string]$PackageRoot = "",
  [int]$Port = 7464,
  [string]$OcrImagePath = "",
  [string]$OcrPdfPath = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
if (-not $PackageRoot) {
  $PackageRoot = Join-Path $repoRoot "apps\desktop\release\win-unpacked"
}

$packagePath = [System.IO.Path]::GetFullPath($PackageRoot)
$resourcesPath = Join-Path $packagePath "resources"
$python = Join-Path $resourcesPath "python-runtime\Scripts\python.exe"
$backendRoot = Join-Path $resourcesPath "backend"

if (-not (Test-Path -LiteralPath $python)) {
  throw "Packaged Python runtime not found: $python"
}
if (-not (Test-Path -LiteralPath (Join-Path $backendRoot "app\main.py"))) {
  throw "Packaged backend source not found under $backendRoot"
}

$smokeRoot = Join-Path $env:TEMP ("cml-packaged-full-vault-" + [guid]::NewGuid().ToString("n"))
$dataDir = Join-Path $smokeRoot "data"
$dbPath = Join-Path $dataDir "cml.sqlite3"
$statusPath = Join-Path $smokeRoot "startup-status.json"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

function New-OcrImageFixture {
  param([string]$Path)

  Add-Type -AssemblyName System.Drawing
  $bitmap = New-Object System.Drawing.Bitmap 1200, 360
  $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
  try {
    $graphics.Clear([System.Drawing.Color]::White)
    $font = New-Object System.Drawing.Font("Arial", 34, [System.Drawing.FontStyle]::Regular)
    try {
      $brush = [System.Drawing.Brushes]::Black
      $graphics.DrawString("CML packaged OCR fixture alpha 2026", $font, $brush, 36, 92)
      $graphics.DrawString("local vault ingestion text extraction", $font, $brush, 36, 174)
      $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    } finally {
      $font.Dispose()
    }
  } finally {
    $graphics.Dispose()
    $bitmap.Dispose()
  }
}

function New-OcrPdfFixture {
  param(
    [string]$ImagePath,
    [string]$PdfPath,
    [string]$PythonPath
  )

  $code = @'
import fitz
import sys

image_path, pdf_path = sys.argv[1], sys.argv[2]
doc = fitz.open()
page = doc.new_page(width=1200, height=360)
page.insert_image(fitz.Rect(0, 0, 1200, 360), filename=image_path)
doc.save(pdf_path)
'@
  $code | & $PythonPath - $ImagePath $PdfPath
  if ($LASTEXITCODE -ne 0) {
    throw "Could not generate OCR PDF fixture with packaged Python."
  }
}

function Ensure-OcrFixtures {
  param(
    [string]$FixtureRoot,
    [string]$PythonPath
  )

  New-Item -ItemType Directory -Force -Path $FixtureRoot | Out-Null
  $generatedImage = Join-Path $FixtureRoot "packaged-ocr-image.png"
  $generatedPdf = Join-Path $FixtureRoot "packaged-ocr-scanned.pdf"
  if (-not $OcrImagePath) {
    New-OcrImageFixture -Path $generatedImage
    $script:OcrImagePath = $generatedImage
  }
  if (-not $OcrPdfPath) {
    New-OcrPdfFixture -ImagePath $script:OcrImagePath -PdfPath $generatedPdf -PythonPath $PythonPath
    $script:OcrPdfPath = $generatedPdf
  }
}

Ensure-OcrFixtures -FixtureRoot (Join-Path $smokeRoot "fixtures") -PythonPath $python

$env:PYTHONPATH = $resourcesPath
$env:CML_BACKEND_MODE = "full_vault"
$env:CML_DATA_DIR = $dataDir
$env:CML_DATABASE_PATH = $dbPath
$env:CML_STARTUP_STATUS_PATH = $statusPath
$env:CML_API_TOKEN = "packaged-full-vault-token"
$env:CML_ALLOW_HASH_EMBEDDINGS = "1"
$env:CML_EMBEDDING_PROVIDER = "hash"

$process = Start-Process `
  -FilePath $python `
  -ArgumentList @("-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "$Port") `
  -WorkingDirectory $resourcesPath `
  -WindowStyle Hidden `
  -PassThru `
  -RedirectStandardOutput (Join-Path $smokeRoot "backend.stdout.log") `
  -RedirectStandardError (Join-Path $smokeRoot "backend.stderr.log")

try {
  $baseUrl = "http://127.0.0.1:$Port"
  $deadline = (Get-Date).AddSeconds(25)
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
    throw "Packaged full-vault backend did not become healthy."
  }

  $headers = @{ "x-cml-api-token" = "packaged-full-vault-token" }
  $vault = Invoke-RestMethod `
    -Uri "$baseUrl/api/v1/vaults" `
    -Method Post `
    -Headers $headers `
    -ContentType "application/json" `
    -Body (@{ name = "Packaged Smoke Vault"; path = $smokeRoot } | ConvertTo-Json) `
    -TimeoutSec 10

  $source = Invoke-RestMethod `
    -Uri "$baseUrl/api/v1/sources/from-text" `
    -Method Post `
    -Headers $headers `
    -ContentType "application/json" `
    -Body (@{
      vault_id = $vault.id
      title = "Packaged full-vault smoke source"
      text = ((1..40 | ForEach-Object { "packaged full vault semantic retrieval diagnostics query cache evidence" }) -join " ")
    } | ConvertTo-Json) `
    -TimeoutSec 10

  $reindex = Invoke-RestMethod -Uri "$baseUrl/api/v1/search/reindex/$($vault.id)" -Method Post -Headers $headers -TimeoutSec 15
  if ($reindex.chunks_indexed -lt 1) {
    throw "Packaged full-vault reindex did not create source chunks."
  }

  $search = Invoke-RestMethod `
    -Uri "$baseUrl/api/v1/search/semantic" `
    -Method Post `
    -Headers $headers `
    -ContentType "application/json" `
    -Body (@{ vault_id = $vault.id; query = "semantic retrieval diagnostics"; limit = 5 } | ConvertTo-Json) `
    -TimeoutSec 10
  if (-not $search.results -or $search.results.Count -lt 1) {
    throw "Packaged full-vault semantic search returned no results."
  }

  $ocrFixtures = @()
  foreach ($fixture in @($OcrImagePath, $OcrPdfPath)) {
    if ($fixture -and (Test-Path -LiteralPath $fixture)) {
      $ocrSource = Invoke-RestMethod `
        -Uri "$baseUrl/api/v1/sources/from-path" `
        -Method Post `
        -Headers $headers `
        -ContentType "application/json" `
        -Body (@{ vault_id = $vault.id; path = ([System.IO.Path]::GetFullPath($fixture)) } | ConvertTo-Json) `
        -TimeoutSec 60
      $ocrFixtures += [ordered]@{
        path = $fixture
        source_id = $ocrSource.id
        source_type = $ocrSource.source_type
        extracted = [bool]$ocrSource.extracted_text
        extracted_length = ($ocrSource.extracted_text | Measure-Object -Character).Characters
      }
      if (-not $ocrSource.extracted_text -or $ocrSource.extracted_text -notmatch "CML|vault|ingestion|fixture") {
        throw "OCR fixture did not produce expected readable text: $fixture"
      }
    }
  }
  if ($ocrFixtures.Count -lt 2) {
    throw "Packaged full-vault smoke did not exercise both generated OCR fixtures."
  }

  $cache = Invoke-RestMethod `
    -Uri "$baseUrl/api/v1/search/query-cache?vault_id=$($vault.id)&query_fingerprint=full-vault-smoke&source_ids=$($source.id)" `
    -Method Post `
    -Headers $headers `
    -TimeoutSec 10
  if (-not $cache.id) {
    throw "Packaged full-vault query cache write failed."
  }

  $prune = Invoke-RestMethod `
    -Uri "$baseUrl/api/v1/search/query-cache/prune?vault_id=$($vault.id)&max_age_days=30&max_items=50&max_payload_bytes=500000" `
    -Method Post `
    -Headers $headers `
    -TimeoutSec 10

  $startupPhases = Invoke-RestMethod -Uri "$baseUrl/api/v1/system/startup-phases" -Headers $headers -TimeoutSec 10
  if (-not $startupPhases.registry.ok) {
    throw "Startup phase registry validation failed in packaged full-vault smoke."
  }

  $diagnostics = Invoke-RestMethod -Uri "$baseUrl/api/v1/diagnostics/bundle" -Method Post -Headers $headers -TimeoutSec 15
  if (-not (Test-Path -LiteralPath $diagnostics.bundle_path)) {
    throw "Packaged full-vault diagnostic bundle was not written."
  }

  [ordered]@{
    package_root = $packagePath
    vault_id = $vault.id
    source_id = $source.id
    chunks_indexed = $reindex.chunks_indexed
    semantic_results = $search.results.Count
    ocr_fixtures = $ocrFixtures
    query_cache_prune = $prune
    startup_phase_registry_ok = $startupPhases.registry.ok
    diagnostic_bundle_path = $diagnostics.bundle_path
    smoke_root = $smokeRoot
  } | ConvertTo-Json -Depth 6
} finally {
  if ($process -and -not $process.HasExited) {
    Stop-Process -Id $process.Id -Force
  }
}
