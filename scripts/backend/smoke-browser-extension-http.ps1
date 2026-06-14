param(
  [string]$ReportPath = "",
  [int]$Port = 7486
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  $python = "python"
}

$smokeRoot = Join-Path $env:TEMP ("cml-extension-http-smoke-" + [guid]::NewGuid().ToString("n"))
$dataDir = Join-Path $smokeRoot "data"
$vaultRoot = Join-Path $smokeRoot "vault-root"
$dbPath = Join-Path $dataDir "cml.sqlite3"
$statusPath = Join-Path $smokeRoot "startup-status.json"
$logOut = Join-Path $smokeRoot "backend.stdout.log"
$logErr = Join-Path $smokeRoot "backend.stderr.log"
$apiToken = "extension-http-smoke-token"
if (-not $ReportPath) {
  $ReportPath = Join-Path $smokeRoot "extension-http-smoke-report.json"
}

New-Item -ItemType Directory -Force -Path $dataDir, $vaultRoot | Out-Null

$env:PYTHONPATH = $repoRoot
$env:CML_BACKEND_MODE = "full_vault"
$env:CML_DATA_DIR = $dataDir
$env:CML_DATABASE_PATH = $dbPath
$env:CML_STARTUP_STATUS_PATH = $statusPath
$env:CML_API_TOKEN = $apiToken
$env:CML_ALLOW_UNAUTHENTICATED_API = "0"
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
  throw "Browser extension HTTP smoke backend did not become healthy."
}

function Invoke-ApiJson([string]$Method, [string]$Uri, [object]$Payload = $null, [hashtable]$Headers = @{}) {
  $params = @{
    Uri        = $Uri
    Method     = $Method
    Headers    = $Headers
    TimeoutSec = 60
  }
  if ($null -ne $Payload) {
    $params.ContentType = "application/json"
    $params.Body = ($Payload | ConvertTo-Json -Depth 8)
  }
  return Invoke-RestMethod @params
}

try {
  $baseUrl = "http://127.0.0.1:$Port"
  $adminHeaders = @{ "x-cml-api-token" = $apiToken }
  Wait-BackendReady $baseUrl

  $vault = Invoke-ApiJson "POST" "$baseUrl/api/v1/vaults" @{
    name = "Extension HTTP Smoke Vault"
    path = $vaultRoot
  } $adminHeaders

  $unlock = Invoke-ApiJson "POST" "$baseUrl/api/v1/system/unlock/initialize" @{
    vault_id = $vault.id
    passphrase = "extension-http-smoke-passphrase"
    unlock_mode = "convenience"
  } $adminHeaders

  $extensionClient = Invoke-ApiJson "POST" "$baseUrl/api/v1/extension/clients" @{
    name = "HTTP smoke browser extension"
    allowed_vault_ids = @($vault.id)
  } $adminHeaders

  $extensionHeaders = @{ "x-cml-extension-token" = $extensionClient.token }

  $status = Invoke-ApiJson "GET" "$baseUrl/api/v1/extension/status" $null $extensionHeaders

  $capture = Invoke-ApiJson "POST" "$baseUrl/api/v1/extension/capture" @{
    vault_id = $vault.id
    capture_type = "selection"
    title = "Saved selection"
    url = "https://example.com/article"
    text = "Captured selection through the live extension HTTP contract."
  } $extensionHeaders

  $upload = Invoke-ApiJson "POST" "$baseUrl/api/v1/extension/capture-upload" @{
    vault_id = $vault.id
    capture_type = "file"
    title = "notes.txt"
    file_name = "notes.txt"
    mime_type = "text/plain"
    content_base64 = "bm90ZXMgdmlhIGxpdmUgZXh0ZW5zaW9uIEhUVFAgY29udHJhY3Q="
  } $extensionHeaders

  $captures = Invoke-ApiJson "GET" "$baseUrl/api/v1/extension/captures?vault_id=$($vault.id)" $null $adminHeaders
  $selectionSource = Invoke-ApiJson "GET" "$baseUrl/api/v1/sources/$($capture.source_id)" $null $adminHeaders
  $uploadSource = Invoke-ApiJson "GET" "$baseUrl/api/v1/sources/$($upload.source_id)" $null $adminHeaders

  $report = [ordered]@{
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    smoke_root = $smokeRoot
    backend_ready = $true
    unlock_state = $unlock.state
    extension_client_id = $extensionClient.id
    extension_status_ok = [bool]$status.ok
    capture_status = $capture.status
    upload_status = $upload.status
    capture_count = @($captures).Count
    selection_source_type = $selectionSource.source_type
    upload_source_type = $uploadSource.source_type
    pass = (
      $unlock.state -eq "ready" -and
      [bool]$status.ok -and
      $capture.status -eq "stored" -and
      $upload.status -eq "stored" -and
      @($captures).Count -ge 2 -and
      $selectionSource.source_type -eq "extension_selection" -and
      $uploadSource.source_type -eq "extension_note"
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
