import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class PdfPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        os.environ["CML_DATA_DIR"] = self.tmp.name
        os.environ["CML_DATABASE_PATH"] = str(Path(self.tmp.name) / "test.sqlite3")
        from backend.app.core.config import get_settings
        from backend.app.core.database import init_db

        get_settings.cache_clear()
        init_db()

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        for key in ("CML_DATA_DIR", "CML_DATABASE_PATH", "CML_PDF_PARSER_BACKEND"):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def test_builtin_pdf_document_falls_back_to_metadata_when_ocr_unavailable(self) -> None:
        from backend.app.core.ocr import OCRError
        from backend.app.core.pdf_pipeline import extract_pdf_document_with_backend

        target = Path(self.tmp.name) / "scan.pdf"
        target.write_bytes(b"%PDF-1.4\n%mock\n")

        class _EmptyReader:
            def __init__(self, *_args, **_kwargs) -> None:
                self.pages = [type("_Page", (), {"extract_text": lambda self: ""})()]

        with (
            patch("pypdf.PdfReader", _EmptyReader),
            patch("backend.app.core.pdf_pipeline.ocr_pdf_pages", side_effect=OCRError("ocr unavailable")),
        ):
            document = extract_pdf_document_with_backend(target, "builtin")

        self.assertEqual(document["title"], "scan.pdf")
        self.assertEqual(document["parser"]["backend"], "builtin")
        self.assertEqual(document["parser"]["mode"], "metadata_fallback")
        self.assertIn("ocr unavailable", document["pages"][0])

    def test_parse_opendataloader_outputs_extracts_tables_and_boxes(self) -> None:
        from backend.app.core.pdf_pipeline import parse_opendataloader_outputs

        output_dir = Path(self.tmp.name) / "odl"
        output_dir.mkdir()
        (output_dir / "doc.md").write_text("# Report\n\nQuarterly results table", encoding="utf-8")
        (output_dir / "doc.json").write_text(
            """
            {
              "elements": [
                {"type": "table", "page_number": 2, "text": "Revenue | Profit", "bbox": {"x": 1, "y": 2}},
                {"type": "paragraph", "page_number": 1, "text": "Intro", "bbox": {"x": 3, "y": 4}}
              ]
            }
            """,
            encoding="utf-8",
        )

        document = parse_opendataloader_outputs(output_dir, source_name="doc.pdf")

        self.assertEqual(document["parser"]["backend"], "opendataloader_pdf")
        self.assertEqual(document["parser"]["source_page_count"], 2)
        self.assertEqual(len(document["parser"]["structured_tables"]), 1)
        self.assertEqual(len(document["parser"]["bounding_boxes"]), 2)
        self.assertTrue(document["pages"])

    def test_validate_worker_output_preserves_parser_metadata(self) -> None:
        from backend.app.core.quarantine import validate_worker_output

        payload = validate_worker_output(
            {
                "title": "doc.pdf",
                "pages": ["alpha", "beta"],
                "parser": {"backend": "opendataloader_pdf", "mode": "markdown_json"},
            }
        )

        self.assertEqual(payload["parser"]["backend"], "opendataloader_pdf")
        self.assertEqual(payload["pages"], ["alpha", "beta"])

    def test_opendataloader_stdout_with_logs_still_parses_json_payload(self) -> None:
        from backend.app.core.pdf_pipeline import _parse_json_payload

        payload = _parse_json_payload(
            """
            Jun 15, 2026 11:43:47 AM org.opendataloader.pdf.processors.DocumentProcessor preprocessing
            INFO: File name: report.pdf
            {"title":"report.pdf","pages":["alpha"],"parser":{"backend":"opendataloader_pdf","mode":"markdown_json"}}
            """
        )

        self.assertEqual(payload["title"], "report.pdf")
        self.assertEqual(payload["parser"]["mode"], "markdown_json")

    def test_pdf_parser_metadata_is_persisted_into_source_security_json(self) -> None:
        from backend.app.api.routes.sources import create_source_from_path
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourcePathCreate

        target = Path(self.tmp.name) / "doc.pdf"
        target.write_bytes(b"%PDF-1.4\n")
        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )

        with patch(
            "backend.app.core.quarantine.run_parser_worker",
            return_value={
                "title": "doc.pdf",
                "pages": ["alpha"],
                "parser": {"backend": "opendataloader_pdf", "mode": "markdown_json"},
            },
        ):
            source = create_source_from_path(SourcePathCreate(vault_id="vault-1", path=str(target)))

        self.assertIn("opendataloader_pdf", source["parser_security_json"])


if __name__ == "__main__":
    unittest.main()
