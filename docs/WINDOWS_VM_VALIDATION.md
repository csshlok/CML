# Windows VM Validation

Last updated: 2026-06-21

## Release Gate

Clean Windows VM validation remains a release blocker.

Required environment:

- fresh Windows VM
- no dev Python on PATH
- no Node on PATH
- no preinstalled OCR tools
- cold first run from the current packaged artifact

## Current State

The current checkout has a locally validated package artifact, but it has not been validated on a clean VM.

Evidence:

- `apps/desktop/release/win-unpacked`
- `apps/desktop/release/test-0.1.6-Setup.exe`
- `.tmp/clean-machine-package-validation-2026-06-21-after-installed-smokes.json` reports `pass=true` on the contributor machine.
- Local packaged runtime smoke passed with packaged Tesseract, Ghostscript, qpdf, image OCR, and PDF OCR.
- Local packaged app launch smoke reached `ready` with renderer readiness.
- Local installed-app startup smoke passed against `test-0.1.6-Setup.exe`.
- Local installer lifecycle smoke passed from a clean local registry state, installing to `%LOCALAPPDATA%\Programs\CML` and uninstalling cleanly.

The active blocker is:

- rerun the current installer and installed-app smoke sequence on a healthier clean VM image
- verify first-run parity for the current package
- capture installer/startup evidence from the actual VM run

## Current Known VM Problem

The latest context docs record that the recent Hyper-V attempt was not a trustworthy gate because the environment itself was unhealthy.

Observed issues in that run:

- the older packaged installer `CML-0.1.0-Setup.exe` crashed inside the guest with `System.dll` / `0xc0000005`
- the guest also showed Windows servicing/component-store failures
- PowerShell Direct sessions were unstable

That means the VM image itself was not reliable enough to certify or reject the package cleanly.

## Historical Context

Earlier package validation failures were dominated by missing packaged resources and non-portable runtime layout. Those failures are historical for the current artifact: the current package includes `resources/backend`, packaged Python runtime, expert runtime, Playwright payload, OCR manifest, and helper manifest.

## What Must Happen Next

1. Use a healthier clean Windows VM image.
2. Copy `apps/desktop/release/test-0.1.6-Setup.exe` to the VM.
3. Run the rebuilt packaged installer.
4. Validate installed-app first run, not only `win-unpacked`.
5. Run the clean-machine package validation and installed-app smoke sequence from the repo scripts if the repo is available in the VM.
6. Capture:
   - installer outcome
   - `startup-status.json`
   - `desktop-runtime.log`
   - `backend-stdout.log`
   - `backend-stderr.log`
7. Treat the gate as passed only after the current package succeeds in that environment.

## Current Assessment

Status: not release-cleared.

The current local package artifact is complete enough for local smokes, but clean VM validation remains unrun for this artifact.
