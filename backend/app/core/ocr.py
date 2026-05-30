import os
import subprocess
import tempfile
from pathlib import Path

from backend.app.core.config import ROOT_DIR, get_settings

IMAGE_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


class OCRError(RuntimeError):
    pass


def ocr_available() -> bool:
    return _tesseract_executable() is not None


def ocr_image(path: Path) -> str:
    executable = _require_tesseract()
    return _run_tesseract(executable, path)


def ocr_pdf_pages(path: Path) -> list[str]:
    executable = _require_tesseract()
    try:
        import fitz
    except ImportError as exc:
        raise OCRError("Scanned PDF OCR requires PyMuPDF in the bundled Python runtime.") from exc

    pages: list[str] = []
    try:
        document = fitz.open(str(path))
    except Exception as exc:
        raise OCRError(f"Could not render PDF for OCR: {exc}") from exc

    with tempfile.TemporaryDirectory(prefix="vault-ocr-") as temp_dir:
        temp_path = Path(temp_dir)
        for index, page in enumerate(document, start=1):
            image_path = temp_path / f"page-{index}.png"
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            pixmap.save(str(image_path))
            pages.append(_run_tesseract(executable, image_path))
    return pages


def _run_tesseract(executable: Path, input_path: Path) -> str:
    env = os.environ.copy()
    tessdata = executable.parent / "tessdata"
    if tessdata.exists():
        env["TESSDATA_PREFIX"] = str(tessdata)
    try:
        completed = subprocess.run(
            [str(executable), str(input_path), "stdout", "-l", "eng"],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
    except OSError as exc:
        raise OCRError(f"Could not run bundled OCR engine: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise OCRError("Bundled OCR engine timed out.") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "Unknown OCR error").strip()
        raise OCRError(detail[:500])
    return completed.stdout.strip()


def _require_tesseract() -> Path:
    executable = _tesseract_executable()
    if executable is None:
        raise OCRError("Bundled OCR engine is not available.")
    return executable


def _tesseract_executable() -> Path | None:
    settings = get_settings()
    candidates = []
    if settings.ocr_binary_path:
        candidates.append(settings.ocr_binary_path)
    candidates.extend(
        [
            ROOT_DIR / "backend" / "bin" / "ocr" / "tesseract.exe",
            ROOT_DIR / "apps" / "desktop" / "packaging" / "backend" / "bin" / "ocr" / "tesseract.exe",
            Path(__file__).resolve().parents[2] / "bin" / "ocr" / "tesseract.exe",
        ]
    )
    for candidate in candidates:
        path = Path(candidate)
        if path.exists() and path.is_file():
            return path
    return None
