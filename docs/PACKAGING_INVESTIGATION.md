# Packaging Investigation

> Historical investigation record. Verify current packaging behavior against the scripts and
> `docs/PROJECT_CONTEXT.md` before treating a status or blocker below as current.

Last updated: 2026-06-14

## Scope

This document tracks the current Windows packaging state, the major packaging decisions already landed, the old failure modes that are now historical, and the real remaining blocker.

## Current Packaging State

The Windows packaging path is now materially more mature than the older missing-runtime phase.

Current repo state:

- packaging is orchestrated through `scripts/packaging/package-windows.ps1`
- `apps/desktop/package.json` delegates `package:win` to that script
- helper manifest generation and package-layout audit are part of the packaging flow
- packaged startup logging now includes:
  - `desktop-runtime.log`
  - `backend-stdout.log`
  - `backend-stderr.log`
  - `startup-status.json`
- the repo now has both unpacked-app and installed-app smoke coverage

Primary files:

- `scripts/packaging/package-windows.ps1`
- `scripts/packaging/validate-clean-machine-package.ps1`
- `scripts/packaging/smoke-packaged-app-launch.ps1`
- `scripts/packaging/smoke-installed-app.ps1`
- `apps/desktop/electron/main.cjs`

## Packaging Architecture

The packaged app bundles:

- Electron shell
- Vite-built renderer
- Python backend runtime
- expert Python runtime
- OCR tooling
- Playwright Chromium

The package is a full local multi-runtime bundle, not a thin frontend shell.

## Old Problems That Are Now Historical

These were real issues, but they are no longer the primary live blocker:

- non-portable packaged Python runtime
- missing packaged backend dependencies
- missing packaged resources in `win-unpacked`
- weak backend startup observability caused by discarded stdio
- split/ambiguous packaging config assumptions

Current code no longer supports the older “backend stdio is discarded” claim:

- Electron now starts the backend with piped stdout/stderr
- packaged startup logs are written under Electron `userData`

Current code also no longer supports the older “package config is effectively split” concern as the main packaging truth:

- the actual package flow is now single-sourced through `scripts/packaging/package-windows.ps1`
- `apps/desktop/package.json` points `package:win` at that script

## What Is Actually Still Open

The real blocker now is not missing architecture. It is release-grade validation.

Still open:

- healthy clean-VM validation of the current packaged installer
- installed-app first-run parity on a healthy clean VM
- any installer/runtime failures reproduced there
- continued renderer/startup observability if new failures appear

## Validation Surface That Exists Today

Current validation scripts include:

- `scripts/packaging/validate-clean-machine-package.ps1`
- `scripts/packaging/smoke-packaged-runtime.ps1`
- `scripts/packaging/smoke-packaged-full-vault.ps1`
- `scripts/packaging/smoke-packaged-dynamic-link.ps1`
- `scripts/packaging/smoke-packaged-migration-drill.ps1`
- `scripts/packaging/smoke-packaged-app-launch.ps1`
- `scripts/packaging/smoke-installed-app.ps1`

This is materially better coverage than the older state where `win-unpacked` dominated the proof story.

## Current Remaining Risk

The package still is not release-cleared because the clean-VM evidence is not trustworthy yet.

The most recent VM attempt was undermined by the VM image itself:

- installer crash inside the guest
- Windows servicing/component-store instability
- unstable VM control path

So the current blocker is a healthy environment rerun, not the older missing-runtime bug cluster.

## Practical Next Steps

1. rerun the current installer on a healthier clean Windows VM
2. validate installed-app startup and first-run behavior there
3. preserve startup/install evidence from the VM run
4. keep the packaging docs aligned with current reality so contributors do not chase the superseded missing-resource state

## Current Assessment

Status: packaging flow is functional and heavily instrumented, but not yet release-cleared.

The main issue is now validation confidence on a trustworthy clean machine, not the older inability to package the app structure correctly.
