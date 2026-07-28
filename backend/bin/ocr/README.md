# Local OCR Runtime

This directory is populated by `scripts/packaging/stage-ocr-runtime.ps1`.
The staging script assembles Tesseract, English language data, qpdf, and
Ghostscript into a self-contained runtime used by Windows packages.

Binary payloads are generated locally and ignored by Git. `manifest.json`
records only portable capability state and must not contain build-machine
paths.
