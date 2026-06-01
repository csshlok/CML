param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [string]$Output = ".\requirements\contributors-backend.txt"
)

if (-not (Test-Path $Python)) {
    throw "Python executable not found: $Python"
}

$header = @(
    "# Contributor backend/dev environment for CML.",
    "# Generated from the active environment. Review before committing.",
    "# Update command: .\scripts\dev\update-requirements.ps1"
)

$freeze = & $Python -m pip freeze
if ($LASTEXITCODE -ne 0) {
    throw "pip freeze failed"
}

Set-Content -Path $Output -Value ($header + $freeze) -Encoding UTF8
Write-Host "Updated $Output"
