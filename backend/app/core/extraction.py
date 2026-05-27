from pathlib import Path


SUPPORTED_TEXT_EXTENSIONS = {".md", ".markdown", ".txt"}


class ExtractionError(Exception):
    pass


def extract_text_from_path(path: str) -> tuple[str, str]:
    source_path = Path(path).expanduser()
    if not source_path.exists() or not source_path.is_file():
        raise ExtractionError("File does not exist or is not readable")

    suffix = source_path.suffix.lower()
    if suffix not in SUPPORTED_TEXT_EXTENSIONS:
        raise ExtractionError("Only TXT and Markdown files are supported in this ingestion slice")

    try:
        text = source_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = source_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ExtractionError(str(exc)) from exc

    return source_path.name, text
