from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


SUPPORTED_TEXT_EXTENSIONS = {".md", ".markdown", ".txt"}
SUPPORTED_DOCUMENT_EXTENSIONS = SUPPORTED_TEXT_EXTENSIONS | {".docx", ".pdf"}


class ExtractionError(Exception):
    pass


def extract_text_from_path(path: str) -> tuple[str, str]:
    source_path = Path(path).expanduser()
    if not source_path.exists() or not source_path.is_file():
        raise ExtractionError("File does not exist or is not readable")

    suffix = source_path.suffix.lower()
    if suffix in SUPPORTED_TEXT_EXTENSIONS:
        return source_path.name, _extract_plain_text(source_path)
    if suffix == ".docx":
        return source_path.name, _extract_docx_text(source_path)
    if suffix == ".pdf":
        return source_path.name, _extract_pdf_text(source_path)

    raise ExtractionError("Supported file types are TXT, Markdown, DOCX, and PDF")


def _extract_plain_text(source_path: Path) -> str:
    try:
        return source_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return source_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ExtractionError(str(exc)) from exc


def _extract_docx_text(source_path: Path) -> str:
    try:
        from docx import Document
    except ImportError as exc:
        raise ExtractionError("DOCX extraction requires python-docx to be installed") from exc

    try:
        document = Document(str(source_path))
    except Exception as exc:
        raise ExtractionError(f"Could not read DOCX file: {exc}") from exc

    paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                paragraphs.append(" | ".join(cells))

    text = "\n".join(paragraphs).strip()
    if not text:
        raise ExtractionError("No readable text was found in this DOCX file")
    return text


def _extract_pdf_text(source_path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ExtractionError("PDF extraction requires pypdf to be installed") from exc

    try:
        reader = PdfReader(str(source_path))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise ExtractionError(f"Could not read PDF file: {exc}") from exc

    text = "\n\n".join(page.strip() for page in pages if page.strip()).strip()
    if not text:
        raise ExtractionError("No readable text was found in this PDF file")
    return text


class _TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self.page_title = ""
        self.meta_title = ""
        self.cover_image_url = ""
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_by_name = {name.lower(): value or "" for name, value in attrs}
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            key = attrs_by_name.get("property") or attrs_by_name.get("name")
            content = attrs_by_name.get("content", "").strip()
            if key in {"og:title", "twitter:title"} and content and not self.meta_title:
                self.meta_title = content
            if key in {"og:image", "twitter:image"} and content and not self.cover_image_url:
                self.cover_image_url = content
        if tag in {"p", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in {"p", "li", "div", "section", "article"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            title = " ".join(data.split())
            if title and not self.page_title:
                self.page_title = title
        if self._skip_depth == 0:
            cleaned = " ".join(data.split())
            if cleaned:
                self._parts.append(cleaned)

    def text(self) -> str:
        return "\n".join(part for part in self._parts if part.strip()).strip()


def extract_text_from_url(url: str) -> tuple[str, str, str | None]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ExtractionError("Only HTTP and HTTPS links are supported")

    request = Request(
        url,
        headers={
            "User-Agent": "CML/0.1 local context ingestion",
            "Accept": "text/html,text/plain;q=0.9,*/*;q=0.8",
        },
    )

    try:
        with urlopen(request, timeout=12) as response:
            content_type = response.headers.get("content-type", "")
            body = response.read(2_000_000)
    except OSError as exc:
        raise ExtractionError(str(exc)) from exc

    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError:
        decoded = body.decode("utf-8", errors="replace")

    if "html" in content_type:
        parser = _TextHTMLParser()
        parser.feed(decoded)
        text = parser.text()
        title = parser.meta_title or parser.page_title
        cover_image_url = urljoin(url, parser.cover_image_url) if parser.cover_image_url else None
    else:
        text = decoded.strip()
        title = ""
        cover_image_url = None

    if not text:
        raise ExtractionError("No readable text was found at this link")

    fallback_title = (parsed.netloc + parsed.path).rstrip("/") or url
    return title or fallback_title, text, cover_image_url
