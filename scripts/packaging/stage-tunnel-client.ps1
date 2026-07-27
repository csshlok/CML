param(
  [string]$TargetDir = "",
  [string]$CacheDir = ""
)

$ErrorActionPreference = "Stop"
$version = "0.0.10"
$archiveName = "tunnel-client-v$version-windows-amd64.zip"
$expectedSha256 = "5e64a056f1d96786da0a6f8db1da5f5f4a03fd19a90d951a25cf2ca8d9093d00"
$downloadUrl = "https://github.com/openai/tunnel-client/releases/download/v$version/$archiveName"

if (-not $TargetDir) {
  throw "TargetDir is required."
}
if (-not $CacheDir) {
  throw "CacheDir is required."
}

$targetPath = [System.IO.Path]::GetFullPath($TargetDir)
$cachePath = [System.IO.Path]::GetFullPath($CacheDir)
$archivePath = Join-Path $cachePath $archiveName
$extractPath = Join-Path $cachePath "extract-$version"

New-Item -ItemType Directory -Force -Path $cachePath | Out-Null
if (Test-Path -LiteralPath $archivePath) {
  $cachedHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($cachedHash -ne $expectedSha256) {
    Remove-Item -LiteralPath $archivePath -Force
  }
}
if (-not (Test-Path -LiteralPath $archivePath)) {
  $webClient = [System.Net.WebClient]::new()
  try {
    $webClient.Headers["User-Agent"] = "Vault-Packager/$version"
    $webClient.DownloadFile($downloadUrl, $archivePath)
  } finally {
    $webClient.Dispose()
  }
}

$actualSha256 = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualSha256 -ne $expectedSha256) {
  throw "Tunnel client checksum mismatch. Expected $expectedSha256 but received $actualSha256."
}

if (Test-Path -LiteralPath $extractPath) {
  Remove-Item -LiteralPath $extractPath -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $extractPath | Out-Null
Expand-Archive -LiteralPath $archivePath -DestinationPath $extractPath -Force
$binary = Get-ChildItem -LiteralPath $extractPath -Recurse -File -Filter "tunnel-client.exe" |
  Select-Object -First 1
if (-not $binary) {
  throw "The verified tunnel-client archive does not contain tunnel-client.exe."
}

if (Test-Path -LiteralPath $targetPath) {
  Remove-Item -LiteralPath $targetPath -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $targetPath | Out-Null
Copy-Item -LiteralPath $binary.FullName -Destination (Join-Path $targetPath "tunnel-client.exe") -Force

$manifest = [ordered]@{
  version = $version
  archive = $archiveName
  source = $downloadUrl
  archive_sha256 = $expectedSha256
  binary_sha256 = (Get-FileHash -LiteralPath (Join-Path $targetPath "tunnel-client.exe") -Algorithm SHA256).Hash.ToLowerInvariant()
}
$manifest | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $targetPath "manifest.json") -Encoding UTF8
Write-Output ($manifest | ConvertTo-Json -Compress)
