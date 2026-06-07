param(
  [string]$ReportPath = "",
  [int]$Port = 7486,
  [string]$Passphrase = "offline-at-rest-passphrase",
  [string]$Marker = "OFFLINE_VAULT_SECRET_MARKER"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  $python = "python"
}

$smokeRoot = Join-Path $env:TEMP ("cml-security-offline-" + [guid]::NewGuid().ToString("n"))
$dataDir = Join-Path $smokeRoot "data"
$vaultRoot = Join-Path $smokeRoot "vault-root"
$fixtureRoot = Join-Path $smokeRoot "fixtures"
$dbPath = Join-Path $dataDir "cml.sqlite3"
$statusPath = Join-Path $smokeRoot "startup-status.json"
$logOut = Join-Path $smokeRoot "backend.stdout.log"
$logErr = Join-Path $smokeRoot "backend.stderr.log"
$apiToken = "offline-at-rest-token"
if (-not $ReportPath) {
  $ReportPath = Join-Path $smokeRoot "offline-at-rest-report.json"
}

New-Item -ItemType Directory -Force -Path $dataDir, $vaultRoot, $fixtureRoot | Out-Null
$filePath = Join-Path $fixtureRoot "offline-secret.txt"
"$Marker bridge capture encrypted blob check" | Set-Content -Path $filePath -Encoding UTF8

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
  throw "Offline-at-rest backend did not become healthy."
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

try {
  $baseUrl = "http://127.0.0.1:$Port"
  $headers = @{ "x-cml-api-token" = $apiToken }
  Wait-BackendReady $baseUrl

  $vault = Invoke-ApiJson "POST" "$baseUrl/api/v1/vaults" @{
    name = "Offline Vault"
    path = $vaultRoot
  } $headers

  Invoke-ApiJson "POST" "$baseUrl/api/v1/system/unlock/initialize" @{
    vault_id = $vault.id
    passphrase = $Passphrase
    unlock_mode = "convenience"
  } $headers | Out-Null

  $source = Invoke-ApiJson "POST" "$baseUrl/api/v1/sources/from-path" @{
    vault_id = $vault.id
    path = $filePath
  } $headers
  Invoke-ApiJson "POST" "$baseUrl/api/v1/search/reindex/$($vault.id)" $null $headers 300 | Out-Null
} finally {
  if ($process -and -not $process.HasExited) {
    Stop-Process -Id $process.Id -Force
  }
}

$hits = @()
$scanRoots = @($dataDir)
foreach ($root in $scanRoots) {
  if (-not (Test-Path -LiteralPath $root)) {
    continue
  }
  $files = Get-ChildItem -LiteralPath $root -Recurse -File -ErrorAction SilentlyContinue
  foreach ($file in $files) {
    try {
      $match = Select-String -LiteralPath $file.FullName -Pattern [regex]::Escape($Marker) -SimpleMatch -Quiet -Encoding UTF8 -ErrorAction SilentlyContinue
      if ($match) {
        $hits += $file.FullName
      }
    } catch {
    }
  }
}

$report = [ordered]@{
  generated_at = (Get-Date).ToUniversalTime().ToString("o")
  smoke_root = $smokeRoot
  data_dir = $dataDir
  marker = $Marker
  hit_count = $hits.Count
  hits = $hits
  pass = $hits.Count -eq 0
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ReportPath) | Out-Null
$report | ConvertTo-Json -Depth 6 | Set-Content -Path $ReportPath -Encoding UTF8
$report | ConvertTo-Json -Depth 6
