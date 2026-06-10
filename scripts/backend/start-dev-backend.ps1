$ErrorActionPreference = "Stop"

if (-not $env:CML_API_TOKEN) {
  $bytes = New-Object byte[] 32
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try {
    $rng.GetBytes($bytes)
  } finally {
    $rng.Dispose()
  }
  $env:CML_API_TOKEN = [Convert]::ToBase64String($bytes).TrimEnd("=")
  Write-Host "Generated CML_API_TOKEN for this backend process."
}

& .venv\Scripts\python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 7343
