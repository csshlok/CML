# CML Working Commands

This file is the operator runbook for local development, packaging, and version bumps.

Run every command from the repo root unless a section says otherwise:

```powershell
cd C:\Users\csshl\Desktop\CML
```

## 1. First-Time Setup

Install JavaScript dependencies:

```powershell
npm install
```

Create the Python virtual environment if `.venv` does not exist yet:

```powershell
python -m venv .venv
```

Install backend dependencies into `.venv`:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e backend
```

Verify the two critical runtimes exist:

```powershell
Test-Path .\.venv\Scripts\python.exe
Test-Path .\node_modules
```

## 2. Starting The Backend

Preferred command for local backend development:

```powershell
npm run backend
```

That script generates `CML_API_TOKEN` for the current process if it is missing and then starts:

```text
uvicorn backend.app.main:app --host 127.0.0.1 --port 7343
```

Direct backend start, if you need to bypass the helper script:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 7343
```

Backend health check:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:7343/health
```

OCR runtime health check:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:7343/api/v1/system/ocr
```

Stop whatever is listening on backend port `7343`:

```powershell
$pidToStop = (Get-NetTCPConnection -LocalPort 7343 -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' } | Select-Object -First 1).OwningProcess
if ($pidToStop) { Stop-Process -Id $pidToStop -Force }
```

## 3. Starting The Desktop App

Run the desktop app in development mode:

```powershell
npm run dev
```

Run only the renderer dev server:

```powershell
npm run dev:web
```

Build the production renderer bundle:

```powershell
npm run build
```

## 4. Windows Packaging And Rebuilds

The Windows packaging entry point is:

```text
scripts/packaging/package-windows.ps1
```

The script now prints phase-by-phase progress in the terminal, including:

- elapsed time
- current packaging phase
- cache hit or cache miss for staged runtimes
- builder target and config path
- final artifact paths and file sizes

### 4.1 Fast Dev Rebuild

Use this while iterating on packaging bugs. It reuses staged runtimes unless fingerprints changed.

Packaged directory only:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\packaging\package-windows.ps1 -PackagedOnly -OutputDir apps\desktop\release
```

Installer plus unpacked output:

```powershell
npm run package:win
```

Current installer naming comes from `apps/desktop/package.json` and the packaging script. Dev installers currently look like:

```text
apps/desktop/release/test-<desktop-version>-Setup.exe
```

### 4.2 Full Release Rebuild

Use this when you want a clean rebuild and do not want cached staged runtimes reused.

Packaged directory only:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\packaging\package-windows.ps1 -Release -PackagedOnly -OutputDir apps\desktop\release
```

Installer plus unpacked output:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\packaging\package-windows.ps1 -Release -OutputDir apps\desktop\release
```

### 4.3 OCR Runtime Staging

If OCR binaries are missing or stale, restage them before rebuilding packages:

```powershell
.\scripts\packaging\stage-ocr-runtime.ps1
```

If auto-detection misses local installs, pass explicit binary paths:

```powershell
.\scripts\packaging\stage-ocr-runtime.ps1 -TesseractExePath "C:\path\to\tesseract.exe" -GhostscriptExePath "C:\path\to\gswin64c.exe"
```

If you intentionally want to package without refreshing OCR:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\packaging\package-windows.ps1 -SkipOcrRuntimeDownload -OutputDir apps\desktop\release
```

### 4.4 Packaged Output Verification

Validate package layout:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\packaging\validate-clean-machine-package.ps1 -PackageRoot apps\desktop\release\win-unpacked
```

Smoke the packaged backend/runtime:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\packaging\smoke-packaged-runtime.ps1 -PackageRoot apps\desktop\release\win-unpacked
```

Smoke packaged full-vault flow:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\packaging\smoke-packaged-full-vault.ps1 -PackageRoot apps\desktop\release\win-unpacked
```

Smoke packaged app launch:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\packaging\smoke-packaged-app-launch.ps1 -PackageRoot apps\desktop\release\win-unpacked
```

Smoke the installer itself:

```powershell
$installer = Get-ChildItem apps\desktop\release\test-*-Setup.exe | Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\packaging\smoke-windows-installer.ps1 -InstallerPath $installer
```

## 5. Version Bump Procedure

Versioning is split by surface, but backend runtime metadata is centralized now:

- `package.json`
- `apps/desktop/package.json`
- `backend/pyproject.toml`

### 5.1 Recommended Version Bump Order

Update the root npm package version:

```powershell
npm version 0.1.6 --no-git-tag-version
```

## 6. Benchmark Reports

Render graphical benchmark reports from the current JSON artifacts:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backend\render-benchmark-graphs.ps1
```

Render graphs for specific benchmark files only:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backend\render-benchmark-graphs.ps1 -ReportPaths .tmp\pdf-parser-benchmark.json,.tmp\ingestion-benchmark.json,.tmp\context-strategy-benchmark.json,.tmp\release-proof\release-proof-report.json
```

The generated HTML index is written to:

```text
data\benchmark-reports\graphs\index.html
```

Run the synthetic user-shaped benchmark corpus end to end:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backend\benchmark-synthetic-user-corpus.ps1 -ReportRoot .tmp\synthetic-user-benchmark
```

Run the 10,000-file scale version:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backend\benchmark-synthetic-user-corpus.ps1 -ReportRoot .tmp\synthetic-user-benchmark-10k-clean -TargetFileCount 10000
```

That run:

- generates a temporary mixed corpus with varied PDFs, notes, DOCX, HTML, CSV, JSON, and TXT
- benchmarks ingestion and PDF parsing
- ingests and indexes the corpus into a fresh benchmark vault without re-extracting the same files twice
- runs the strict context-strategy benchmark and rejects zero-chunk or zero-hit runs
- deletes the generated corpus before exiting unless `-KeepCorpus` is passed

Update the desktop app version:

```powershell
npm version 0.1.6 --workspace @cml/desktop --no-git-tag-version
```

Then update the backend package version in:

- `backend/pyproject.toml`

Backend runtime, diagnostics, and MCP metadata now resolve the app version from `backend/pyproject.toml` through `backend/app/core/version.py`. Do not manually hardcode the same version into multiple Python files.

Refresh npm lock metadata after version bumps:

```powershell
npm install --package-lock-only
```

If you want to check for stale version strings before committing, search for the old version directly:

```powershell
rg -n "0\\.1\\.4|0\\.1\\.0" package.json apps\desktop\package.json backend\pyproject.toml backend\app
```

### 5.2 Important Version Rules

- The Windows installer artifact name is driven by `apps/desktop/package.json`.
- If you only bump the root `package.json`, the installer version does not change.
- Backend diagnostics and API metadata are derived from the backend package version; keep `backend/pyproject.toml` authoritative.
- Do not hardcode version numbers into packaging commands or tests.

## 6. Daily Validation Commands

Run all backend tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend/tests
```

Run the targeted backend tests that have been useful during packaging work:

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend/tests/test_parameters_doc_cases.py
```

Run the focused parser / context-reduction / benchmark / extension-backend tests added for the new benchmark and ingestion work:

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend/tests/test_pdf_pipeline.py backend/tests/test_context_reduction.py backend/tests/test_benchmark_matrix.py backend/tests/test_extension_setup_contract.py
```

Run desktop behavior tests:

```powershell
npm run lint
```

Run the renderer production build:

```powershell
npm run build
```

Run package security checks:

```powershell
npm run security:renderer
npm run security:package
```

Compile backend Python files:

```powershell
.\.venv\Scripts\python.exe -m compileall backend
```

## 7. Benchmarks And Smokes

Run backend benchmark smoke:

```powershell
.\scripts\backend\benchmark-backend.ps1 -Sources 250 -WordsPerSource 240 -ReportPath .tmp\backend-benchmark-report.md
```

Run the PDF parser bakeoff benchmark:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backend\benchmark-pdf-parsers.ps1 -SourceRoot . -MaxFiles 25 -ReportPath .tmp\pdf-parser-benchmark.json
```

Run the mixed-file ingestion timing benchmark:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backend\benchmark-ingestion-matrix.ps1 -SourceRoot . -MaxFiles 100 -ReportPath .tmp\ingestion-benchmark.json
```

Run the context-strategy comparison benchmark against a prepared vault:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backend\benchmark-context-strategies.ps1 -VaultId vault-1 -ReportPath .tmp\context-strategy-benchmark.json
```

Run the real-PDF retrieval benchmark:

```powershell
.\scripts\backend\benchmark-real-vault-retrieval.ps1 -MaxFiles 50 -QueryCount 20 -TopK 10
```

Run the LoRA scaffold smoke:

```powershell
.\scripts\backend\smoke-lora-expert.ps1 -AllowTestTrainer
```

Run a real LoRA trainer smoke:

```powershell
$env:CML_LORA_TRAINER_COMMAND = ".\.venv-lora\Scripts\llamafactory-cli.exe train {config_path}"
$env:CML_LORA_MODEL_DIRS = "D:\models\hf"
$env:CML_LLM_MODEL = "Qwen2.5-3B-Instruct"
$env:CML_LORA_TRAINING_MAX_STEPS = "1"
$env:CML_LORA_TRAINING_CUTOFF_LEN = "512"
.\scripts\backend\smoke-lora-expert.ps1 -RuntimeMaxNewTokens 8 -BenchmarkMaxNewTokens 8 -AllowBenchmarkFailure
```

Run the local adapter smoke:

```powershell
$env:CML_LORA_MODEL_DIRS = "D:\models\hf"
$env:CML_LORA_RUNTIME_PYTHON = "C:\Users\you\Desktop\CML\.venv-lora\Scripts\python.exe"
.\scripts\backend\smoke-lora-runtime.ps1 -AdapterPath D:\cml\data\experts\cluster-1\adapter-1234 -BaseModel Qwen2.5-3B-Instruct
```

Run the release-proof wrapper for the new parser/benchmark/extension surfaces:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backend\validate-release-proof.ps1 -ContextVaultId vault-1 -ReportRoot .tmp\release-proof
```

## 8. Common Output Paths

Desktop package output:

```text
apps/desktop/release
```

Packaged app executable:

```text
apps/desktop/release/win-unpacked/CML.exe
```

Packaged resources root:

```text
apps/desktop/release/win-unpacked/resources
```

Local packaging runtime caches:

```text
apps/desktop/packaging/backend
apps/desktop/packaging/python-runtime
apps/desktop/packaging/expert-python-runtime
apps/desktop/packaging/ms-playwright
```

## 9. Practical Workflow

For everyday feature work:

1. `npm run backend`
2. In another terminal, `npm run dev`
3. Run `npm run lint`, `npm run build`, and targeted backend tests before committing

For packaging work:

1. Restage OCR only if needed
2. Run a fast dev rebuild first
3. Run packaged validation smokes on `win-unpacked`
4. Run a full `-Release` rebuild only when you need a clean artifact

For versioned Windows drops:

1. Bump versions
2. Verify no stale version strings remain
3. Run the rebuild command that matches the release goal
4. Validate `win-unpacked`
5. Test the installer on a clean VM
