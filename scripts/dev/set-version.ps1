param(
  [Parameter(Mandatory = $true)]
  [ValidatePattern('^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$')]
  [string]$Version
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$trackedVersionFiles = @(
  (Join-Path $repoRoot "package.json"),
  (Join-Path $repoRoot "package-lock.json"),
  (Join-Path $repoRoot "apps\desktop\package.json"),
  (Join-Path $repoRoot "backend\pyproject.toml")
)
$originalContent = @{}
foreach ($path in $trackedVersionFiles) {
  $originalContent[$path] = [System.IO.File]::ReadAllText($path)
}

Push-Location $repoRoot
try {
  npm version $Version --no-git-tag-version --allow-same-version
  if ($LASTEXITCODE -ne 0) {
    throw "Could not update the root npm package version."
  }

  npm version $Version --workspace @cml/desktop --no-git-tag-version --allow-same-version
  if ($LASTEXITCODE -ne 0) {
    throw "Could not update the desktop npm package version."
  }

  $backendProject = Join-Path $repoRoot "backend\pyproject.toml"
  $backendText = [System.IO.File]::ReadAllText($backendProject)
  $versionPattern = '(?m)^(version\s*=\s*")[^"\r\n]+(")(?=\r?$)'
  $versionRegex = [regex]::new($versionPattern)
  if (-not $versionRegex.IsMatch($backendText)) {
    throw "Could not find the backend project version in backend\pyproject.toml."
  }
  $backendText = $versionRegex.Replace(
    $backendText,
    "`${1}$Version`${2}",
    1
  )
  [System.IO.File]::WriteAllText(
    $backendProject,
    $backendText,
    [System.Text.UTF8Encoding]::new($false)
  )

  npm install --package-lock-only --ignore-scripts
  if ($LASTEXITCODE -ne 0) {
    throw "Could not refresh npm lock metadata."
  }
}
catch {
  foreach ($path in $trackedVersionFiles) {
    [System.IO.File]::WriteAllText(
      $path,
      $originalContent[$path],
      [System.Text.UTF8Encoding]::new($false)
    )
  }
  throw
}
finally {
  Pop-Location
}

Write-Host "Vault version updated to $Version in root npm, desktop npm, backend, and lock metadata."
