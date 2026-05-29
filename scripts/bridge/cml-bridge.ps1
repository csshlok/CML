param(
  [Parameter(Mandatory = $true, Position = 0)]
  [string]$Query,

  [string]$BackendUrl = "http://127.0.0.1:7343",
  [string]$Token = $env:CML_BRIDGE_TOKEN,
  [string]$VaultId = "",
  [string]$ClusterId = "",
  [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}
$tokenValue = ""
if ($Token) {
  $tokenValue = $Token
}

$args = @(
  "-m", "backend.app.bridge_cli",
  $Query,
  "--backend", $BackendUrl,
  "--token", $tokenValue
)

if ($VaultId) {
  $args += @("--vault-id", $VaultId)
}
if ($ClusterId) {
  $args += @("--cluster-id", $ClusterId)
}
if ($Json) {
  $args += "--json"
}

Push-Location $repoRoot
try {
  & $python @args
} finally {
  Pop-Location
}
