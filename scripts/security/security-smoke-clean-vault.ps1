param(
  [string]$ReportPath = "",
  [int]$Port = 7484,
  [string]$Passphrase = "clean-vault-security-passphrase"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  $python = "python"
}

$smokeRoot = Join-Path $env:TEMP ("cml-security-clean-" + [guid]::NewGuid().ToString("n"))
$dataDir = Join-Path $smokeRoot "data"
$vaultRoot = Join-Path $smokeRoot "vault-root"
$fixtureRoot = Join-Path $smokeRoot "fixtures"
$dbPath = Join-Path $dataDir "cml.sqlite3"
$statusPath = Join-Path $smokeRoot "startup-status.json"
$logOut = Join-Path $smokeRoot "backend.stdout.log"
$logErr = Join-Path $smokeRoot "backend.stderr.log"
$apiToken = "clean-vault-security-token"
if (-not $ReportPath) {
  $ReportPath = Join-Path $smokeRoot "security-clean-vault-report.json"
}

New-Item -ItemType Directory -Force -Path $dataDir, $vaultRoot, $fixtureRoot | Out-Null
$notePath = Join-Path $fixtureRoot "clean-security-note.txt"
"CLEAN_VAULT_SECURITY_MARKER bridge approval search smoke" | Set-Content -Path $notePath -Encoding UTF8

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
  throw "Security smoke backend did not become healthy."
}

function Invoke-ApiJson([string]$Method, [string]$Uri, [object]$Payload = $null, [hashtable]$Headers = @{}) {
  $params = @{
    Uri         = $Uri
    Method      = $Method
    Headers     = $Headers
    TimeoutSec  = 60
  }
  if ($null -ne $Payload) {
    $params.ContentType = "application/json"
    $params.Body = ($Payload | ConvertTo-Json -Depth 8)
  }
  return Invoke-RestMethod @params
}

function Get-ResponseStatusCode([scriptblock]$Action) {
  try {
    & $Action | Out-Null
    return 200
  } catch {
    $response = $_.Exception.Response
    if ($response -and $response.StatusCode) {
      return [int]$response.StatusCode.value__
    }
    throw
  }
}

function Wait-DurableJobs([string]$BaseUrl, [hashtable]$Headers, [int]$TimeoutSeconds = 120) {
  Invoke-ApiJson "POST" "$BaseUrl/api/v1/jobs/run-once" $null $Headers | Out-Null
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  do {
    $status = Invoke-ApiJson "GET" "$BaseUrl/api/v1/jobs/status" $null $Headers
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
    name = "Security Clean Vault"
    path = $vaultRoot
  } $headers

  $initialized = Invoke-ApiJson "POST" "$baseUrl/api/v1/system/unlock/initialize" @{
    vault_id = $vault.id
    passphrase = $Passphrase
    unlock_mode = "strict"
  } $headers

  $source = Invoke-ApiJson "POST" "$baseUrl/api/v1/sources/from-path" @{
    vault_id = $vault.id
    path = $notePath
  } $headers

  $reindex = Invoke-ApiJson "POST" "$baseUrl/api/v1/search/reindex/$($vault.id)" $null $headers
  $jobStatus = Wait-DurableJobs $baseUrl $headers
  if ($jobStatus.failed -gt 0) {
    throw "A clean-vault indexing job failed."
  }
  $search = Invoke-ApiJson "POST" "$baseUrl/api/v1/search/semantic" @{
    vault_id = $vault.id
    query = "bridge approval search smoke"
    limit = 5
  } $headers

  $bridgeSettings = Invoke-ApiJson "PATCH" "$baseUrl/api/v1/bridge/settings" @{
    enabled = $true
    allowed_vault_ids = @($vault.id)
    rotate_token = $true
  } $headers

  $approval = Invoke-ApiJson "POST" "$baseUrl/api/v1/bridge/approval-requests" @{
    claimed_name = "Phase14 Smoke Client"
    requested_vault_ids = @($vault.id)
  }

  $approved = Invoke-ApiJson "POST" "$baseUrl/api/v1/bridge/approval-requests/$($approval.request_id)/approve" @{
    detail = "phase14 clean smoke"
  } $headers

  $bridgeContext = Invoke-ApiJson "POST" "$baseUrl/api/v1/bridge/context" @{
    vault_id = $vault.id
    query = "bridge approval search smoke"
    client_name = "Phase14 Smoke Client"
  } @{ "x-cml-bridge-token" = $approved.token }

  $lock = Invoke-ApiJson "POST" "$baseUrl/api/v1/system/unlock/lock?vault_id=$($vault.id)" $null $headers
  $lockedStatus = Get-ResponseStatusCode { Invoke-ApiJson "GET" "$baseUrl/api/v1/sources" $null $headers }

  $unlocked = Invoke-ApiJson "POST" "$baseUrl/api/v1/system/unlock/passphrase" @{
    vault_id = $vault.id
    passphrase = $Passphrase
  } $headers

  Invoke-ApiJson "DELETE" "$baseUrl/api/v1/bridge/clients/$($approved.id)" $null $headers | Out-Null
  $revokedStatus = Get-ResponseStatusCode {
    Invoke-ApiJson "POST" "$baseUrl/api/v1/bridge/context" @{
      vault_id = $vault.id
      query = "bridge approval search smoke"
      client_name = "Phase14 Smoke Client"
    } @{ "x-cml-bridge-token" = $approved.token }
  }

  $report = [ordered]@{
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    smoke_root = $smokeRoot
    vault_id = $vault.id
    source_id = $source.id
    unlock_state = $initialized.state
    reindex_jobs_queued = $reindex.jobs_queued
    jobs_succeeded = $jobStatus.succeeded
    search_results = $search.results.Count
    bridge_request_id = $approval.request_id
    bridge_client_id = $approved.id
    bridge_context_sources = @($bridgeContext.source_snippets).Count
    locked_sources_status = $lockedStatus
    revoked_bridge_status = $revokedStatus
    pass = (
      $initialized.state -eq "ready" -and
      $reindex.jobs_queued -ge 1 -and
      $jobStatus.succeeded -ge $reindex.jobs_queued -and
      $search.results.Count -ge 1 -and
      @($bridgeContext.source_snippets).Count -ge 1 -and
      $lockedStatus -eq 423 -and
      $unlocked.state -eq "ready" -and
      $revokedStatus -ge 400
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
