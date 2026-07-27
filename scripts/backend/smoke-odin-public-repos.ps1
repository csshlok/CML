param(
  [string]$WorkRoot = "",
  [int]$Port = 7354
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  throw "The project Python runtime is missing: $python"
}
if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
  throw "curl.exe is required for the public-repository Odin smoke test."
}
if (-not $WorkRoot) {
  $WorkRoot = Join-Path $repoRoot ("tmp\odin-public-smoke-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
}
$work = [IO.Path]::GetFullPath($WorkRoot)
New-Item -ItemType Directory -Force -Path $work | Out-Null
$reposRoot = Join-Path $work "repos"
New-Item -ItemType Directory -Force -Path $reposRoot | Out-Null

$fixtures = @(
  @{
    name = "itsdangerous"
    url = "https://github.com/pallets/itsdangerous.git"
    archive = "https://codeload.github.com/pallets/itsdangerous/zip/672971d66a2ef9f85151e53283113f33d642dabd"
    commit = "672971d66a2ef9f85151e53283113f33d642dabd"
    query = "serializer signing"
  },
  @{
    name = "yoctocolors"
    url = "https://github.com/sindresorhus/yoctocolors.git"
    archive = "https://codeload.github.com/sindresorhus/yoctocolors/zip/a02a16ec36fbd58a0848e95598fb4913c54c7591"
    commit = "a02a16ec36fbd58a0848e95598fb4913c54c7591"
    query = "terminal color support"
  }
)

foreach ($fixture in $fixtures) {
  $target = Join-Path $reposRoot $fixture.name
  $archive = Join-Path $work ($fixture.name + ".zip")
  & curl.exe -L --fail --silent --show-error --max-time 60 -o $archive $fixture.archive
  if ($LASTEXITCODE -ne 0) {
    throw "Could not download $($fixture.archive)."
  }
  $expanded = Join-Path $work ("expanded-" + $fixture.name)
  Expand-Archive -LiteralPath $archive -DestinationPath $expanded
  $source = Get-ChildItem -LiteralPath $expanded -Directory | Select-Object -First 1
  if (-not $source) {
    throw "The source archive for $($fixture.name) was empty."
  }
  Move-Item -LiteralPath $source.FullName -Destination $target
}

function Get-TreeFingerprint([string]$Root) {
  $normalizedRoot = [IO.Path]::GetFullPath($Root).TrimEnd("\")
  $lines = Get-ChildItem -LiteralPath $Root -Recurse -File |
    Sort-Object FullName |
    ForEach-Object {
      $relative = $_.FullName.Substring($normalizedRoot.Length + 1).Replace("\", "/")
      $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
      "$relative`:$hash"
  }
  $bytes = [Text.Encoding]::UTF8.GetBytes(($lines -join "`n"))
  $sha256 = [Security.Cryptography.SHA256]::Create()
  try {
    return ([BitConverter]::ToString($sha256.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
  } finally {
    $sha256.Dispose()
  }
}

$token = "odin-public-smoke-" + ("x" * 48)
$dataDir = Join-Path $work "data"
$databasePath = Join-Path $work "odin.sqlite3"
$runtimeFile = Join-Path $work "odin-runtime.json"
$vaultPath = Join-Path $work "vault"
New-Item -ItemType Directory -Force -Path $vaultPath | Out-Null

$savedEnvironment = @{}
$environment = @{
  CML_API_TOKEN = $token
  CML_API_PREFIX = "/api/v1"
  CML_DATABASE_PATH = $databasePath
  CML_DATA_DIR = $dataDir
  CML_EMBEDDING_PROVIDER = "hash"
  CML_ALLOW_HASH_EMBEDDINGS = "1"
  CML_LLM_PROVIDER = "none"
  ODIN_RUNTIME_FILE = $runtimeFile
  ODIN_API_TOKEN = $token
  ODIN_ALLOW_DEVELOPMENT_TOKEN = "1"
}
foreach ($entry in $environment.GetEnumerator()) {
  $savedEnvironment[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key, "Process")
  [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process")
}

$backend = $null
try {
  $backendStdout = Join-Path $work "backend.stdout.log"
  $backendStderr = Join-Path $work "backend.stderr.log"
  $backend = Start-Process -FilePath $python `
    -ArgumentList @("-s", "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "$Port") `
    -WorkingDirectory $repoRoot -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $backendStdout -RedirectStandardError $backendStderr
  $baseUrl = "http://127.0.0.1:$Port"
  $headers = @{ "X-CML-API-Token" = $token }
  $ready = $false
  for ($attempt = 0; $attempt -lt 120; $attempt++) {
    if ($backend.HasExited) {
      throw "The Odin smoke backend exited before it became ready."
    }
    try {
      Invoke-RestMethod -Uri "$baseUrl/health" -TimeoutSec 1 | Out-Null
      $ready = $true
      break
    } catch {
      Start-Sleep -Milliseconds 250
    }
  }
  if (-not $ready) {
    throw "The Odin smoke backend did not become ready."
  }

  $identity = Invoke-RestMethod -Uri "$baseUrl/api/v1/system/backend-identity" -Headers $headers
  $vault = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/v1/vaults" -Headers $headers `
    -ContentType "application/json" `
    -Body (@{ name = "Public repository smoke"; path = $vaultPath } | ConvertTo-Json)
  $runtimeDescriptor = @{
    version = 1
    backend_url = $baseUrl
    api_prefix = "/api/v1"
    backend_instance_id = $identity.instance_id
    backend_started_at = $identity.started_at
    backend_pid = $backend.Id
    desktop_pid = $PID
    created_at = (Get-Date).ToUniversalTime().ToString("o")
    expires_at = (Get-Date).ToUniversalTime().AddHours(1).ToString("o")
  } | ConvertTo-Json
  [IO.File]::WriteAllText($runtimeFile, $runtimeDescriptor, [Text.UTF8Encoding]::new($false))

  $results = @()
  foreach ($fixture in $fixtures) {
    $target = Join-Path $reposRoot $fixture.name
    $before = Get-TreeFingerprint $target
    $commands = @(
      @("project", "add", $target, "--name", $fixture.name, "--vault-id", $vault.id, "--scope", "code", "--json"),
      @("project", "status", $target, "--json"),
      @("project", "sync", $target, "--json"),
      @("project", "tree", $target, "--query", $fixture.query, "--format", "json", "--json"),
      @("project", "graph", $target, "--query", $fixture.query, "--depth", "2", "--format", "json", "--json"),
      @("context", $fixture.query, "--project", $target, "--json")
    )
    $outputs = @()
    foreach ($arguments in $commands) {
      $previousErrorPreference = $ErrorActionPreference
      $ErrorActionPreference = "Continue"
      try {
        $raw = & $python -s -m backend.app.odin_cli @arguments 2>&1
        $commandExitCode = $LASTEXITCODE
      } finally {
        $ErrorActionPreference = $previousErrorPreference
      }
      if ($commandExitCode -notin @(0, 6)) {
        throw "Odin command failed for $($fixture.name): odin $($arguments -join ' ')`n$($raw -join [Environment]::NewLine)"
      }
      $outputs += @{
        command = "odin " + ($arguments -join " ")
        exit_code = $commandExitCode
        output = ($raw -join [Environment]::NewLine)
      }
    }
    $after = Get-TreeFingerprint $target
    if ($before -ne $after) {
      throw "Odin modified the $($fixture.name) repository working tree."
    }
    $results += @{
      name = $fixture.name
      url = $fixture.url
      commit = $fixture.commit
      clean_after = $true
      commands = $outputs
    }
  }

  $report = @{
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    work_root = $work
    backend = $baseUrl
    vault_id = $vault.id
    repositories = $results
    pass = $true
  }
  $reportPath = Join-Path $work "odin-public-repos-report.json"
  $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding utf8
  $report | ConvertTo-Json -Depth 5
} catch {
  $failure = @{
    pass = $false
    error = $_.Exception.Message
    position = $_.InvocationInfo.PositionMessage
    script_stack = $_.ScriptStackTrace
  } | ConvertTo-Json -Depth 5
  [IO.File]::WriteAllText(
    (Join-Path $work "odin-public-repos-failure.json"),
    $failure,
    [Text.UTF8Encoding]::new($false)
  )
  throw
} finally {
  if ($backend -and -not $backend.HasExited) {
    Stop-Process -Id $backend.Id -Force
    $backend.WaitForExit()
  }
  foreach ($entry in $savedEnvironment.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process")
  }
}
