import os
import sys
import importlib.util
import subprocess
import tempfile
from pathlib import Path

from backend.app.core.config import ROOT_DIR, get_settings

IMAGE_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


class OCRError(RuntimeError):
    pass


def ocr_available() -> bool:
    return _tesseract_executable() is not None


def ocr_runtime_status() -> dict:
    tesseract = _tesseract_executable()
    ocrmypdf = _ocrmypdf_command()
    tessdata = tesseract.parent / "tessdata" / "eng.traineddata" if tesseract else None
    tesseract_usable = _tesseract_usable(tesseract) if tesseract else False
    ghostscript = _find_bundled_tool("ghostscript", ("gswin64c.exe", "gswin32c.exe", "gs.exe"))
    qpdf = _find_bundled_tool("qpdf", ("qpdf.exe",))
    image_ready = tesseract is not None and tesseract_usable and tessdata is not None and tessdata.exists()
    full_pdf_ready = image_ready and ocrmypdf is not None and ghostscript is not None and qpdf is not None
    fallback_pdf_ready = image_ready and _pymupdf_available()
    missing: list[str] = []
    if tesseract is None:
        missing.append("tesseract")
    elif not tesseract_usable:
        missing.append("working tesseract")
    if tessdata is None or not tessdata.exists():
        missing.append("eng.traineddata")
    if ocrmypdf is None:
        missing.append("ocrmypdf")
    if ghostscript is None:
        missing.append("ghostscript")
    if qpdf is None:
        missing.append("qpdf")
    if not _pymupdf_available():
        missing.append("pymupdf")
    pdf_engine = None
    if full_pdf_ready:
        pdf_engine = "ocrmypdf"
    elif fallback_pdf_ready:
        pdf_engine = "tesseract-render-fallback"
    return {
        "available": image_ready,
        "pdf_ocr_available": full_pdf_ready or fallback_pdf_ready,
        "image_ocr_available": image_ready,
        "pdf_ocr_engine": pdf_engine,
        "full_pdf_ocr_available": full_pdf_ready,
        "fallback_pdf_ocr_available": fallback_pdf_ready,
        "tesseract_path": str(tesseract) if tesseract else None,
        "ocrmypdf_command": " ".join(ocrmypdf) if ocrmypdf else None,
        "tessdata_path": str(tessdata) if tessdata and tessdata.exists() else None,
        "ghostscript_path": str(ghostscript) if ghostscript else None,
        "qpdf_path": str(qpdf) if qpdf else None,
        "missing": missing,
        "detail": _ocr_status_detail(image_ready, full_pdf_ready, fallback_pdf_ready, missing),
    }


def ocr_image(path: Path) -> str:
    executable = _require_tesseract()
    return _run_tesseract(executable, path)


def ocr_pdf_pages(path: Path) -> list[str]:
    executable = _require_tesseract()
    try:
        return _ocr_pdf_with_ocrmypdf(path, executable)
    except OCRError:
        return _ocr_pdf_pages_with_tesseract_render(path, executable)


def _ocr_pdf_with_ocrmypdf(path: Path, tesseract_executable: Path) -> list[str]:
    command = _ocrmypdf_command()
    if command is None:
        raise OCRError("OCRmyPDF is not available in the local OCR runtime.")

    with tempfile.TemporaryDirectory(prefix="vault-ocrmypdf-") as temp_dir:
        output_path = Path(temp_dir) / "searchable.pdf"
        full_command = [
            *command,
            "--force-ocr",
            "--deskew",
            "--optimize",
            "0",
            "--output-type",
            "pdf",
            str(path),
            str(output_path),
        ]
        env = _ocr_env(tesseract_executable)
        try:
            completed = subprocess.run(
                full_command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=1800,
                env=env,
            )
        except OSError as exc:
            raise OCRError(f"Could not run OCRmyPDF: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise OCRError("OCRmyPDF timed out.") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "Unknown OCRmyPDF error").strip()
            raise OCRError(detail[:500])
        if not output_path.exists():
            raise OCRError("OCRmyPDF did not produce a searchable PDF.")
        return _extract_pdf_pages_from_searchable_pdf(output_path)


def _extract_pdf_pages_from_searchable_pdf(path: Path) -> list[str]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise OCRError("OCRmyPDF output extraction requires pypdf in the bundled Python runtime.") from exc

    try:
        reader = PdfReader(str(path))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except Exception as exc:
        raise OCRError(f"Could not extract OCRmyPDF output text: {exc}") from exc
    if not any(page.strip() for page in pages):
        raise OCRError("OCRmyPDF produced no readable text.")
    return pages


def _ocr_pdf_pages_with_tesseract_render(path: Path, executable: Path) -> list[str]:
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
    env = _ocr_env(executable)
    try:
        completed = subprocess.run(
            [str(executable), str(input_path), "stdout", "-l", "eng"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
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


def _ocr_env(tesseract_executable: Path) -> dict[str, str]:
    env = os.environ.copy()
    tessdata = tesseract_executable.parent / "tessdata"
    if tessdata.exists():
        env["TESSDATA_PREFIX"] = str(tessdata)
    bin_dirs = [str(tesseract_executable.parent)]
    for tool in (
        _find_bundled_tool("ghostscript", ("gswin64c.exe", "gswin32c.exe", "gs.exe")),
        _find_bundled_tool("qpdf", ("qpdf.exe",)),
    ):
        if tool is not None:
            bin_dirs.append(str(tool.parent))
    env["PATH"] = os.pathsep.join(bin_dirs + [env.get("PATH", "")])
    return env


def _ocrmypdf_command() -> list[str] | None:
    settings = get_settings()
    candidates = []
    if settings.ocrmypdf_binary_path:
        candidates.append(settings.ocrmypdf_binary_path)
    candidates.extend(root / "ocrmypdf.exe" for root in _ocr_roots())
    for candidate in candidates:
        path = Path(candidate)
        if path.exists() and path.is_file():
            return [str(path)]
    if importlib.util.find_spec("ocrmypdf") is not None:
        return [sys.executable, "-m", "ocrmypdf"]
    return None


def _find_bundled_tool(folder_name: str, executable_names: tuple[str, ...]) -> Path | None:
    roots = _ocr_roots()
    for root in roots:
        for name in executable_names:
            direct = root / name
            nested = root / folder_name / name
            if direct.exists() and direct.is_file():
                return direct
            if nested.exists() and nested.is_file():
                return nested
            recursive = _find_child_file(root / folder_name, name)
            if recursive is not None:
                return recursive
    return None


def _find_child_file(root: Path, name: str) -> Path | None:
    if not root.exists():
        return None
    for candidate in root.rglob(name):
        if candidate.is_file():
            return candidate
    return None


def _require_tesseract() -> Path:
    executable = _tesseract_executable()
    if executable is None:
        raise OCRError("Bundled OCR engine is not available.")
    if not _tesseract_usable(executable):
        raise OCRError("Bundled OCR engine is not executable.")
    return executable


def _tesseract_executable() -> Path | None:
    settings = get_settings()
    candidates = []
    if settings.ocr_binary_path:
        candidates.append(settings.ocr_binary_path)
    candidates.extend(root / "tesseract.exe" for root in _ocr_roots())
    for candidate in candidates:
        path = Path(candidate)
        if path.exists() and path.is_file():
            return path
    return None


def _tesseract_usable(executable: Path) -> bool:
    try:
        completed = subprocess.run(
            [str(executable), "--version"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            env=_ocr_env(executable),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _ocr_roots() -> list[Path]:
    return [
        ROOT_DIR / "backend" / "bin" / "ocr",
        ROOT_DIR / "apps" / "desktop" / "packaging" / "backend" / "bin" / "ocr",
        Path(__file__).resolve().parents[2] / "bin" / "ocr",
    ]


def _pymupdf_available() -> bool:
    return importlib.util.find_spec("fitz") is not None


def _ocr_status_detail(
    image_ready: bool,
    full_pdf_ready: bool,
    fallback_pdf_ready: bool,
    missing: list[str],
) -> str:
    if full_pdf_ready:
        return "OCR runtime ready with OCRmyPDF, Tesseract, Ghostscript, and qpdf."
    if image_ready and fallback_pdf_ready:
        return "OCR runtime ready for images and fallback scanned-PDF OCR; OCRmyPDF acceleration is incomplete."
    if image_ready:
        return "Image OCR runtime ready; scanned-PDF OCR needs PyMuPDF or OCRmyPDF dependencies."
    return f"Missing OCR component(s): {', '.join(missing)}."
