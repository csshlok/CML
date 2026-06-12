# Packaging Investigation

## Scope

This document traces how the Windows desktop package is built today, what gets bundled, what happens during install and first run, and which packaging failures have been observed so far.

This is a build and packaging investigation only. No rebuild was started while preparing this document.

## High-level architecture

The desktop app is an Electron shell that bundles:

- A Vite-built frontend
- An Electron main process
- A Python backend
- A second Python runtime for expert-model work
- OCR tools
- Playwright Chromium

The packaged app is not a thin Electron wrapper around a remote service. It is a full local bundle with multiple runtimes and large binary dependencies.

## Packaging entry points

The current packaging entry point is the Windows packaging script:

### `scripts/packaging/package-windows.ps1`

This script is the real orchestrator for the current Windows package flow. It:

1. Builds the desktop frontend with `npm run build`
2. Stages backend source into `apps/desktop/packaging/backend`
3. Stages OCR tools
4. Builds or reuses a packaged backend Python runtime
5. Builds or reuses a packaged expert Python runtime
6. Stages Playwright Chromium
7. Generates a helper integrity manifest
8. Audits helper layout
9. Generates a temporary Electron Builder config in `.tmp/electron-builder.generated.json`
10. Runs `npx electron-builder --win --x64 --config <generated-config>`

`apps/desktop/package.json` now delegates its `package:win` command to this script, so the packaging path is single-sourced through the PowerShell workflow rather than split across a second static Electron Builder definition.

## What exactly gets bundled

The package contains these major payloads under `resources/`:

- `backend/`
- `python-runtime/`
- `expert-python-runtime/`
- `ms-playwright/`
- `helper-manifest.json`

The frontend and Electron code are bundled separately via Electron Builder:

- `dist/**/*`
- `electron/**/*`
- `package.json`

## Backend source staging

The script copies:

- `backend/app`
- `backend/bin` if present
- `backend/pyproject.toml`

into:

- `apps/desktop/packaging/backend`

This staged backend is then shipped into `resources/backend`.

## Python runtime strategy

### Previous broken approach

The original packaged runtime was based on a Windows virtual environment.

That failed because the bundled `python.exe` still pointed back to the build machine install path:

- `C:\Python314\python.exe`

That made the package non-relocatable and caused VM startup failures.

### Current approach

The current script resolves a base Python root from:

- `.venv\Scripts\python.exe`

by reading:

- `sys.base_prefix`

It then copies that entire CPython installation into:

- `apps/desktop/packaging/python-runtime`
- `apps/desktop/packaging/expert-python-runtime`

This is a portable copied runtime, not a venv.

### Backend runtime packages

The backend packaged runtime currently installs:

- `fastapi`
- `uvicorn[standard]`
- `pydantic-settings`
- `cryptography`
- `numpy`
- `pypdf`
- `python-docx`
- `PyMuPDF`
- `ocrmypdf`
- `playwright`

### Expert runtime packages

The expert runtime currently installs:

- `torch`
- `transformers`
- `peft`

## Caching and reuse

The packaging script caches staged payloads using fingerprints:

- OCR runtime stamp
- Backend Python runtime stamp
- Expert Python runtime stamp
- Playwright runtime stamp

For non-release builds, if the fingerprint and required files match, the script reuses the staged payload instead of rebuilding it.

This reduces Python dependency install time, but it does not reduce final installer compression time much because the package still has to be archived by Electron Builder and NSIS.

## Helper integrity and layout checks

### Helper manifest

`scripts/packaging/generate-helper-manifest.cjs` creates a hash manifest over:

- selected backend security-critical files
- packaged Python runtime binaries
- OCR binaries
- Playwright binaries

At runtime, Electron verifies the helper manifest before starting the backend.

### Layout audit

`scripts/packaging/audit-package-layout.cjs` checks that helper payloads do not overlap writable directories such as:

- Electron `userData`
- pre-vault storage
- active vault `.vault` directory

This is a packaging safety check to reduce helper tampering and writable/executable overlap.

## What happens when the user installs the app

The current package target is NSIS.

Electron Builder generates:

- `win-unpacked/`
- an intermediate `.nsis.7z` payload archive
- the final installer `test-0.1-Setup.exe`

The current installer is:

- not code-signed

Observed locally:

- `Get-AuthenticodeSignature` reports `NotSigned`

That matters because unsigned Windows installers often trigger additional verification and reputation checks.

## What happens when the user launches the installed app

### Main process startup

The Electron main process does this:

1. Requests a single-instance lock
2. Writes `desktop-runtime.log`
3. Calls `ensureBackend()`
4. If backend startup succeeds, creates the BrowserWindow and loads the packaged renderer
5. If backend startup fails, loads the startup repair page

### Single-instance behavior

If another instance already holds the lock:

- the new instance logs `single-instance lock unavailable; quitting`
- the new instance exits

This explains repeated log lines where a second launch appears to do nothing.

It does not explain why the original instance failed, only why subsequent launch attempts may vanish.

### Packaged backend verification before spawn

When packaged, `ensureBackend()` first runs:

- helper manifest verification
- helper layout audit

If either fails, backend launch is aborted before Python starts.

### Backend environment

For packaged runs, Electron builds a constrained child environment with:

- `CML_API_PREFIX`
- `CML_API_TOKEN`
- `CML_BACKEND_MODE`
- `CML_DATA_DIR`
- `CML_DATABASE_PATH`
- `CML_STARTUP_STATUS_PATH`
- `CML_VAULT_LOCK_OVERRIDE`
- `CML_LORA_RUNTIME_PYTHON`
- `PLAYWRIGHT_BROWSERS_PATH`
- `PYTHONPATH=<resources root>`
- `PYTHONHOME=<python-runtime root>`
- `PYTHONNOUSERSITE=1`

`PATH` is also restricted to the packaged Python runtimes and core Windows paths.

### Backend process launch

Electron spawns:

`python.exe -s -m uvicorn backend.app.main:app --host 127.0.0.1 --port <port>`

Current behavior:

- backend `stdout` and `stderr` are piped to `backend-stdout.log` and `backend-stderr.log` under Electron `userData`
- the main process also writes `desktop-runtime.log`

That closes the earlier observability gap where backend startup failures could disappear before `startup-status.json` was written.

### Backend startup sequence

Inside `backend/app/main.py`, startup does this:

1. Writes `starting`
2. Configures logging
3. If no active vault:
   - enters `pre_vault_mode`
   - initializes the database
   - writes `ready`
4. If an active vault exists:
   - acquires vault lock
   - initializes database
   - runs integrity check
   - runs migrations and schema verification
   - recovers jobs
   - queues reconciliation
   - starts background worker
   - writes `ready`

If startup fails after backend import succeeds, it attempts to write a failure status such as:

- `vault_lock_failed`
- `integrity_check_failed`
- `schema_check_failed`
- `startup_failed`

### Renderer startup

After backend startup succeeds, the packaged app starts a local renderer HTTP server from:

- `dist/server/index.js`

and serves static assets from:

- `dist/client`

Then the BrowserWindow loads:

- `http://127.0.0.1:<renderer-port>/`

If backend startup fails first, the app does not proceed to the normal packaged renderer UI.

## Validation scripts already present

Current validation scripts include:

- `scripts/packaging/validate-clean-machine-package.ps1`
- `scripts/packaging/smoke-packaged-runtime.ps1`
- `scripts/packaging/smoke-packaged-full-vault.ps1`
- `scripts/packaging/smoke-packaged-dynamic-link.ps1`
- `scripts/packaging/smoke-packaged-migration-drill.ps1`
- `scripts/packaging/smoke-packaged-app-launch.ps1`

These are useful, but they have a blind spot:

- they prove `win-unpacked` behavior more strongly than installed-NSIS behavior
- they do not currently preserve backend stderr from the actual Electron-managed packaged launch path

## Failures observed so far

### 1. Non-portable packaged Python runtime

Observed on VM:

- packaged `python.exe` tried to resolve `C:\Python314\python.exe`

Root cause:

- packaged venv-based runtime was not portable

Status:

- fixed by switching to copied base CPython runtimes

### 2. Missing packaged backend dependencies

Observed during packaged import probing:

- `backend.app.main` import failed because packaged backend runtime lacked at least `numpy`

Also identified:

- `cryptography` was imported by backend vault code but missing from packaged dependency list

Status:

- fixed in the package script and backend dependency metadata

### 3. Dev rebuilds taking too long

Observed behavior:

- a dev rebuild took roughly from `1:53 PM` to `2:40 PM`

What consumed the time:

- very large Python runtime staging
- expert runtime contents
- Playwright browser payload
- final NSIS/Electron Builder compression

The `.nsis.7z` payload alone reached about:

- `795,776,324` bytes

This is not a normal frontend-only rebuild. It is a heavy binary packaging run.

### 4. VM still showing backend startup failure

Observed from user testing:

- app shows startup repair screen
- message says backend did not start at `http://127.0.0.1:7343`
- `startup-status.json` was reportedly missing on VM

What this implies:

- either Python never started correctly
- or backend import failed before startup status could be written
- or helper verification/layout checks failed before spawn

Because Electron currently discards child stdout/stderr, the exact cause is not preserved by the app itself.

### 5. Local `win-unpacked` run showed blank screen

Observed from user report on this machine:

- unpacked build opened to a blank screen

What local logs currently show:

- local `startup-status.json` reached `ready`
- `desktop-runtime.log` shows packaged launches happened
- no backend startup failure was recorded in those logs

What this most likely means:

- the blank screen is more likely in the packaged renderer path than in backend boot
- or the app window was launched while another instance already existed
- or the renderer server returned an error page/empty page that is not currently logged in `desktop-runtime.log`

Current limitation:

- the app does not log packaged renderer fetch failures in a durable way

### 6. Installer showed “verifying installer” and then disappeared

Observed from user report on this machine:

- setup showed verifying installer
- then vanished without completing visibly

Facts currently confirmed:

- installer is unsigned
- installer has no Mark-of-the-Web alternate stream in the current local file copy

Likely possibilities:

- Windows reputation or SmartScreen behavior against an unsigned NSIS installer
- installer process exited early without user-visible diagnostics
- single silent exit due to environment-specific installer/runtime issue

What is not yet proven:

- the exact local reason for that installer disappearance

There is not yet enough installer-side logging in the current flow to state this conclusively.

## Packaging bugs and weaknesses identified

### Bug 1: Validation emphasizes `win-unpacked`, not installed app parity

Current state:

- we have strong checks for packaged files and direct runtime probing
- we have weaker instrumentation for post-NSIS installed execution

Impact:

- installer-specific or install-path-specific failures can slip through

### Bug 2: Renderer startup is under-instrumented

Current state:

- backend status is tracked
- renderer HTTP server issues are not durably logged with enough detail

Impact:

- blank-screen failures are difficult to distinguish from backend failures

### Bug 5: Package size is extreme for iteration

Current state:

- package ships full Python runtimes, OCR tools, Playwright, and model dependencies

Impact:

- slow dev package cycles
- larger attack surface
- larger chance of install-time friction

## Local facts confirmed during this investigation

- Current local packaged startup status file is present and currently reports `ready`
- Current local packaged startup path now writes `desktop-runtime.log`, `backend-stdout.log`, and `backend-stderr.log` under Electron `userData`
- Current installer `test-0.1-Setup.exe` is unsigned
- Current output directory contains:
  - `win-unpacked/`
  - `@cmldesktop-0.1.0-x64.nsis.7z`
  - `test-0.1-Setup.exe`

## What needs to be fixed next

These are the highest-value packaging fixes before another rebuild cycle:

1. Keep installed-app smoke coverage at parity with `win-unpacked` validation instead of relying mainly on unpacked runtime checks
2. Continue tightening renderer startup verification so blank-screen failures are classified more precisely
3. Decide whether unsigned local NSIS installers are acceptable for VM and local testing, or whether signing/reputation handling must become part of the workflow
4. Keep package/runtime notes current as the startup instrumentation and package command path evolve

## Current assessment

The packaging system is functional enough to produce a heavy local package and pass `win-unpacked` runtime checks, but it is not yet reliable enough in failure reporting.

The main problems are no longer just dependency bundling. The larger issue now is observability:

- the app can fail during install or early startup
- the current package flow does not preserve enough evidence to explain those failures quickly

That is the main packaging bug cluster at this stage.

## The real blocker now: observability failure

The Python portability problem was real, but it is no longer the central blocker.

The current blocker is this:

- when packaging or startup fails, the system often leaves too little evidence to explain why

That is the common thread across:

- VM startup failure
- blank packaged window
- installer verification then disappearance

### Critical: backend stdio is discarded

The Electron main process currently starts the backend with:

- `stdio: "ignore"`

Impact:

- Python import failures can disappear
- uvicorn boot failures can disappear
- native dependency load failures can disappear
- startup can fail before `startup-status.json` is ever written

This is currently the single highest-value packaging fix because every backend startup mystery remains harder than it should be until stdout, stderr, and process exit are captured durably.

### Critical: packaging configuration is split

We currently have two different installer definitions:

- static config in `apps/desktop/package.json`
- generated config in `scripts/packaging/package-windows.ps1`

Impact:

- local developers can test a different installer than the scripted flow produces
- `oneClick` behavior is currently inconsistent
- installer bugs can be misdiagnosed because the tested artifact depends on which command was used

This should be treated as a packaging bug, not just cleanup.

### High: installer behavior is under-tested

Our stronger validations target:

- `win-unpacked`
- direct runtime probing

But the user-visible failures are happening on:

- the installed app
- the NSIS installer path

That means we are still under-testing the actual distribution flow that users run.

### High: unsigned installer increases Windows friction

The current test installer is unsigned.

That does not prove SmartScreen was the reason the installer vanished, but it materially increases the chance of:

- verification prompts
- trust warnings
- reputation-related launch friction
- behavior differences across Windows images and VM snapshots

### Medium: blank screen is probably a renderer-side observability gap

When local startup status reaches `ready` but the app shows a blank screen, that points away from early backend boot failure and toward:

- packaged renderer server failure
- renderer asset serving failure
- invisible renderer exception path

The current logging is not strong enough to isolate that cleanly.

## What the investigation should prioritize next

This is the practical order of operations for packaging bugs.

1. Capture backend stdout, stderr, and exit code in the actual Electron packaged launch path
2. Unify packaging configuration so there is one source of truth for NSIS settings
3. Add a smoke test that exercises the actual installed NSIS app, not only `win-unpacked`
4. Decide whether test-build signing or other Windows trust mitigation is required for VM testing
5. Add renderer startup verification and durable logging for blank-screen cases

## Updated conclusion

At this point, the highest-risk packaging problem is no longer “can we bundle Python at all”.

It is:

- can we explain installer and startup failures with enough evidence to fix them quickly

Right now, the answer is still not reliably yes.
