import json
import sys

from backend.app.core.extraction import extract_pages_from_validated_path


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
        title, pages = extract_pages_from_validated_path(args[0])
    except Exception as exc:
        _write_text(sys.stderr, str(exc)[:500])
        return 1
    _write_text(sys.stdout, json.dumps({"title": title, "pages": pages}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
