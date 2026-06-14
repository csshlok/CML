param(
  [Parameter(Mandatory = $true)]
  [string]$SourceRoot,
  [int]$MaxFiles = 1000,
  [int]$Port = 7474,
  [string]$ReportPath = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  $python = "python"
}

$sourcePath = [System.IO.Path]::GetFullPath($SourceRoot)
if (-not (Test-Path -LiteralPath $sourcePath)) {
  throw "User-owned benchmark fixture root does not exist: $sourcePath"
}

$smokeRoot = Join-Path $env:TEMP ("cml-user-owned-benchmark-" + [guid]::NewGuid().ToString("n"))
$dataDir = Join-Path $smokeRoot "data"
$dbPath = Join-Path $dataDir "cml.sqlite3"
$statusPath = Join-Path $smokeRoot "startup-status.json"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

if (-not $ReportPath) {
  $ReportPath = Join-Path $smokeRoot "user-owned-retrieval-benchmark.json"
}

$env:PYTHONPATH = $repoRoot
$env:CML_BACKEND_MODE = "full_vault"
$env:CML_DATA_DIR = $dataDir
$env:CML_DATABASE_PATH = $dbPath
$env:CML_STARTUP_STATUS_PATH = $statusPath
$env:CML_API_TOKEN = "user-owned-benchmark-token"
$env:CML_ALLOW_HASH_EMBEDDINGS = "1"
$env:CML_EMBEDDING_PROVIDER = "hash"

$process = Start-Process `
  -FilePath $python `
  -ArgumentList @("-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "$Port") `
  -WorkingDirectory $repoRoot `
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
    throw "Benchmark backend did not become healthy."
  }

  $headers = @{ "x-cml-api-token" = "user-owned-benchmark-token" }
  $vault = Invoke-RestMethod `
    -Uri "$baseUrl/api/v1/vaults" `
    -Method Post `
    -Headers $headers `
    -ContentType "application/json" `
    -Body (@{ name = "User-owned retrieval benchmark"; path = $sourcePath } | ConvertTo-Json) `
    -TimeoutSec 10

  Invoke-RestMethod `
    -Uri "$baseUrl/api/v1/system/unlock/initialize" `
    -Method Post `
    -Headers $headers `
    -ContentType "application/json" `
    -Body (@{
      vault_id = $vault.id
      passphrase = "user-owned-benchmark-passphrase"
      unlock_mode = "convenience"
    } | ConvertTo-Json) `
    -TimeoutSec 30 | Out-Null

  $scanStarted = Get-Date
  $scan = Invoke-RestMethod `
    -Uri "$baseUrl/api/v1/integrations/local-folder/scan" `
    -Method Post `
    -Headers $headers `
    -ContentType "application/json" `
    -Body (@{ vault_id = $vault.id; path = $sourcePath; max_files = $MaxFiles } | ConvertTo-Json) `
    -TimeoutSec 180
  $scanSeconds = ((Get-Date) - $scanStarted).TotalSeconds

  $refreshStarted = Get-Date
  $refresh = Invoke-RestMethod `
    -Uri "$baseUrl/api/v1/integrations/imports/$($scan.import_id)/refresh?import_files=true&tombstone_missing=true&scan_limit=$MaxFiles" `
    -Method Post `
    -Headers $headers `
    -TimeoutSec 600
  $refreshSeconds = ((Get-Date) - $refreshStarted).TotalSeconds

  $indexStarted = Get-Date
  $index = Invoke-RestMethod `
    -Uri "$baseUrl/api/v1/search/reindex/$($vault.id)" `
    -Method Post `
    -Headers $headers `
    -TimeoutSec 300
  $indexSeconds = ((Get-Date) - $indexStarted).TotalSeconds

  $queries = @(
    "project context release risk",
    "vault ingestion OCR dynamic link",
    "security threat model local token",
    "migration recovery startup repair",
    "query cache evidence retention"
  )

  $queryResults = @()
  foreach ($query in $queries) {
    $started = Get-Date
    $search = Invoke-RestMethod `
      -Uri "$baseUrl/api/v1/search/semantic" `
      -Method Post `
      -Headers $headers `
      -ContentType "application/json" `
      -Body (@{ vault_id = $vault.id; query = $query; limit = 10 } | ConvertTo-Json) `
      -TimeoutSec 30
    $elapsedMs = [math]::Round(((Get-Date) - $started).TotalMilliseconds, 2)
    $queryResults += [ordered]@{
      query = $query
      elapsed_ms = $elapsedMs
      result_count = $search.results.Count
      top_score = if ($search.results.Count) { $search.results[0].score } else { $null }
      top_source = if ($search.results.Count) { $search.results[0].source_title } else { $null }
    }
  }

  $latencies = @($queryResults | ForEach-Object { $_.elapsed_ms } | Sort-Object)
  $p95Index = [math]::Max(0, [math]::Ceiling($latencies.Count * 0.95) - 1)
  $p95 = if ($latencies.Count) { $latencies[$p95Index] } else { $null }

  $report = [ordered]@{
    source_root = $sourcePath
    max_files = $MaxFiles
    supported_count = $scan.supported_count
    imported_count = $refresh.imported_count
    updated_count = $refresh.updated_count
    failed_count = $refresh.failed_count
    chunks_indexed = $index.chunks_indexed
    scan_seconds = [math]::Round($scanSeconds, 2)
    refresh_seconds = [math]::Round($refreshSeconds, 2)
    index_seconds = [math]::Round($indexSeconds, 2)
    query_p95_ms = $p95
    threshold_targets = [ordered]@{
      min_imported_files = [math]::Min(100, $MaxFiles)
      min_indexed_chunks = [math]::Min(100, $MaxFiles)
      max_query_p95_ms = 1500
      max_failed_files = 0
    }
    passed = (
      $refresh.imported_count -ge [math]::Min(100, $MaxFiles) -and
      $index.chunks_indexed -ge [math]::Min(100, $MaxFiles) -and
      ($null -ne $p95 -and $p95 -le 1500) -and
      $refresh.failed_count -eq 0
    )
    queries = $queryResults
    report_path = [System.IO.Path]::GetFullPath($ReportPath)
    smoke_root = $smokeRoot
  }

  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ReportPath) | Out-Null
  $report | ConvertTo-Json -Depth 6 | Set-Content -Path $ReportPath -Encoding UTF8
  $report | ConvertTo-Json -Depth 6
} finally {
  if ($process -and -not $process.HasExited) {
    Stop-Process -Id $process.Id -Force
  }
}
