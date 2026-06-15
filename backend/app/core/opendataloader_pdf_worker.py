from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from backend.app.core.pdf_pipeline import parse_opendataloader_outputs


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) != 1:
        _write_error("usage: opendataloader_pdf_worker <path>")
        return 2
    source_path = Path(args[0]).expanduser()
    if not source_path.exists():
        _write_error("PDF file does not exist.")
        return 2
    try:
        import opendataloader_pdf
    except ImportError as exc:
        _write_error(f"OpenDataLoader PDF is not installed: {exc}")
        return 1
    try:
        with tempfile.TemporaryDirectory(prefix="cml-opendataloader-pdf-") as temp_dir:
            opendataloader_pdf.convert(
                input_path=[str(source_path)],
                output_dir=temp_dir,
                format="markdown,json",
            )
            payload = parse_opendataloader_outputs(temp_dir, source_name=source_path.name)
    except Exception as exc:
        _write_error(str(exc))
        return 1
    _write_stdout(payload)
    return 0


def _write_stdout(payload: dict) -> None:
    target = getattr(sys.stdout, "buffer", sys.stdout)
    target.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
    if hasattr(target, "flush"):
        target.flush()


def _write_error(message: str) -> None:
    target = getattr(sys.stderr, "buffer", sys.stderr)
    target.write((str(message).strip() + "\n").encode("utf-8"))
    if hasattr(target, "flush"):
        target.flush()


if __name__ == "__main__":
    raise SystemExit(main())
