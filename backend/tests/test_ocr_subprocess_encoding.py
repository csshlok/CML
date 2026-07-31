import sys
import tempfile
import unittest
from pathlib import Path

from backend.app.core.ocr import _run_tesseract


class OCRSubprocessEncodingTests(unittest.TestCase):
    def test_tesseract_output_with_non_utf8_bytes_does_not_crash_reader_thread(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            script = Path(temp_dir) / "emit_invalid_utf8.py"
            script.write_text(
                "import sys\nsys.stdout.buffer.write(b'readable \\x9d text')\n",
                encoding="utf-8",
            )

            output = _run_tesseract(Path(sys.executable), script)

        self.assertEqual(output, "readable \ufffd text")


if __name__ == "__main__":
    unittest.main()
