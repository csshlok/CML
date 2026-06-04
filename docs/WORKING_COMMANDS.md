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

Check OCR runtime health:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:7343/api/v1/system/ocr
```

Create a local vault database backup:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:7343/api/v1/system/vault-safety/backup
```

Stop the backend on port `7343`:

```powershell
$pidToStop = (Get-NetTCPConnection -LocalPort 7343 -ErrorAction SilentlyContinue | Where-Object {$_.State -eq 'Listen'} | Select-Object -First 1).OwningProcess
if ($pidToStop) { Stop-Process -Id $pidToStop -Force }
```

## Desktop App

Start the desktop app in development mode:

```powershell
npm run dev
```

Start only the Vite renderer:

```powershell
npm run dev:web
```

Build the desktop app renderer:

```powershell
npm run build
```

Build the Windows package:

```powershell
npm run package:win
```

## Tests And Checks

Run backend tests:

```powershell
.venv\Scripts\python -m unittest backend.tests.test_background_jobs backend.tests.test_source_pages -v
```

Run the LoRA scaffold smoke:

```powershell
.\scripts\backend\smoke-lora-expert.ps1 -AllowTestTrainer
```

Run a real LoRA trainer smoke:

```powershell
$env:CML_LORA_TRAINER_COMMAND = ".\.venv-lora\Scripts\llamafactory-cli.exe train --config {config_path}"
$env:CML_LORA_MODEL_DIRS = "D:\models\hf"
$env:CML_LLM_MODEL = "Qwen2.5-3B-Instruct"
.\scripts\backend\smoke-lora-expert.ps1
```

Run the live local adapter smoke against a real local model directory:

```powershell
$env:CML_LORA_MODEL_DIRS = "D:\models\hf"
$env:CML_LORA_RUNTIME_PYTHON = "C:\Users\you\Desktop\CML\.venv-lora\Scripts\python.exe"
.\scripts\backend\smoke-lora-runtime.ps1 -AdapterPath D:\cml\data\experts\cluster-1\adapter-1234 -BaseModel Qwen2.5-3B-Instruct
```

The runtime smoke expects a local Transformers model directory with `config.json` and tokenizer files. It loads the adapter with PEFT, runs a short prompt, and releases model resources before exiting.

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

Run backend ingestion/search/vector repair benchmark smoke:

```powershell
.\scripts\backend\benchmark-backend.ps1 -Sources 250 -WordsPerSource 240 -ReportPath .tmp\backend-benchmark-report.md
```

## Local OCR

Vault's OCR path is local-only. Scanned PDFs use OCRmyPDF + Tesseract when the local runtime is staged. Images use Tesseract directly. The backend first looks for bundled OCR binaries under:

```text
backend/bin/ocr/tesseract.exe
backend/bin/ocr/tessdata/eng.traineddata
backend/bin/ocr/qpdf/qpdf.exe
backend/bin/ocr/ghostscript/.../gswin64c.exe
```

Stage the local runtime:

```powershell
.\scripts\packaging\stage-ocr-runtime.ps1
```

If auto-detection misses a local install, pass explicit paths:

```powershell
.\scripts\packaging\stage-ocr-runtime.ps1 -TesseractExePath "C:\path\to\tesseract.exe" -GhostscriptExePath "C:\path\to\gswin64c.exe"
```

Run an OCR accuracy smoke:

```powershell
.\scripts\ocr\benchmark-ocr.ps1 -PdfPath .tmp\sample.pdf -ReferenceTextPath .tmp\reference.txt
```

OCRmyPDF requires local Ghostscript and qpdf command dependencies. In development, the backend can also run `python -m ocrmypdf` if the package is installed in `.venv`. If OCRmyPDF is incomplete, scanned PDFs fall back to direct page rendering plus Tesseract. If Tesseract is not present, image ingestion stores metadata and scanned-PDF ingestion reports that bundled OCR is unavailable. Packaged builds include `backend/bin/**/*` so the OCR runtime ships with the installer once staged there. Current local staged status is full OCRmyPDF ready with Tesseract, `eng.traineddata`, qpdf, and Ghostscript.
