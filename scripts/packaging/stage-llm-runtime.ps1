param(
  [Parameter(Mandatory = $true)]
  [string]$TargetDir,
  [string]$CacheDir = ""
)

$ErrorActionPreference = "Stop"
$runtimeVersion = "b9374"
$archiveName = "llama-b9374-bin-win-cpu-x64.zip"
$archiveSha256 = "1a19a4966ae3798aff3f6bc03da8d6314bac2292b3f3503987baa8542e303761"
$archiveUrl = "https://github.com/ggml-org/llama.cpp/releases/download/$runtimeVersion/$archiveName"

$targetPath = [System.IO.Path]::GetFullPath($TargetDir)
if (-not $CacheDir) {
  $CacheDir = Join-Path ([System.IO.Path]::GetTempPath()) "cml-llama-runtime-cache"
}
$cachePath = [System.IO.Path]::GetFullPath($CacheDir)
$archivePath = Join-Path $cachePath $archiveName
$extractPath = "$targetPath.extracting"
$lockPath = Join-Path $cachePath "stage.lock"

New-Item -ItemType Directory -Force -Path $cachePath | Out-Null
$cacheLock = $null
$lockDeadline = [DateTime]::UtcNow.AddMinutes(3)
while ($null -eq $cacheLock) {
  try {
    $cacheLock = [System.IO.File]::Open(
      $lockPath,
      [System.IO.FileMode]::OpenOrCreate,
      [System.IO.FileAccess]::ReadWrite,
      [System.IO.FileShare]::None
    )
  }
  catch [System.IO.IOException] {
    if ([DateTime]::UtcNow -ge $lockDeadline) {
      throw "Timed out waiting for another llama.cpp runtime staging process to finish."
    }
    Start-Sleep -Milliseconds 250
  }
}

try {
  if (-not (Test-Path -LiteralPath $archivePath)) {
    $downloadPath = "$archivePath.download-$PID"
    try {
      Invoke-WebRequest `
        -Uri $archiveUrl `
        -OutFile $downloadPath `
        -Headers @{ "User-Agent" = "Vault-packaging/$runtimeVersion" }
      Move-Item -LiteralPath $downloadPath -Destination $archivePath
    }
    finally {
      if (Test-Path -LiteralPath $downloadPath) {
        Remove-Item -LiteralPath $downloadPath -Force
      }
    }
  }

  $actualSha256 = $null
  $hashDeadline = [DateTime]::UtcNow.AddSeconds(15)
  while ($null -eq $actualSha256) {
    try {
      $actualSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant()
    }
    catch {
      if ([DateTime]::UtcNow -ge $hashDeadline) {
        throw
      }
      Start-Sleep -Milliseconds 250
    }
  }
  if ($actualSha256 -ne $archiveSha256) {
    throw "Pinned llama.cpp runtime archive failed SHA-256 verification."
  }

  if (Test-Path -LiteralPath $extractPath) {
    Remove-Item -LiteralPath $extractPath -Recurse -Force
  }
  New-Item -ItemType Directory -Force -Path $extractPath | Out-Null
  Expand-Archive -LiteralPath $archivePath -DestinationPath $extractPath -Force

  $server = Get-ChildItem -LiteralPath $extractPath -Recurse -Filter "llama-server.exe" |
    Select-Object -First 1
  if (-not $server) {
    throw "Pinned llama.cpp runtime does not contain llama-server.exe."
  }
  if ($server.Directory.FullName -ne $extractPath) {
    Get-ChildItem -LiteralPath $server.Directory.FullName -Force |
      Copy-Item -Destination $extractPath -Recurse -Force
  }

  @{
    schema_version = 1
    runtime = "llama.cpp"
    version = $runtimeVersion
    archive = $archiveName
    archive_sha256 = $archiveSha256
    source = $archiveUrl
  } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $extractPath "runtime.json") -Encoding utf8

  if (Test-Path -LiteralPath $targetPath) {
    Remove-Item -LiteralPath $targetPath -Recurse -Force
  }
  Move-Item -LiteralPath $extractPath -Destination $targetPath
  Write-Output (Join-Path $targetPath "llama-server.exe")
}
finally {
  if ($null -ne $cacheLock) {
    $cacheLock.Dispose()
  }
}
