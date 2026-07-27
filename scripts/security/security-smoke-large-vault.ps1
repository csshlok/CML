param(
  [string]$ReportPath = "",
  [int]$Port = 7485,
  [int]$Sources = 2000,
  [string]$Passphrase = "large-vault-security-passphrase"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  $python = "python"
}

$smokeRoot = Join-Path $env:TEMP ("cml-security-large-" + [guid]::NewGuid().ToString("n"))
$dataDir = Join-Path $smokeRoot "data"
$vaultRoot = Join-Path $smokeRoot "vault-root"
$fixtureRoot = Join-Path $smokeRoot "fixtures"
$dbPath = Join-Path $dataDir "cml.sqlite3"
$statusPath = Join-Path $smokeRoot "startup-status.json"
$logOut = Join-Path $smokeRoot "backend.stdout.log"
$logErr = Join-Path $smokeRoot "backend.stderr.log"
$apiToken = "large-vault-security-token"
if (-not $ReportPath) {
  $ReportPath = Join-Path $smokeRoot "security-large-vault-report.json"
}

New-Item -ItemType Directory -Force -Path $dataDir, $vaultRoot, $fixtureRoot | Out-Null
for ($index = 1; $index -le $Sources; $index++) {
  $content = "SECURITY LARGE VAULT FILE $index `nRepeated content for scale and retrieval safety checks. " * 4
  Set-Content -Path (Join-Path $fixtureRoot ("doc-{0:d4}.md" -f $index)) -Value $content -Encoding UTF8
}

$env:PYTHONPATH = $repoRoot
$env:CML_BACKEND_MODE = "full_vault"
$env:CML_DATA_DIR = $dataDir
$env:CML_DATABASE_PATH = $dbPath
$env:CML_STARTUP_STATUS_PATH = $statusPath
$env:CML_API_TOKEN = $apiToken
$env:CML_ALLOW_HASH_EMBEDDINGS = "1"
$env:CML_EMBEDDING_PROVIDER = "hash"

$process = Start-Process `
  -FilePath $python `
  -ArgumentList @("-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "$Port") `
  -WorkingDirectory $repoRoot `
  -WindowStyle Hidden `
  -PassThru `
  -RedirectStandardOutput $logOut `
  -RedirectStandardError $logErr

function Wait-BackendReady([string]$BaseUrl) {
  $deadline = (Get-Date).AddSeconds(25)
  while ((Get-Date) -lt $deadline) {
    try {
      $health = Invoke-RestMethod -Uri "$BaseUrl/health" -TimeoutSec 2
      if ($health.status -eq "ok") {
        return
      }
    } catch {
      Start-Sleep -Milliseconds 300
    }
  }
  throw "Large-vault security smoke backend did not become healthy."
}

function Invoke-ApiJson([string]$Method, [string]$Uri, [object]$Payload = $null, [hashtable]$Headers = @{}, [int]$Timeout = 300) {
  $params = @{
    Uri         = $Uri
    Method      = $Method
    Headers     = $Headers
    TimeoutSec  = $Timeout
  }
  if ($null -ne $Payload) {
    $params.ContentType = "application/json"
    $params.Body = ($Payload | ConvertTo-Json -Depth 8)
  }
  return Invoke-RestMethod @params
}

function Wait-DurableJobs([string]$BaseUrl, [hashtable]$Headers, [int]$TimeoutSeconds = 900) {
  Invoke-ApiJson "POST" "$BaseUrl/api/v1/jobs/run-once" $null $Headers 30 | Out-Null
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  do {
    $status = Invoke-ApiJson "GET" "$BaseUrl/api/v1/jobs/status" $null $Headers 30
    if ($status.queued -eq 0 -and $status.running -eq 0) {
      return $status
    }
    Start-Sleep -Milliseconds 250
  } while ((Get-Date) -lt $deadline)
  throw "Durable jobs did not finish within $TimeoutSeconds seconds."
}

try {
  $baseUrl = "http://127.0.0.1:$Port"
  $headers = @{ "x-cml-api-token" = $apiToken }
  Wait-BackendReady $baseUrl

  $vault = Invoke-ApiJson "POST" "$baseUrl/api/v1/vaults" @{
    name = "Large Security Vault"
    path = $vaultRoot
  } $headers

  Invoke-ApiJson "POST" "$baseUrl/api/v1/system/unlock/initialize" @{
    vault_id = $vault.id
    passphrase = $Passphrase
    unlock_mode = "strict"
  } $headers | Out-Null

  $scanStarted = Get-Date
  $scan = Invoke-ApiJson "POST" "$baseUrl/api/v1/integrations/local-folder/scan" @{
    vault_id = $vault.id
    path = $fixtureRoot
    max_files = $Sources
  } $headers 300
  $scanSeconds = ((Get-Date) - $scanStarted).TotalSeconds

  $refreshStarted = Get-Date
  $refresh = Invoke-ApiJson "POST" "$baseUrl/api/v1/integrations/imports/$($scan.import_id)/refresh?import_files=true&tombstone_missing=true" $null $headers 1200
  $refreshSeconds = ((Get-Date) - $refreshStarted).TotalSeconds

  $reindexStarted = Get-Date
  $reindex = Invoke-ApiJson "POST" "$baseUrl/api/v1/search/reindex/$($vault.id)" $null $headers 900
  $jobStatus = Wait-DurableJobs $baseUrl $headers
  $reindexSeconds = ((Get-Date) - $reindexStarted).TotalSeconds
  if ($jobStatus.failed -gt 0) {
    throw "A large-vault indexing job failed."
  }

  $queryStarted = Get-Date
  $search = Invoke-ApiJson "POST" "$baseUrl/api/v1/search/semantic" @{
    vault_id = $vault.id
    query = "Repeated content retrieval safety"
    limit = 10
  } $headers 60
  $queryMs = [math]::Round(((Get-Date) - $queryStarted).TotalMilliseconds, 2)

  $runs = Invoke-ApiJson "GET" "$baseUrl/api/v1/integrations/imports/$($scan.import_id)/reconciliation-runs?limit=3" $null $headers 60

  $report = [ordered]@{
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    smoke_root = $smokeRoot
    sources = $Sources
    supported_count = $scan.supported_count
    imported_count = $refresh.imported_count
    failed_count = $refresh.failed_count
    reindex_jobs_queued = $reindex.jobs_queued
    jobs_succeeded = $jobStatus.succeeded
    scan_seconds = [math]::Round($scanSeconds, 2)
    refresh_seconds = [math]::Round($refreshSeconds, 2)
    reindex_seconds = [math]::Round($reindexSeconds, 2)
    query_ms = $queryMs
    reconciliation_status = if ($runs.Count -gt 0) { $runs[0].status } else { $null }
    reconciliation_detail_count = if ($runs.Count -gt 0) { $runs[0].detail_count } else { 0 }
    pass = (
      $scan.supported_count -eq $Sources -and
      $refresh.imported_count -eq $Sources -and
      $refresh.failed_count -eq 0 -and
      $reindex.jobs_queued -ge $Sources -and
      $jobStatus.succeeded -ge $reindex.jobs_queued -and
      $search.results.Count -ge 1 -and
      $runs.Count -ge 1 -and
      $runs[0].detail_count -ge [math]::Min($Sources, 2000)
    )
  }

  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ReportPath) | Out-Null
  $report | ConvertTo-Json -Depth 6 | Set-Content -Path $ReportPath -Encoding UTF8
  $report | ConvertTo-Json -Depth 6
} finally {
  if ($process -and -not $process.HasExited) {
    Stop-Process -Id $process.Id -Force
  }
}
