# CML Working Commands

Last updated: 2026-07-26

This is the current collaborator runbook for local development, Windows
development packages, validation, and version bumps. Commands do not depend on a
specific drive letter, username, or checkout folder.

Run every command from the repo root unless a section says otherwise:

```powershell
cd <your CML checkout>
```

## Collaborator Version Bump And Release Build

For the normal collaborator release workflow, replace `0.1.10` with the intended
version and run:

```powershell
$version = "0.1.10"
.\scripts\dev\set-version.ps1 -Version $version
npm run package:win:check
npm run lint
npm run build
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\packaging\package-windows.ps1 -Release -OutputDir apps\desktop\release
```

The version command updates the root npm package, desktop package, npm lockfiles,
and backend project together. It restores every version file if any update fails.
The release build clears staged runtime caches and uses maximum compression.

Expected outputs:

```text
apps/desktop/release/test-<version>-Setup.exe
apps/desktop/release/win-unpacked/CML.exe
```

This produces a clean development/test release build. It does not make the
installer publicly trusted or production-signed unless the collaborator also has
the approved signing identity and release credentials.

## 1. First-Time Setup

### 1.1 Supported contributor environment

Use:

- 64-bit Windows 10 or 11
- Windows PowerShell 5.1 or PowerShell 7
- 64-bit Node.js 22 LTS or newer
- 64-bit Python 3.11 through 3.14; Python 3.12 is the CI-aligned recommendation
- Git with long paths enabled
- At least 12 GB free on the drive containing the checkout for a first package
  build; cached rebuilds need less
- Internet access for npm, Python wheels, Electron, Chromium, llama.cpp, and OCR
  runtime downloads

No signing certificate, Hugging Face account, fixed drive letter, globally
installed Electron, or globally installed OCR tools are required for a
development/test package.

Clone into any writable folder, then run every command from the repository root:

```powershell
git config --global core.longpaths true
cd <your Vault checkout>
```

Install the exact JavaScript dependency tree:

```powershell
npm ci
```

Create the repository virtual environment. The `py` launcher command is preferred
because it selects the intended Python explicitly:

```powershell
py -3.12 -m venv .venv
```

If Python 3.12 is installed without the launcher, use its full executable path
instead. Install the pinned contributor environment, which includes packaging,
test, embedding, image, and OCR dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements\contributors-backend.txt
.\.venv\Scripts\python.exe -m pip install -e backend
```

Run the same packaging preflight used by the package script:

```powershell
npm run package:win:check
```

It verifies Windows/x64, Node, the repository virtual environment, required
Python modules, package branding and integrity inputs, Electron dependencies, and
available space on the repository drive.

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

### 3.1 Odin Project Commands

Odin is the Project Graph command surface. Packaged builds expose `odin`; from a source checkout,
the `odin.ps1` wrapper runs the same CLI:

```powershell
.\odin.ps1 auth status
.\odin.ps1 project add . --name "My Project" --scope context
.\odin.ps1 project add C:\src\library --name "Library Code" --scope code
.\odin.ps1 project list
.\odin.ps1 project status .
.\odin.ps1 project sync .
.\odin.ps1 project sync . --scope code
.\odin.ps1 project reindex . --layer retrieval
.\odin.ps1 project link . --cluster "Research"
.\odin.ps1 project explain . register_project
.\odin.ps1 project path . register_project build_structure_graph
.\odin.ps1 project graph . --query "project indexing" --depth 2 --format markdown
.\odin.ps1 project tree . --root "backend/app" --format markdown
.\odin.ps1 context "How does project indexing work?" --project .
.\odin.ps1 project remove .
```

For direct CLI development, use the module form:

```powershell
.\.venv\Scripts\python.exe -m backend.app.odin_cli project list
```

Odin uses `ODIN_BACKEND_URL` and `ODIN_API_TOKEN`, with the existing `CML_BACKEND_URL` and
`CML_API_TOKEN` variables as development fallbacks. Normal desktop use pairs the CLI through
the approval flow and stores its device credential with Windows user-bound protection. Removing
an Odin project deletes only CML's imported index and never modifies the repository working tree.
The persisted `context` scope (the default) includes code, supported documentation, manifests, and
configuration. The `code` scope retains source-like files and code manifests while excluding general
prose and configuration. Changing scope during sync builds a candidate snapshot and keeps the prior
active snapshot usable until activation.

Run the isolated Odin benchmark:

```powershell
.\.venv\Scripts\python.exe -m scripts.backend.benchmark_odin_project . tmp\benchmark\odin --scope code --retrieval
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

The build is self-contained and checkout-relative:

- Python comes only from `<repo>/.venv`; packaging never falls back to an
  unrelated system interpreter.
- Builder, llama.cpp, and OCR temporary/download state stays under the checkout
  (`.tmp` or `apps/desktop/packaging`) instead of assuming `C:` has space.
- Tesseract, qpdf, Ghostscript, llama.cpp, Playwright Chromium, and the packaged
  Python runtime are detected, downloaded, or staged automatically.
- Development signing is disabled. `-Release` controls clean caches and maximum
  compression; it does not provide a production certificate.

Before the first build:

```powershell
npm run package:win:check
npm run lint
npm run build
```

### 4.1 Fast Dev Rebuild

Use this while iterating on packaging bugs. It reuses staged runtimes unless fingerprints changed.

To produce both outputs collaborators normally need, run:

```powershell
npm run package:win
```

Expected outputs:

```text
apps/desktop/release/test-<desktop-version>-Setup.exe
apps/desktop/release/win-unpacked/CML.exe
```

`CML.exe` is the unpacked runnable app, not a second installer. The first package
build can take 20-40 minutes depending on network and disk speed because it creates
the packaged Python environment and downloads helper runtimes. Later unchanged
development builds reuse fingerprinted caches.

Packaged directory only:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\packaging\package-windows.ps1 -PackagedOnly -OutputDir apps\desktop\release
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

Normal development packaging stages OCR automatically without requiring a global
installation. If OCR binaries are missing or stale and you want to stage them
separately:

```powershell
.\scripts\packaging\stage-ocr-runtime.ps1
```

If preferred, reuse existing local installations by passing explicit binary paths:

```powershell
.\scripts\packaging\stage-ocr-runtime.ps1 -TesseractExePath "C:\path\to\tesseract.exe" -GhostscriptExePath "C:\path\to\gswin64c.exe"
```

If you intentionally want to package without refreshing OCR:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\packaging\package-windows.ps1 -SkipOcrRuntimeDownload -OutputDir apps\desktop\release
```

That flag reuses already staged OCR files; it does not create a valid OCR payload
from nothing.

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

The installer smoke installs and uninstalls CML and can stop an existing `CML.exe`.
Run it only on a disposable test profile or VM if preserving an existing local
installation matters.

## 5. Version Bump Procedure

Versioning is split by surface, but backend runtime metadata is centralized now:

- `package.json`
- `apps/desktop/package.json`
- `backend/pyproject.toml`

### 5.1 Recommended Version Bump Order

Use the transactional version command:

```powershell
$version = "0.1.9"
.\scripts\dev\set-version.ps1 -Version $version
```

Backend runtime, diagnostics, and MCP metadata now resolve the app version from `backend/pyproject.toml` through `backend/app/core/version.py`. Do not manually hardcode the same version into multiple Python files.

If you want to check for stale version strings before committing, search for the old version directly:

```powershell
$oldVersion = "0.1.8"
rg -n ([regex]::Escape($oldVersion)) package.json apps\desktop\package.json backend\pyproject.toml backend\app
```

### 5.2 Important Version Rules

- The Windows installer artifact name is driven by `apps/desktop/package.json`.
- If you only bump the root `package.json`, the installer version does not change.
- Backend diagnostics and API metadata are derived from the backend package version; keep `backend/pyproject.toml` authoritative.
- Do not hardcode version numbers into packaging commands or tests.

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

## 7. Daily Validation Commands

Run the CI-equivalent backend tiers independently:

```powershell
.\scripts\backend\run-tests.ps1 -Tier quick
.\scripts\backend\run-tests.ps1 -Tier integration
.\scripts\backend\run-tests.ps1 -Tier system
.\scripts\backend\run-tests.ps1 -Tier benchmark
```

Run the opt-in 50,000-file gate separately; it has a longer Windows budget and is not part of ordinary CI:

```powershell
.\scripts\backend\run-tests.ps1 -Tier scale
```

Run all non-scale backend tests in one local process when tier isolation is not needed:

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend/tests -m "not scale"
```

Run the targeted backend tests that have been useful during packaging work:

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend/tests/test_parameters_doc_cases.py
```

Run the focused managed-model activation and onboarding state checks:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_managed_model_runtime.py -q
.\.venv\Scripts\python.exe -m pytest backend/tests/test_additional_qa_cases.py::AdditionalQACases::test_onboarding_route_uses_internal_scroll_shell_instead_of_hidden_root backend/tests/test_additional_qa_cases.py::AdditionalQACases::test_onboarding_model_download_flow_exposes_location_progress_and_continue -q
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

## 8. Benchmarks And Smokes

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

Run the release-proof wrapper for the new parser/benchmark/extension surfaces:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backend\validate-release-proof.ps1 -ContextVaultId vault-1 -ReportRoot .tmp\release-proof
```

## 9. Common Output Paths

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
apps/desktop/packaging/ms-playwright
apps/desktop/packaging/llm-runtime
.tmp/llm-runtime-cache
.tmp/ocr-download-cache
```

## 10. Packaging Troubleshooting

### Preflight reports missing files or modules

Run the first-time setup exactly as documented, including both the pinned
requirements file and editable backend install. Do not substitute a global Python
environment for `.venv`.

### `EPERM` or rename failure for `win-unpacked.tmp`

Close CML, File Explorer windows open inside `release`, antivirus scans that have
the executable locked, and any terminal whose current directory is inside the
output. Then rerun `npm run package:win`; Electron Builder already retries with
isolated output directories.

### Build succeeds but expected executable or installer is absent

Use the first thrown Electron Builder error, not the later artifact-verification
message, as the root cause. Confirm these exact outputs after a successful run:

```powershell
Test-Path apps\desktop\release\win-unpacked\CML.exe
Get-ChildItem apps\desktop\release\test-*-Setup.exe
```

### Download or GitHub API failure

The first build requires access to npm, PyPI, GitHub Releases/API, raw GitHub
content, and Playwright's browser download host. Configure the normal system
`HTTP_PROXY`/`HTTPS_PROXY` environment if the machine uses a proxy, then rerun.
Completed downloads and fingerprinted runtimes are reused.

### Insufficient disk space

Keep the checkout on a drive with at least 12 GB free. Package staging, builder
temporary files, and llama/OCR caches follow the checkout. Moving only the final
`release` folder does not move all build state.

### Force a clean development rebuild

Use `-Release` only when a fresh runtime rebuild is intentional:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\packaging\package-windows.ps1 -Release -OutputDir apps\desktop\release
```

This is slower and redownloads/recreates staged helper runtimes. It still creates
an unsigned development/test artifact unless production signing is configured
separately.

## 11. Practical Workflow

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

After changing Electron chrome, preload IPC, onboarding downloads, or managed
runtime activation, a successful renderer build is not package proof. Re-run the
development package and installer lifecycle so `win-unpacked` and the NSIS
installer contain the current source revision.
