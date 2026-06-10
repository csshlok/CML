# Retrieval Benchmarks

Date: 2026-06-10

Audit source: `docs/RELEASE_AUDIT.md`

## Release Gate

The release audit treats retrieval validation as part of the public V1 release evidence. It calls out larger user-owned vault benchmarks and broader retrieval threshold tuning as remaining release-risk work.

## Current Evidence

| Check | Result | Evidence |
| --- | --- | --- |
| Desktop build sanity | Passed | `npm run build` completed successfully after rerunning outside the filesystem sandbox. Vite built both client and SSR bundles. |
| Retrieval benchmark command | Blocked | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backend\benchmark-retrieval.ps1 -Sources 100` could not run because the local Python launcher resolves to a missing Windows Store Python executable. |
| Backend test baseline | Blocked in this pass | `py -3.12 -m pytest -q backend/tests` could not start for the same missing Python launcher reason. |
| Prior audit baseline | Informational only | `docs/RELEASE_AUDIT.md` records `189 passed, 1 skipped` for backend tests and notes that larger retrieval benchmarks remain unproven. |

## Command Evidence

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backend\benchmark-retrieval.ps1 -Sources 100
```

Result:

```text
No Python at '"C:\Users\KIIT0001\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\python.exe'
```

```powershell
py -3.12 -m pytest -q backend/tests
```

Result:

```text
Unable to create process using '"C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.12_3.12.2800.0_x64__qbz5n2kfra8p0\python3.12.exe" -m pytest -q backend/tests'
```

## Release Assessment

Status: not release-cleared.

This artifact satisfies the missing documentation requirement from the release audit, but it does not close the retrieval benchmark blocker. Public V1 still needs a successful retrieval benchmark run on a working release validation machine, including the larger user-owned vault or equivalent natural-corpus benchmark called out in `docs/PROJECT_CONTEXT.md`.

