# Bundled OCR Runtime

Stage the Windows OCR runtime here before packaging:

```text
backend/bin/ocr/tesseract.exe
backend/bin/ocr/tessdata/eng.traineddata
backend/bin/ocr/qpdf/qpdf.exe
backend/bin/ocr/ghostscript/bin/gswin64c.exe
```

Use `scripts/packaging/stage-ocr-runtime.ps1` before building the package. The
packaged Python runtime installs OCRmyPDF, while qpdf/Ghostscript/Tesseract live
in this local folder and are prepended to `PATH` only for OCR subprocesses.

The backend does not call any remote OCR service. Image OCR runs through bundled
Tesseract. Scanned-PDF OCR prefers OCRmyPDF plus Tesseract and falls back to direct
page rendering plus Tesseract if OCRmyPDF is unavailable during development.
