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

The current checkout does not have a valid package artifact for clean VM launch validation.

After the 2026-06-20 rebuild attempt failed, local validation against `apps/desktop/release/win-unpacked` reported that the package root itself is absent:

- `package_root_exists=false`
- `resources_exists=false`
- all packaged runtime/resource checks are false because the package root was not produced

Evidence:

- `.tmp/clean-machine-package-validation-2026-06-20.json`
- `scripts/packaging/smoke-packaged-runtime.ps1 -PackageRoot apps/desktop/release/win-unpacked -Port 7464` failed with `Packaged app root not found`.
- `scripts/packaging/smoke-packaged-app-launch.ps1 -PackageRoot apps/desktop/release/win-unpacked -TimeoutSeconds 45` failed with `Packaged app executable not found`.
- `npm run package:win --workspace @cml/desktop` was rerun on 2026-06-20. It passed the renderer build, downloaded OCR runtime inputs, and failed during OCR staging because the downloaded Tesseract installer did not provide a portable `tesseract.exe`; Ghostscript staging also reported `The operation was canceled by the user`.

The active blocker is:

- provide real portable OCR tool paths or fix OCR installer extraction, then rebuild a complete package artifact
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
