param(
  [string]$PackageRoot = "",
  [int]$Iterations = 5,
  [string]$ReportPath = "tmp\packaged-startup-benchmark.json",
  [double]$MaxWindowVisibleP95Ms = 1000,
  [double]$MaxBackendReadyP95Ms = 5000,
  [double]$MaxRendererReadyP95Ms = 8000
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
if (-not $PackageRoot) {
  throw "PackageRoot is required."
}
if ($Iterations -lt 3 -or $Iterations -gt 20) {
  throw "Iterations must be between 3 and 20."
}
$packagePath = [IO.Path]::GetFullPath($PackageRoot)
$smoke = Join-Path $PSScriptRoot "smoke-packaged-app-launch.ps1"
$userData = Join-Path $env:TEMP ("cml-startup-benchmark-" + [guid]::NewGuid().ToString("n"))
New-Item -ItemType Directory -Force -Path $userData | Out-Null

function Invoke-StartupProbe {
  $output = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $smoke `
    -PackageRoot $packagePath `
    -UserDataRoot $userData `
    -TimeoutSeconds 60
  if ($LASTEXITCODE -ne 0) {
    throw "Packaged startup probe failed."
  }
  return (($output -join "`n") | ConvertFrom-Json)
}

function Get-Percentile([double[]]$Values, [double]$Ratio) {
  $ordered = @($Values | Sort-Object)
  $index = [Math]::Max(0, [Math]::Ceiling($ordered.Count * $Ratio) - 1)
  return [double]$ordered[$index]
}

# Prime generated app state and the signed helper-verification receipt. The
# measured iterations are warm launches against the same immutable package.
Invoke-StartupProbe | Out-Null
$runs = @()
for ($index = 1; $index -le $Iterations; $index += 1) {
  $probe = Invoke-StartupProbe
  if ($null -eq $probe.window_visible_elapsed_ms) {
    throw "The packaged app did not record startup-window timing."
  }
  $runs += [ordered]@{
    iteration = $index
    window_visible_ms = [double]$probe.window_visible_elapsed_ms
    backend_ready_ms = [double]$probe.backend_ready_elapsed_ms
    renderer_ready_ms = [double]$probe.launch_to_renderer_ready_ms
  }
}
$windowP95 = Get-Percentile @($runs.window_visible_ms) 0.95
$backendP95 = Get-Percentile @($runs.backend_ready_ms) 0.95
$rendererP95 = Get-Percentile @($runs.renderer_ready_ms) 0.95
$report = [ordered]@{
  generated_at = (Get-Date).ToUniversalTime().ToString("o")
  package_root = $packagePath
  profile = "warm_same_package_and_user_data"
  iterations = $Iterations
  runs = $runs
  p95 = [ordered]@{
    window_visible_ms = $windowP95
    backend_ready_ms = $backendP95
    renderer_ready_ms = $rendererP95
  }
  budgets = [ordered]@{
    window_visible_ms = $MaxWindowVisibleP95Ms
    backend_ready_ms = $MaxBackendReadyP95Ms
    renderer_ready_ms = $MaxRendererReadyP95Ms
  }
  pass = (
    $windowP95 -le $MaxWindowVisibleP95Ms -and
    $backendP95 -le $MaxBackendReadyP95Ms -and
    $rendererP95 -le $MaxRendererReadyP95Ms
  )
}
$resolvedReport = [IO.Path]::GetFullPath((Join-Path $repoRoot $ReportPath))
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $resolvedReport) | Out-Null
$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $resolvedReport -Encoding utf8
$report | ConvertTo-Json -Depth 6
if (-not $report.pass) {
  exit 1
}
