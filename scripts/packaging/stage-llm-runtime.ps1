param(
  [Parameter(Mandatory = $true)]
  [string]$TargetDir,
  [string]$CacheDir = "",
  [switch]$CpuOnly
)

$ErrorActionPreference = "Stop"
$runtimeVersion = "b9374"
$cpuArchive = @{
  Name = "llama-b9374-bin-win-cpu-x64.zip"
  Sha256 = "1a19a4966ae3798aff3f6bc03da8d6314bac2292b3f3503987baa8542e303761"
}
$cudaArchive = @{
  Name = "llama-b9374-bin-win-cuda-12.4-x64.zip"
  Sha256 = "9843c5ec7db8939e66d0ce546e032cf515403093713b6c5229d04e21ecf8e5f8"
}
$cudaRuntimeArchive = @{
  Name = "cudart-llama-bin-win-cuda-12.4-x64.zip"
  Sha256 = "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6"
}
$releaseBaseUrl = "https://github.com/ggml-org/llama.cpp/releases/download/$runtimeVersion"

$targetPath = [System.IO.Path]::GetFullPath($TargetDir)
if (-not $CacheDir) {
  $CacheDir = Join-Path ([System.IO.Path]::GetTempPath()) "cml-llama-runtime-cache"
}
$cachePath = [System.IO.Path]::GetFullPath($CacheDir)
$extractPath = "$targetPath.extracting"
$lockPath = Join-Path $cachePath "stage.lock"

function Get-VerifiedArchive([hashtable]$Asset) {
  $archivePath = Join-Path $cachePath $Asset.Name
  if (-not (Test-Path -LiteralPath $archivePath)) {
    $downloadPath = "$archivePath.download-$PID"
    try {
      Invoke-WebRequest `
        -Uri "$releaseBaseUrl/$($Asset.Name)" `
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
  $hashDeadline = [DateTime]::UtcNow.AddSeconds(30)
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
  if ($actualSha256 -ne $Asset.Sha256) {
    throw "Pinned llama.cpp runtime archive failed SHA-256 verification: $($Asset.Name)"
  }
  return $archivePath
}

function Expand-ServerArchive(
  [string]$ArchivePath,
  [string]$Destination,
  [string]$ScratchName
) {
  $scratchPath = Join-Path $extractPath $ScratchName
  New-Item -ItemType Directory -Force -Path $scratchPath | Out-Null
  Expand-Archive -LiteralPath $ArchivePath -DestinationPath $scratchPath -Force
  $server = Get-ChildItem -LiteralPath $scratchPath -Recurse -Filter "llama-server.exe" |
    Select-Object -First 1
  if (-not $server) {
    throw "Pinned llama.cpp runtime does not contain llama-server.exe: $ArchivePath"
  }
  New-Item -ItemType Directory -Force -Path $Destination | Out-Null
  Get-ChildItem -LiteralPath $server.Directory.FullName -Force |
    Copy-Item -Destination $Destination -Recurse -Force
  Remove-Item -LiteralPath $scratchPath -Recurse -Force
}

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
  $cpuArchivePath = Get-VerifiedArchive $cpuArchive
  $cudaArchivePath = $null
  $cudaRuntimeArchivePath = $null
  if (-not $CpuOnly) {
    $cudaArchivePath = Get-VerifiedArchive $cudaArchive
    $cudaRuntimeArchivePath = Get-VerifiedArchive $cudaRuntimeArchive
  }

  if (Test-Path -LiteralPath $extractPath) {
    Remove-Item -LiteralPath $extractPath -Recurse -Force
  }
  New-Item -ItemType Directory -Force -Path $extractPath | Out-Null
  Expand-ServerArchive $cpuArchivePath $extractPath "cpu-archive"

  $variants = [ordered]@{
    cpu = [ordered]@{
      server = "llama-server.exe"
      archive = $cpuArchive.Name
      archive_sha256 = $cpuArchive.Sha256
    }
  }

  if (-not $CpuOnly) {
    $cudaPath = Join-Path $extractPath "cuda"
    Expand-ServerArchive $cudaArchivePath $cudaPath "cuda-archive"

    $cudaRuntimeScratch = Join-Path $extractPath "cuda-runtime-archive"
    New-Item -ItemType Directory -Force -Path $cudaRuntimeScratch | Out-Null
    Expand-Archive -LiteralPath $cudaRuntimeArchivePath -DestinationPath $cudaRuntimeScratch -Force
    Get-ChildItem -LiteralPath $cudaRuntimeScratch -Recurse -File -Force |
      Copy-Item -Destination $cudaPath -Force
    Remove-Item -LiteralPath $cudaRuntimeScratch -Recurse -Force

    $requiredCudaFiles = @(
      (Join-Path $cudaPath "llama-server.exe"),
      (Join-Path $cudaPath "ggml-cuda.dll"),
      (Join-Path $cudaPath "cublas64_12.dll"),
      (Join-Path $cudaPath "cudart64_12.dll")
    )
    foreach ($requiredFile in $requiredCudaFiles) {
      if (-not (Test-Path -LiteralPath $requiredFile)) {
        throw "Pinned CUDA runtime is incomplete: $requiredFile"
      }
    }
    $variants["cuda"] = [ordered]@{
      server = "cuda/llama-server.exe"
      archive = $cudaArchive.Name
      archive_sha256 = $cudaArchive.Sha256
      cuda_runtime_archive = $cudaRuntimeArchive.Name
      cuda_runtime_archive_sha256 = $cudaRuntimeArchive.Sha256
      cuda_version = "12.4"
    }
  }

  $runtimeManifest = [ordered]@{
    schema_version = 2
    runtime = "llama.cpp"
    version = $runtimeVersion
    source = "$releaseBaseUrl/"
    variants = $variants
  } | ConvertTo-Json -Depth 5
  [System.IO.File]::WriteAllText(
    (Join-Path $extractPath "runtime.json"),
    $runtimeManifest,
    [System.Text.UTF8Encoding]::new($false)
  )

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
