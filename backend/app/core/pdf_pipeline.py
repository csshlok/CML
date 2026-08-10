from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from backend.app.core.config import ROOT_DIR, get_settings
from backend.app.core.ocr import OCRError, ocr_pdf_pages


class PdfPipelineError(RuntimeError):
    pass


def extract_pdf_document(source_path: str | Path) -> dict:
    path = Path(source_path)
    plan = pdf_parser_runtime_status()
    backend = str(plan["selected_backend"] or "builtin")
    issues: list[str] = []
    if backend == "opendataloader_pdf":
        try:
            return _extract_opendataloader_pdf_document(path, plan)
        except PdfPipelineError as exc:
            issues.append(str(exc))
            if str(plan["configured_backend"]) == "opendataloader":
                raise
    document = _extract_builtin_pdf_document(path)
    if issues:
        document["parser"]["issues"] = [*document["parser"].get("issues", []), *issues]
        document["parser"]["fallback_from"] = "opendataloader_pdf"
    return document


def extract_pdf_document_with_backend(source_path: str | Path, backend: str) -> dict:
    path = Path(source_path)
    selected = str(backend or "builtin").strip().lower()
    plan = pdf_parser_runtime_status()
    if selected == "opendataloader":
        selected = "opendataloader_pdf"
    if selected == "opendataloader_pdf":
        return _extract_opendataloader_pdf_document(path, plan)
    if selected != "builtin":
        raise PdfPipelineError(f"Unknown PDF parser backend: {backend}")
    return _extract_builtin_pdf_document(path)


def pdf_parser_runtime_status() -> dict:
    settings = get_settings()
    configured = str(getattr(settings, "pdf_parser_backend", "auto") or "auto").strip().lower()
    available = ["builtin"]
    issues: list[str] = []
    command = _opendataloader_command()
    opendataloader_ready = bool(command)
    if opendataloader_ready:
        available.append("opendataloader_pdf")
    elif configured in {"auto", "opendataloader"}:
        issues.append("OpenDataLoader PDF runtime is not available; falling back to builtin parser.")
    if configured == "builtin":
        selected = "builtin"
    elif configured == "opendataloader":
        selected = "opendataloader_pdf" if opendataloader_ready else "builtin"
    else:
        selected = "opendataloader_pdf" if opendataloader_ready else "builtin"
    return {
        "configured_backend": configured,
        "selected_backend": selected,
        "available_backends": available,
        "opendataloader_command": command or "",
        "runtime_python": _runtime_python(),
        "timeout_seconds": int(getattr(settings, "pdf_parser_timeout_seconds", 180) or 180),
        "issues": issues,
    }


def _extract_builtin_pdf_document(source_path: Path) -> dict:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise PdfPipelineError("PDF extraction requires pypdf to be installed") from exc

    try:
        reader = PdfReader(str(source_path))
        raw_pages = [(page.extract_text() or "").strip() for page in reader.pages]
        source_page_count = len(reader.pages)
    except Exception as exc:
        raise PdfPipelineError(f"Could not read PDF file: {exc}") from exc

    readable_pages = [page for page in raw_pages if page.strip()]
    parser = {
        "backend": "builtin",
        "mode": "text",
        "source_page_count": source_page_count,
        "page_count": len(readable_pages),
        "used_ocr": False,
        "issues": [],
        "canonical_markdown": "",
        "structured_tables": [],
        "bounding_boxes": [],
    }
    if not readable_pages:
        if os.environ.get("CML_DEFER_PDF_OCR", "").strip().lower() in {"1", "true", "yes", "on"}:
            fallback = _pdf_metadata_fallback(source_path, detail="OCR queued as a separate background stage.")
            parser["mode"] = "metadata_fallback"
            parser["issues"] = ["OCR deferred to the bounded ocr_cpu worker."]
            parser["page_count"] = 1
            parser["canonical_markdown"] = fallback
            parser["ocr_deferred"] = True
            return {"title": source_path.name, "pages": [fallback], "parser": parser}
        try:
            ocr_pages = ocr_pdf_pages(source_path)
        except OCRError as exc:
            fallback = _pdf_metadata_fallback(source_path, detail=str(exc))
            parser["mode"] = "metadata_fallback"
            parser["issues"] = [str(exc)]
            parser["page_count"] = 1
            parser["canonical_markdown"] = fallback
            return {"title": source_path.name, "pages": [fallback], "parser": parser}
        readable_ocr_pages = [page for page in ocr_pages if page.strip()]
        if not readable_ocr_pages:
            fallback = _pdf_metadata_fallback(source_path)
            parser["mode"] = "metadata_fallback"
            parser["page_count"] = 1
            parser["canonical_markdown"] = fallback
            return {"title": source_path.name, "pages": [fallback], "parser": parser}
        readable_pages = _split_text_pages("\n\n".join(readable_ocr_pages))
        parser["mode"] = "ocr"
        parser["used_ocr"] = True
    else:
        readable_pages = _split_text_pages("\n\n".join(readable_pages))
    parser["page_count"] = len(readable_pages)
    parser["canonical_markdown"] = "\n\n".join(readable_pages).strip()
    return {
        "title": source_path.name,
        "pages": readable_pages,
        "parser": parser,
    }


def _extract_opendataloader_pdf_document(source_path: Path, plan: dict) -> dict:
    command = _worker_command()
    if not command:
        raise PdfPipelineError("OpenDataLoader PDF worker command is not available.")
    try:
        completed = subprocess.run(
            [*command, str(source_path)],
            capture_output=True,
            text=True,
            timeout=int(plan["timeout_seconds"]),
            cwd=str(ROOT_DIR),
        )
    except subprocess.TimeoutExpired as exc:
        raise PdfPipelineError("OpenDataLoader PDF worker timed out.") from exc
    except OSError as exc:
        raise PdfPipelineError(f"OpenDataLoader PDF worker failed to launch: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "OpenDataLoader PDF worker failed").strip()
        raise PdfPipelineError(detail[:500])
    try:
        payload = _parse_json_payload(completed.stdout or "")
    except json.JSONDecodeError as exc:
        raise PdfPipelineError("OpenDataLoader PDF worker returned malformed JSON.") from exc
    if not isinstance(payload, dict):
        raise PdfPipelineError("OpenDataLoader PDF worker returned invalid output.")
    title = str(payload.get("title") or source_path.name).strip() or source_path.name
    pages = payload.get("pages")
    parser = payload.get("parser")
    if not isinstance(pages, list) or not pages:
        raise PdfPipelineError("OpenDataLoader PDF worker produced no readable pages.")
    clean_pages = [str(page).strip() for page in pages if str(page).strip()]
    if not clean_pages:
        raise PdfPipelineError("OpenDataLoader PDF worker produced empty pages.")
    if not isinstance(parser, dict):
        parser = {}
    parser["backend"] = "opendataloader_pdf"
    parser["page_count"] = len(clean_pages)
    parser.setdefault("issues", [])
    return {
        "title": title[:240],
        "pages": clean_pages,
        "parser": parser,
    }


def _worker_command() -> list[str]:
    runtime_python = _runtime_python()
    if not runtime_python:
        return []
    return [runtime_python, "-m", "backend.app.core.opendataloader_pdf_worker"]


def _runtime_python() -> str:
    settings = get_settings()
    configured = str(getattr(settings, "pdf_parser_runtime_python", "") or "").strip()
    return configured or sys.executable


def _opendataloader_command() -> str | None:
    settings = get_settings()
    configured = str(getattr(settings, "opendataloader_pdf_command", "") or "").strip()
    if configured:
        return configured
    return _runtime_python()


def _parse_json_payload(raw: str) -> dict:
    text = str(raw or "").strip()
    if not text:
        raise json.JSONDecodeError("empty payload", text, 0)
    first_brace = text.find("{")
    if first_brace < 0:
        raise json.JSONDecodeError("missing json object", text, 0)
    decoder = json.JSONDecoder()
    payload, _end = decoder.raw_decode(text[first_brace:])
    return payload


def _split_text_pages(text: str, *, max_page_bytes: int = 256 * 1024) -> list[str]:
    normalized = str(text or "").strip()
    if not normalized:
        return []
    pages: list[str] = []
    current: list[str] = []
    current_bytes = 0
    for line in normalized.splitlines():
        candidate = line if not current else f"\n{line}"
        candidate_bytes = len(candidate.encode("utf-8"))
        if candidate_bytes > max_page_bytes:
            if current:
                pages.append("".join(current).strip())
                current = []
                current_bytes = 0
            pages.extend(_split_long_text_line(line, max_page_bytes=max_page_bytes))
            continue
        if current and current_bytes + candidate_bytes > max_page_bytes:
            pages.append("".join(current).strip())
            current = [line]
            current_bytes = len(line.encode("utf-8"))
            continue
        current.append(candidate if current else line)
        current_bytes += candidate_bytes
    if current:
        pages.append("".join(current).strip())
    return [page for page in pages if page.strip()]


def _split_long_text_line(text: str, *, max_page_bytes: int) -> list[str]:
    chunks: list[str] = []
    remaining = text.strip()
    while remaining:
        end = min(len(remaining), max_page_bytes)
        while end > 1 and len(remaining[:end].encode("utf-8")) > max_page_bytes:
            end -= 1
        if end <= 1:
            end = 1
        chunk = remaining[:end].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[end:].strip()
    return chunks


def _pdf_metadata_fallback(source_path: Path, detail: str | None = None) -> str:
    note = "PDF stored in vault metadata. No readable text was found, including after local OCR."
    if detail:
        note = f"{note} OCR detail: {detail}"
    stat = source_path.stat()
    return "\n".join(
        [
            note,
            f"File name: {source_path.name}",
            f"File type: {source_path.suffix.lower() or 'unknown'}",
            f"Size bytes: {stat.st_size}",
        ]
    )


def parse_opendataloader_outputs(output_dir: str | Path, *, source_name: str) -> dict:
    root = Path(output_dir)
    markdown_path = _largest_matching_file(root, "*.md")
    json_path = _largest_matching_file(root, "*.json")
    markdown_text = markdown_path.read_text(encoding="utf-8") if markdown_path is not None else ""
    pages = _split_text_pages(markdown_text)
    structured_tables: list[dict] = []
    bounding_boxes: list[dict] = []
    source_page_count = 0
    if json_path is not None:
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        structured_tables, bounding_boxes, source_page_count = _structured_pdf_artifacts(payload)
    parser = {
        "backend": "opendataloader_pdf",
        "mode": "markdown_json",
        "page_count": len(pages),
        "source_page_count": source_page_count or len(pages),
        "canonical_markdown": markdown_text.strip(),
        "structured_tables": structured_tables,
        "bounding_boxes": bounding_boxes,
        "issues": [],
    }
    return {
        "title": source_name,
        "pages": pages or [f"PDF parsed by OpenDataLoader but no readable markdown was returned for {source_name}."],
        "parser": parser,
    }


def _structured_pdf_artifacts(payload: object) -> tuple[list[dict], list[dict], int]:
    elements = _flatten_elements(payload)
    tables = []
    boxes = []
    page_numbers: set[int] = set()
    for element in elements:
        if not isinstance(element, dict):
            continue
        page_number = _int_or_zero(element.get("page_number") or element.get("page") or element.get("pageIndex"))
        if page_number > 0:
            page_numbers.add(page_number)
        bbox = element.get("bbox") or element.get("bounding_box") or element.get("bounds")
        if isinstance(bbox, dict):
            boxes.append(
                {
                    "page_number": page_number,
                    "type": str(element.get("type") or element.get("kind") or "element"),
                    "bbox": bbox,
                }
            )
        element_type = str(element.get("type") or element.get("kind") or "").lower()
        if "table" in element_type:
            tables.append(
                {
                    "page_number": page_number,
                    "type": element_type or "table",
                    "text": str(element.get("text") or element.get("markdown") or "").strip(),
                }
            )
    return tables[:200], boxes[:500], max(page_numbers, default=0)


def _flatten_elements(payload: object) -> list[object]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("elements", "pages", "items", "content"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                nested = value.get("elements")
                if isinstance(nested, list):
                    return nested
    return []


def _largest_matching_file(root: Path, pattern: str) -> Path | None:
    matches = [path for path in root.rglob(pattern) if path.is_file()]
    if not matches:
        return None
    matches.sort(key=lambda path: path.stat().st_size, reverse=True)
    return matches[0]


def _int_or_zero(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
