# Windows VM Validation

Last updated: 2026-06-14

## Release Gate

Clean Windows VM validation remains a release blocker.

Required environment:

- fresh Windows VM
- no dev Python on PATH
- no Node on PATH
- no preinstalled OCR tools
- cold first run from the current packaged artifact

## Current State

The package has already moved past the old missing-resources failure mode.

That older state is useful only as historical context now.

The active blocker is:

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

Those are no longer the primary live issue.

Keep the old failures in mind only to avoid regression:

- missing `resources/backend`
- missing packaged Python runtime
- missing expert runtime
- missing Playwright payload
- missing OCR manifest
- missing helper manifest

## What Must Happen Next

1. Use a healthier clean Windows VM image.
2. Run the current packaged installer.
3. Validate installed-app first run, not only `win-unpacked`.
4. Capture:
   - installer outcome
   - `startup-status.json`
   - `desktop-runtime.log`
   - `backend-stdout.log`
   - `backend-stderr.log`
5. Treat the gate as passed only after the current package succeeds in that environment.

## Current Assessment

Status: not release-cleared.

The blocker is no longer “the package is obviously incomplete.”
The blocker is “the current package still needs a trustworthy clean-VM pass.”
