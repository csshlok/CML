param(
  [string]$ReportPath = "",
  [int]$Port = 7487,
  [string]$Passphrase = "interrupted-flow-passphrase"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  $python = "python"
}

$smokeRoot = Join-Path $env:TEMP ("cml-security-drill-" + [guid]::NewGuid().ToString("n"))
$dataDir = Join-Path $smokeRoot "data"
$vaultRoot = Join-Path $smokeRoot "vault-root"
$dbPath = Join-Path $dataDir "cml.sqlite3"
$statusPath = Join-Path $smokeRoot "startup-status.json"
$logOut = Join-Path $smokeRoot "backend.stdout.log"
$logErr = Join-Path $smokeRoot "backend.stderr.log"
$apiToken = "interrupted-flow-token"
if (-not $ReportPath) {
  $ReportPath = Join-Path $smokeRoot "security-drill-report.json"
}

New-Item -ItemType Directory -Force -Path $dataDir, $vaultRoot | Out-Null

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
  throw "Interrupted-flow drill backend did not become healthy."
}

function Invoke-ApiJson([string]$Method, [string]$Uri, [object]$Payload = $null, [hashtable]$Headers = @{}, [int]$Timeout = 120) {
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

try {
  $baseUrl = "http://127.0.0.1:$Port"
  $headers = @{ "x-cml-api-token" = $apiToken }
  Wait-BackendReady $baseUrl

  $vault = Invoke-ApiJson "POST" "$baseUrl/api/v1/vaults" @{
    name = "Interrupted Flow Drill"
    path = $vaultRoot
  } $headers

  $initialized = Invoke-ApiJson "POST" "$baseUrl/api/v1/system/unlock/initialize" @{
    vault_id = $vault.id
    passphrase = $Passphrase
    unlock_mode = "strict"
  } $headers

  $drillsBefore = Invoke-ApiJson "GET" "$baseUrl/api/v1/system/recovery-drills" $null $headers
  $lock = Invoke-ApiJson "POST" "$baseUrl/api/v1/system/unlock/lock?vault_id=$($vault.id)" $null $headers
  $blockedStatus = Get-ResponseStatusCode { Invoke-ApiJson "POST" "$baseUrl/api/v1/jobs/run-once" $null $headers }
  $unlocked = Invoke-ApiJson "POST" "$baseUrl/api/v1/system/unlock/passphrase" @{
    vault_id = $vault.id
    passphrase = $Passphrase
  } $headers
  $repair = Invoke-ApiJson "GET" "$baseUrl/api/v1/system/startup-repair" $null $headers
  $drillsAfter = Invoke-ApiJson "GET" "$baseUrl/api/v1/system/recovery-drills?apply_recovery=false" $null $headers

  $report = [ordered]@{
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    smoke_root = $smokeRoot
    unlock_state = $initialized.state
    locked_jobs_status = $blockedStatus
    unlocked_state = $unlocked.state
    drill_passes_before = $drillsBefore.passes_drill
    drill_passes_after = $drillsAfter.passes_drill
    startup_repair_issue_count = $repair.issues.Count
    pass = (
      $initialized.state -eq "ready" -and
      $blockedStatus -eq 423 -and
      $unlocked.state -eq "ready" -and
      $drillsBefore.passes_drill -eq $true -and
      $drillsAfter.passes_drill -eq $true -and
      $repair.issues.Count -eq 0
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
