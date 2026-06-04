$ErrorActionPreference = "Stop"

if (-not $env:CML_API_TOKEN) {
  $bytes = New-Object byte[] 32
  [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
  $env:CML_API_TOKEN = [Convert]::ToBase64String($bytes).TrimEnd("=")
  Write-Host "Generated CML_API_TOKEN for this backend process."
}

& .venv\Scripts\python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 7343
