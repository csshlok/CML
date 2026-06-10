# Windows VM Validation

Date: 2026-06-10

Audit source: `docs/RELEASE_AUDIT.md`

## Release Gate

The audit marks clean Windows VM package validation as a release blocker. The required environment is a fresh Windows VM with no dev Python, no Node, no preinstalled OCR tools, and a cold first run from the packaged artifact.

## Current Package Probe

Command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\packaging\validate-clean-machine-package.ps1 -PackageRoot apps\desktop\release\win-unpacked -ReportPath .tmp\phase4-clean-machine-package-validation.json
```

Result: failed.

The generated report is `.tmp\phase4-clean-machine-package-validation.json`.

Phase 5 rerun:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\packaging\validate-clean-machine-package.ps1 -PackageRoot apps\desktop\release\win-unpacked -ReportPath .tmp\phase5-clean-machine-package-validation.json
```

Result: failed with the same missing packaged resource checks.

Packaged runtime smoke:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\packaging\smoke-packaged-runtime.ps1 -PackageRoot apps\desktop\release\win-unpacked
```

Result:

```text
Packaged Python runtime not found: C:\Users\KIIT0001\Desktop\Project-2\CML\apps\desktop\release\win-unpacked\resources\python-runtime\Scripts\python.exe
```

## Failed Checks

| Check | Expected path | Result |
| --- | --- | --- |
| `backend_exists` | `apps\desktop\release\win-unpacked\resources\backend` | Missing |
| `python_runtime_exists` | `apps\desktop\release\win-unpacked\resources\python-runtime\Scripts\python.exe` | Missing |
| `expert_python_runtime_exists` | `apps\desktop\release\win-unpacked\resources\expert-python-runtime\Scripts\python.exe` | Missing |
| `playwright_runtime_exists` | `apps\desktop\release\win-unpacked\resources\ms-playwright` | Missing |
| `ocr_manifest_exists` | `apps\desktop\release\win-unpacked\resources\backend\bin\ocr\manifest.json` | Missing |
| `helper_manifest_exists` | `apps\desktop\release\win-unpacked\resources\helper-manifest.json` | Missing |

Package contents observed under `apps\desktop\release\win-unpacked\resources`:

```text
app.asar
app.asar.unpacked
elevate.exe
```

## Host Tool Findings

The validator also reported:

| Host tool | Detected |
| --- | --- |
| Python on PATH | No |
| Node on PATH | Yes |
| Tesseract on PATH | No |
| Ghostscript on PATH | No |

Because Node is present and this is not a fresh VM, this machine does not satisfy the clean-VM requirement even if package structure were fixed.

## Release Assessment

Status: not release-cleared.

This artifact satisfies the Windows VM validation document requirement, but it does not close the clean-machine blocker. The current unpacked package is missing required runtime resources before VM validation can be considered meaningful.
