param(
  [Parameter(Mandatory = $true)][string]$PdfPath,
  [Parameter(Mandatory = $true)][string]$ReferenceTextPath,
  [string]$TesseractExePath = "",
  [string]$ReportPath = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$pdf = [System.IO.Path]::GetFullPath($PdfPath)
$reference = [System.IO.Path]::GetFullPath($ReferenceTextPath)
if (-not $ReportPath) {
  $ReportPath = Join-Path $repoRoot ".tmp\ocr-benchmark-report.md"
}
$report = [System.IO.Path]::GetFullPath($ReportPath)
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $report) | Out-Null

if ($TesseractExePath) {
  $env:CML_OCR_BINARY_PATH = [System.IO.Path]::GetFullPath($TesseractExePath)
}

@"
from __future__ import annotations
import re
from difflib import SequenceMatcher
from pathlib import Path

from backend.app.core.extraction import extract_pages_from_path
from backend.app.core.ocr import ocr_runtime_status

pdf = Path(r"$pdf")
reference_path = Path(r"$reference")
report = Path(r"$report")
reference = reference_path.read_text(encoding="utf-8", errors="replace")
status = ocr_runtime_status()
_title, pages = extract_pages_from_path(str(pdf))
ocr_text = "\n\n".join(pages)

def norm(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return re.sub(r"\s+", " ", value).strip()

def words(value: str) -> set[str]:
    return {word for word in norm(value).split() if len(word) > 2}

reference_words = words(reference)
ocr_words = words(ocr_text)
overlap = reference_words & ocr_words
similarity = SequenceMatcher(None, norm(reference), norm(ocr_text)).ratio()
recall = len(overlap) / max(len(reference_words), 1)
precision = len(overlap) / max(len(ocr_words), 1)

lines = [
    "# OCR Benchmark Report",
    "",
    f"- PDF: `{pdf}`",
    f"- Reference: `{reference_path}`",
    f"- OCR detail: `{status['detail']}`",
    f"- OCR engine: `{status['pdf_ocr_engine']}`",
    f"- Pages OCRed: `{len(pages)}`",
    f"- Extracted characters: `{len(ocr_text)}`",
    f"- Normalized sequence similarity: `{similarity:.4f}`",
    f"- Word recall: `{recall:.4f}`",
    f"- Word precision: `{precision:.4f}`",
    "",
    "## Sample OCR Output",
    "",
    "```text",
    ocr_text[:3000],
    "```",
]
report.write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines[:11]))
"@ | .\.venv\Scripts\python -
