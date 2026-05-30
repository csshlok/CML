# Vault Working Commands

Run all commands from the repo root:

```powershell
cd C:\Users\csshl\Desktop\CML
```

## Backend

Start the local backend:

```powershell
.venv\Scripts\python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 7343
```

Check backend health:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:7343/health
```

Stop the backend on port `7343`:

```powershell
$pidToStop = (Get-NetTCPConnection -LocalPort 7343 -ErrorAction SilentlyContinue | Where-Object {$_.State -eq 'Listen'} | Select-Object -First 1).OwningProcess
if ($pidToStop) { Stop-Process -Id $pidToStop -Force }
```

## Desktop App

Start the desktop app in development mode:

```powershell
npm run dev --workspace @cml/desktop
```

Start only the Vite renderer:

```powershell
npm run dev:web --workspace @cml/desktop
```

Build the desktop app renderer:

```powershell
npm run build --workspace @cml/desktop
```

Build the Windows package:

```powershell
npm run package:win --workspace @cml/desktop
```

## Tests And Checks

Run backend tests:

```powershell
.venv\Scripts\python -m unittest backend.tests.test_background_jobs backend.tests.test_source_pages -v
```

Compile backend Python files:

```powershell
.venv\Scripts\python -m compileall backend
```

Run startup checks manually:

```powershell
@'
from backend.app.core.database import init_db
from backend.app.core.startup_checks import run_startup_checks
init_db()
run_startup_checks()
print("startup-check-ok")
'@ | .venv\Scripts\python -
```

## Local OCR

Vault's OCR path is local-only. The backend first looks for a bundled Tesseract binary under:

```text
backend/bin/ocr/tesseract.exe
backend/bin/ocr/tessdata/eng.traineddata
```

If that binary is not present, image ingestion stores metadata and scanned-PDF ingestion reports that bundled OCR is unavailable. Packaged builds include `backend/bin/**/*` so the OCR runtime ships with the installer once staged there.
