param(
  [string]$Destination = "",
  [ValidateSet("cpu", "cuda")]
  [string]$Runtime = "cpu",
  [string]$CudaVersion = "12.4",
  [string]$AssetPattern = ""
)

$ErrorActionPreference = "Stop"

if (-not $Destination) {
  $Destination = Join-Path $env:LOCALAPPDATA "CML\llm-runtimes\llama.cpp"
}

New-Item -ItemType Directory -Force -Path $Destination | Out-Null

$release = Invoke-RestMethod `
  -Uri "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest" `
  -Headers @{ "User-Agent" = "CML-local-runtime-setup" }

if (-not $AssetPattern) {
  $AssetPattern = if ($Runtime -eq "cuda") {
    "^llama-.*bin-win-cuda-$([regex]::Escape($CudaVersion))-x64\.zip$"
  } else {
    "^llama-.*bin-win-cpu-x64\.zip$"
  }
}

$assets = @(
  $release.assets |
    Where-Object { $_.name -match $AssetPattern } |
    Select-Object -First 1
)

if ($Runtime -eq "cuda") {
  $cudartPattern = "cudart-llama-bin-win-cuda-$([regex]::Escape($CudaVersion))-x64\.zip$"
  $assets += $release.assets |
    Where-Object { $_.name -match $cudartPattern } |
    Select-Object -First 1
}

$assets = @($assets | Where-Object { $_ })

if (-not $assets) {
  throw "No llama.cpp release assets matched runtime: $Runtime"
}

$runtimeName = if ($Runtime -eq "cuda") { "cuda-$CudaVersion" } else { "cpu" }
$extractPath = Join-Path $Destination "$($release.tag_name)-$runtimeName"

foreach ($asset in $assets) {
  $zipPath = Join-Path $Destination $asset.name
  if (-not (Test-Path $zipPath)) {
    Write-Host "Downloading $($asset.name)..." -ForegroundColor Cyan
    Invoke-WebRequest `
      -Uri $asset.browser_download_url `
      -OutFile $zipPath `
      -Headers @{ "User-Agent" = "CML-local-runtime-setup" }
  }

  Write-Host "Extracting $($asset.name) to $extractPath..." -ForegroundColor Cyan
  New-Item -ItemType Directory -Force -Path $extractPath | Out-Null
  Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force
}

$server = Get-ChildItem -Path $extractPath -Recurse -Filter "llama-server.exe" |
  Select-Object -First 1
$cli = Get-ChildItem -Path $extractPath -Recurse -Filter "llama-cli.exe" |
  Select-Object -First 1

if (-not $server -or -not $cli) {
  throw "Extracted runtime is missing llama-server.exe or llama-cli.exe"
}

Write-Host "llama.cpp $($release.tag_name) $runtimeName is ready." -ForegroundColor Green
Write-Host "Server: $($server.FullName)"
Write-Host "CLI:    $($cli.FullName)"
