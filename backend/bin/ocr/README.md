# Bundled OCR Runtime

Place the Windows OCRmyPDF + Tesseract runtime here before packaging:

```text
backend/bin/ocr/tesseract.exe
backend/bin/ocr/tessdata/eng.traineddata
backend/bin/ocr/ocrmypdf.exe
```

OCRmyPDF also needs local command dependencies available on `PATH`, especially
Ghostscript and qpdf. For packaged builds, stage those under the OCR runtime folder
and keep `tesseract.exe` in the same folder so the backend can prepend the bundled
runtime to `PATH` before running OCRmyPDF.

The backend does not call any remote OCR service. Image OCR runs through bundled
Tesseract. Scanned-PDF OCR prefers OCRmyPDF plus Tesseract and falls back to direct
page rendering plus Tesseract if OCRmyPDF is unavailable during development.
