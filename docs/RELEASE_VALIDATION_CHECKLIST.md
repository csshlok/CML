# Release Validation Checklist

Run these checks from the repository root on a Windows release machine. Each item below includes the exact command, expected output, and clear pass/fail criteria for release sign-off.

## 1. Backend validation

- [ ] Command
  ```powershell
  .\.venv\Scripts\python.exe -m pytest -q backend/tests
  ```
- [ ] Expected output
  - `189 passed, 1 skipped` (current verified baseline)
  - Exit code `0`
- [ ] Pass criteria
  - Pytest completes with exit code `0`
  - No test failures
  - No unexpected backend regressions in the core routes, jobs, OCR, embeddings, or expert flows
- [ ] Fail criteria
  - Any test fails or errors
  - Pytest exits non-zero
  - New backend regression appears in the release-critical path

## 2. Desktop application validation

- [ ] Command
  ```powershell
  cd apps/desktop
  npm run build
  ```
- [ ] Expected output
  - Vite production build completes with `✓ built in ...`
  - Client and SSR bundles are emitted under `apps/desktop/dist/`
- [ ] Pass criteria
  - `npm run build` exits `0`
  - Production assets are generated without fatal errors
- [ ] Fail criteria
  - Build exits non-zero
  - Missing or broken bundle output
  - Runtime compile errors in the desktop renderer or server path

## 3. OCR validation

- [ ] Command
  ```powershell
  .\scripts\ocr\benchmark-ocr.ps1 -PdfPath .tmp\sample.pdf -ReferenceTextPath .tmp\reference.txt
  ```
- [ ] Expected output
  - OCR benchmark report prints similarity, recall, and precision metrics
  - The command completes without OCR runtime errors
- [ ] Pass criteria
  - Benchmark command exits `0`
  - OCR text is produced for the supplied sample PDF
  - Similarity/recall/precision remain within the project’s accepted release threshold
- [ ] Fail criteria
  - OCR command fails, times out, or returns no readable text
  - OCR metrics are materially below the accepted threshold
  - OCR runtime is marked unavailable or partial when release packaging requires OCR

## 4. Embeddings validation

- [ ] Command
  ```powershell
  Invoke-RestMethod -Uri http://127.0.0.1:7343/api/v1/models/embeddings
  ```
- [ ] Expected output
  - JSON payload with an embedding provider and runtime status
  - The provider should be a real local runtime path, not a placeholder or hash-only fallback in release validation
- [ ] Pass criteria
  - Endpoint returns `200` and a valid provider/status object
  - Embedding runtime is available for the release configuration
  - No missing or malformed embedding setup data is returned
- [ ] Fail criteria
  - Endpoint errors or returns an empty provider/status object
  - Embedded runtime is unavailable or misconfigured
  - Hash-only fallback is used when a real embedding runtime is required for release validation

## 5. Expert routing validation

- [ ] Command
  ```powershell
  .\scripts\backend\smoke-lora-expert.ps1 -AllowTestTrainer
  ```
- [ ] Expected output
  - A smoke report is written to `.tmp/lora-expert-smoke-report.json`
  - The script prints that the expert smoke report was written successfully
- [ ] Pass criteria
  - Script exits `0`
  - Report contains non-empty expert artifacts and a passing retrieval-vs-adapter comparison
  - Expert status is searchable and ready for the smoke path
- [ ] Fail criteria
  - Script exits non-zero
  - No expert artifact is produced
  - Expert status is not searchable or the comparison does not pass

## 6. Packaging validation

- [ ] Command
  ```powershell
  cd apps/desktop
  npm run package:win
  ```
- [ ] Expected output
  - Electron Builder completes and writes a Windows installer/artifact under `apps/desktop/release/`
  - Unpacked runtime appears under `apps/desktop/release/win-unpacked/`
- [ ] Pass criteria
  - Packaging command exits `0`
  - Installer and unpacked output are present
  - Required packaged resources exist under `resources/`
- [ ] Fail criteria
  - Packaging exits non-zero
  - Installer or unpacked package is missing
  - Required packaged backend/runtime assets are absent

## 7. Clean-machine validation

- [ ] Command
  ```powershell
  pwsh -File scripts/packaging/validate-clean-machine-package.ps1 -PackageRoot apps/desktop/release/win-unpacked
  ```
- [ ] Expected output
  - JSON summary with `pass = true`
  - All key package checks report `ok = true`
- [ ] Pass criteria
  - Script exits `0`
  - Package root, backend, bundled runtime, OCR manifest, and smoke scripts are all present
  - The clean-machine report marks the package ready for VM validation
- [ ] Fail criteria
  - Script exits non-zero
  - Any package asset or validation check is missing or false
  - The report indicates the package is not ready for clean-machine testing

## 8. Performance validation

- [ ] Command
  ```powershell
  pwsh -File scripts/backend/benchmark-backend.ps1 -Sources 250 -WordsPerSource 240 -ReportPath .tmp\backend-benchmark-report.md
  ```
- [ ] Expected output
  - Markdown benchmark report is written to `.tmp/backend-benchmark-report.md`
  - The report includes insert, index, search, and repair/compact timing measurements
- [ ] Pass criteria
  - Benchmark command exits `0`
  - Report is generated successfully
  - Timing and result counts are within the release-performance envelope for the target machine
- [ ] Fail criteria
  - Benchmark command fails or writes no report
  - Performance results are outside the accepted release budget
  - Search or repair operations fail or return unusable results

## Release sign-off rule

- [ ] All eight checks above must pass before the release is declared ready for public validation.
- [ ] Any failure must be investigated, documented, and re-verified before release approval.
