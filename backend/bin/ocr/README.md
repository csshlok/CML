# Local OCR runtime

Vault packages its OCR dependencies from this directory so document extraction
works without relying on a machine-wide installation.

The runtime is staged by `scripts/packaging/stage-ocr-runtime.ps1`. Do not place
developer-specific paths or downloaded installers in this directory. The
packaging script supplies the Tesseract language data, qpdf, and Ghostscript
files used by the Windows build.
