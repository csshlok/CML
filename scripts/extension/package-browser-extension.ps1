param(
  [string]$OutputRoot = ".tmp/browser-extension-dist"
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path
$extensionRoot = Join-Path $repoRoot "apps\\browser-extension"
$outputRootPath = Join-Path $repoRoot $OutputRoot
$stagingPath = Join-Path $outputRootPath "cml-browser-extension"
$zipPath = Join-Path $outputRootPath "cml-browser-extension.zip"

if (-not (Test-Path $extensionRoot)) {
  throw "Extension root not found: $extensionRoot"
}

New-Item -ItemType Directory -Force -Path $outputRootPath | Out-Null
if (Test-Path $stagingPath) {
  Remove-Item -LiteralPath $stagingPath -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $stagingPath | Out-Null

Copy-Item -LiteralPath (Join-Path $extensionRoot "manifest.json") -Destination $stagingPath
Copy-Item -LiteralPath (Join-Path $extensionRoot "background-core.js") -Destination $stagingPath
Copy-Item -LiteralPath (Join-Path $extensionRoot "background.js") -Destination $stagingPath
Copy-Item -LiteralPath (Join-Path $extensionRoot "content.js") -Destination $stagingPath
Copy-Item -LiteralPath (Join-Path $extensionRoot "popup.html") -Destination $stagingPath
Copy-Item -LiteralPath (Join-Path $extensionRoot "popup.css") -Destination $stagingPath
Copy-Item -LiteralPath (Join-Path $extensionRoot "popup-core.js") -Destination $stagingPath
Copy-Item -LiteralPath (Join-Path $extensionRoot "popup.js") -Destination $stagingPath
Copy-Item -LiteralPath (Join-Path $extensionRoot "extension-core.js") -Destination $stagingPath

$iconsPath = Join-Path $extensionRoot "icons"
if (-not (Test-Path $iconsPath)) {
  throw "Extension icons folder is missing: $iconsPath"
}
Copy-Item -LiteralPath $iconsPath -Destination $stagingPath -Recurse

if (Test-Path $zipPath) {
  Remove-Item -LiteralPath $zipPath -Force
}
Compress-Archive -Path (Join-Path $stagingPath "*") -DestinationPath $zipPath

Write-Output "Packaged browser extension:"
Write-Output "  Staging: $stagingPath"
Write-Output "  Zip: $zipPath"
