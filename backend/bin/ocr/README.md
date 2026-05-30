# Bundled OCR Runtime

Place the Windows Tesseract runtime here before packaging:

```text
backend/bin/ocr/tesseract.exe
backend/bin/ocr/tessdata/eng.traineddata
```

The backend does not call any remote OCR service. Image OCR and scanned-PDF OCR only run when this bundled local binary is present in the installed app.
