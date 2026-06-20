# Windows VM Validation

Last updated: 2026-06-20

## Release Gate

Clean Windows VM validation remains a release blocker.

Required environment:

- fresh Windows VM
- no dev Python on PATH
- no Node on PATH
- no preinstalled OCR tools
- cold first run from the current packaged artifact

## Current State

The current checked-out package artifact is not valid for clean VM launch validation.

On 2026-06-20, local validation against `apps/desktop/release/win-unpacked` reported missing packaged resources:

- `resources/backend`
- `resources/python-runtime/python.exe`
- `resources/expert-python-runtime/python.exe`
- `resources/ms-playwright`
- `resources/backend/bin/ocr/manifest.json`
- `resources/helper-manifest.json`

Evidence:

- `.tmp/clean-machine-package-validation-2026-06-20.json`
- `scripts/packaging/smoke-packaged-runtime.ps1 -PackageRoot apps/desktop/release/win-unpacked -Port 7464` failed on missing packaged Python runtime.
- `scripts/packaging/smoke-packaged-app-launch.ps1 -PackageRoot apps/desktop/release/win-unpacked -TimeoutSeconds 45` failed because the packaged app did not write fresh startup status.

The active blocker is:

- rebuild a complete package artifact
- rerun packaged runtime, packaged app launch, installed-app launch, and installer lifecycle smokes locally
- rerun the current installer and installed-app smoke sequence on a healthier clean VM image
- verify first-run parity for the current package
- capture installer/startup evidence from the actual VM run

## Current Known VM Problem

The latest context docs record that the recent Hyper-V attempt was not a trustworthy gate because the environment itself was unhealthy.

Observed issues in that run:

- the packaged installer `CML-0.1.0-Setup.exe` crashed inside the guest with `System.dll` / `0xc0000005`
- the guest also showed Windows servicing/component-store failures
- PowerShell Direct sessions were unstable

That means the VM image itself was not reliable enough to certify or reject the package cleanly.

## Historical Context

Earlier package validation failures were dominated by missing packaged resources and non-portable runtime layout.

Those failures are present again in the current checked-out artifact, so do not send this artifact to a clean VM until it has been rebuilt and local package validation is green.

Current missing-resource failures to eliminate:

- missing `resources/backend`
- missing packaged Python runtime
- missing expert runtime
- missing Playwright payload
- missing OCR manifest
- missing helper manifest

## What Must Happen Next

1. Rebuild a complete Windows package artifact.
2. Rerun local package structure/runtime/app-launch/installed-app smokes.
3. Use a healthier clean Windows VM image.
4. Run the rebuilt packaged installer.
5. Validate installed-app first run, not only `win-unpacked`.
6. Capture:
   - installer outcome
   - `startup-status.json`
   - `desktop-runtime.log`
   - `backend-stdout.log`
   - `backend-stderr.log`
7. Treat the gate as passed only after the current package succeeds in that environment.

## Current Assessment

Status: not release-cleared.

The current local package artifact is incomplete, so clean VM validation is blocked until a complete artifact is rebuilt and local package smokes pass.
