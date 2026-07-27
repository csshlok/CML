param(
  [string]$PackageRoot = "",
  [string]$ReportPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
if (-not $PackageRoot) {
  throw "PackageRoot is required."
}
$packagePath = [IO.Path]::GetFullPath($PackageRoot)
$exe = Join-Path $packagePath "CML.exe"
$resources = Join-Path $packagePath "resources"
$python = Join-Path $resources "python-runtime\python.exe"
$module = Join-Path $resources "app.asar\electron\odin-launcher.cjs"
$asar = Join-Path $resources "app.asar"
foreach ($required in @($exe, $python, $asar)) {
  if (-not (Test-Path -LiteralPath $required)) {
    throw "Packaged Odin smoke prerequisite is missing: $required"
  }
}

$smokeRoot = Join-Path $env:TEMP ("cml-odin-launcher-" + [guid]::NewGuid().ToString("n"))
$bin = Join-Path $smokeRoot "bin"
$cleanAppData = Join-Path $smokeRoot "appdata"
$driver = Join-Path $smokeRoot "install-launcher.cjs"
New-Item -ItemType Directory -Force -Path $smokeRoot, $cleanAppData | Out-Null
$driverText = @'
const launcher = require(process.argv[2]);
launcher.installLauncher({
  binDir: process.argv[3],
  pythonPath: process.argv[4],
  resourcesRoot: process.argv[5],
  registerPath: () => ({ changed: false, supported: true }),
}).then((result) => process.stdout.write(JSON.stringify(result)))
  .catch((error) => { process.stderr.write(String(error && error.stack || error)); process.exitCode = 1; });
'@
[IO.File]::WriteAllText($driver, $driverText, [Text.UTF8Encoding]::new($false))

$previousRunAsNode = $env:ELECTRON_RUN_AS_NODE
try {
  $env:ELECTRON_RUN_AS_NODE = "1"
  $installStdout = Join-Path $smokeRoot "install.stdout.log"
  $installStderr = Join-Path $smokeRoot "install.stderr.log"
  $installProcess = Start-Process `
    -FilePath $exe `
    -ArgumentList @($driver, $module, $bin, $python, $resources) `
    -Wait `
    -PassThru `
    -RedirectStandardOutput $installStdout `
    -RedirectStandardError $installStderr
  if ($installProcess.ExitCode -ne 0) {
    $detail = Get-Content -LiteralPath $installStderr -Raw -ErrorAction SilentlyContinue
    throw "The packaged launcher module could not install Odin. $detail"
  }
  $installed = (Get-Content -LiteralPath $installStdout -Raw) | ConvertFrom-Json
} finally {
  if ($null -eq $previousRunAsNode) {
    Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
  } else {
    $env:ELECTRON_RUN_AS_NODE = $previousRunAsNode
  }
}

$cleanScript = @'
$ErrorActionPreference = "Continue"
$env:PATH = "$env:ODIN_SMOKE_BIN;$env:SystemRoot\System32;$env:SystemRoot"
$env:APPDATA = $env:ODIN_SMOKE_APPDATA
Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
Remove-Item Env:ODIN_API_TOKEN -ErrorAction SilentlyContinue
Remove-Item Env:CML_API_TOKEN -ErrorAction SilentlyContinue
$help = & odin --help 2>&1
$helpCode = $LASTEXITCODE
$offline = & odin project list 2>&1
$offlineCode = $LASTEXITCODE
[ordered]@{
  command = (Get-Command odin).Source
  help_exit_code = $helpCode
  help_mentions_odin = [bool](($help -join "`n") -match "Odin")
  offline_exit_code = $offlineCode
  offline_message_is_actionable = [bool](($offline -join "`n") -match "Vault Desktop is not available|Open Vault")
} | ConvertTo-Json -Compress
'@
$cleanProbePath = Join-Path $smokeRoot "clean-probe.ps1"
[IO.File]::WriteAllText($cleanProbePath, $cleanScript, [Text.UTF8Encoding]::new($false))
$env:ODIN_SMOKE_BIN = $bin
$env:ODIN_SMOKE_APPDATA = $cleanAppData
$cleanOutput = & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $cleanProbePath
if ($LASTEXITCODE -ne 0) {
  throw "The clean PowerShell Odin probe could not run."
}
$probe = ($cleanOutput -join "`n") | ConvertFrom-Json
$pass = (
  $installed.installed -and
  $probe.command -eq (Join-Path $bin "odin.cmd") -and
  $probe.help_exit_code -eq 0 -and
  $probe.help_mentions_odin -and
  $probe.offline_exit_code -eq 3 -and
  $probe.offline_message_is_actionable
)
$report = [ordered]@{
  generated_at = (Get-Date).ToUniversalTime().ToString("o")
  package_root = $packagePath
  used_host_python = $false
  used_host_node = $false
  packaged_electron_node_driver = $exe
  packaged_python = $python
  launcher = $installed
  clean_shell = $probe
  pass = $pass
}
if ($ReportPath) {
  $resolvedReport = [IO.Path]::GetFullPath($ReportPath)
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $resolvedReport) | Out-Null
  $report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $resolvedReport -Encoding utf8
}
$report | ConvertTo-Json -Depth 6
if (-not $pass) {
  exit 1
}
