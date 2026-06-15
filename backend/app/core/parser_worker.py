import json
import sys
from pathlib import Path

from backend.app.core.extraction import extract_pages_from_validated_path
from backend.app.core.pdf_pipeline import extract_pdf_document


def _write_text(stream, text: str) -> None:
    payload = text.encode("utf-8", errors="strict")
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(payload)
        buffer.write(b"\n")
        buffer.flush()
        return
    stream.write(payload.decode("utf-8"))
    stream.write("\n")
    stream.flush()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        _write_text(sys.stderr, json.dumps({"error": "usage: parser_worker <path>"}))
        return 2
    try:
        if Path(args[0]).suffix.lower() == ".pdf":
            document = extract_pdf_document(args[0])
            title = str(document.get("title") or Path(args[0]).name)
            pages = document.get("pages") or []
            parser = document.get("parser") or {}
        else:
            title, pages = extract_pages_from_validated_path(args[0])
            parser = {}
    except Exception as exc:
        _write_text(sys.stderr, str(exc)[:500])
        return 1
    _write_text(sys.stdout, json.dumps({"title": title, "pages": pages, "parser": parser}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
