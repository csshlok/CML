import json
import unittest
from unittest.mock import patch

from backend.app.core.llm_runtime import LLMResult, LLMRuntimeError
from backend.app.core.semantic_metadata import (
    SemanticModelUnavailable,
    clean_extracted_text,
    enrich_cluster_metadata,
    enrich_source_metadata,
    fallback_source_summary,
    representative_preview,
)


class SemanticMetadataTests(unittest.TestCase):
    def test_clean_text_and_preview_remove_markup_and_avoid_summary_copy(self) -> None:
        raw = (
            '<body class="main"><script>ignore()</script>'
            "<h1>Course handbook</h1><p>This guide explains the Python course schedule.</p>"
            "<p>Students complete daily coding projects and assessments.</p></body>"
        )
        cleaned = clean_extracted_text(raw)
        preview = representative_preview(
            raw,
            summary="This guide explains the Python course schedule.",
        )
        self.assertNotIn("<body", cleaned)
        self.assertNotIn("ignore()", cleaned)
        self.assertIn("daily coding projects", preview)
        self.assertNotEqual(
            preview,
            "This guide explains the Python course schedule.",
        )

    def test_source_fallback_uses_a_readable_file_name_not_an_ocr_header(self) -> None:
        summary = fallback_source_summary(
            title="student_employment_letter.pdf",
            text=(
                "DATE: February 20, 2025 RE: Last Name: Example First Name: Student "
                "SEVIS ID: N000000000 Dear Representative\n"
                "This letter confirms the student is enrolled and eligible for campus employment."
            ),
        )
        self.assertTrue(summary.startswith("student employment letter:"))
        self.assertIn("confirms the student", summary)

    def test_local_source_enrichment_returns_bounded_semantic_copy(self) -> None:
        response = LLMResult(
            text=json.dumps(
                {
                    "summary": "A course guide covering the schedule, projects, and completion requirements.",
                    "keywords": ["Python", "course schedule", "projects"],
                }
            ),
            provider="local",
            model="test",
        )
        with patch(
            "backend.app.core.semantic_metadata.generate_local_structured_json",
            return_value=response,
        ):
            result = enrich_source_metadata(
                title="syllabus.pdf",
                source_type="file",
                text="A long course syllabus about one hundred days of Python.",
            )
        self.assertIn("course guide", result["summary"])
        self.assertEqual(result["keywords"][0], "Python")

    def test_unavailable_model_pauses_semantic_work_instead_of_saving_fallback_copy(self) -> None:
        with (
            patch(
                "backend.app.core.semantic_metadata.generate_local_structured_json",
                side_effect=LLMRuntimeError("runtime unreachable"),
            ),
            patch(
                "backend.app.core.semantic_metadata.runtime_status",
                return_value={
                    "available": False,
                    "state": "unreachable",
                    "detail": "The selected model stopped.",
                },
            ),
        ):
            with self.assertRaises(SemanticModelUnavailable):
                enrich_source_metadata(
                    title="syllabus.pdf",
                    source_type="file",
                    text="A course syllabus describing lessons and projects.",
                    require_model=True,
                )

    def test_runtime_error_does_not_save_fallback_when_process_still_looks_ready(self) -> None:
        with (
            patch(
                "backend.app.core.semantic_metadata.generate_local_structured_json",
                side_effect=LLMRuntimeError("generation request failed"),
            ),
            patch(
                "backend.app.core.semantic_metadata.runtime_status",
                return_value={"available": True, "state": "ready", "detail": ""},
            ),
        ):
            with self.assertRaises(LLMRuntimeError):
                enrich_source_metadata(
                    title="syllabus.pdf",
                    source_type="file",
                    text="A course syllabus describing lessons and projects.",
                    require_model=True,
                )

    def test_invalid_model_metadata_is_retried_instead_of_marked_complete(self) -> None:
        response = LLMResult(text="not json", provider="local", model="test")
        with patch(
            "backend.app.core.semantic_metadata.generate_local_structured_json",
            return_value=response,
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid source metadata"):
                enrich_source_metadata(
                    title="syllabus.pdf",
                    source_type="file",
                    text="A course syllabus describing lessons and projects.",
                    require_model=True,
                )

    def test_cluster_enrichment_rejects_filename_style_names(self) -> None:
        response = LLMResult(
            text=json.dumps(
                {
                    "name": "50100628627553.pdf",
                    "description": "Bank transaction receipts and account statements.",
                    "summary": "Financial records used to review payments and balances.",
                }
            ),
            provider="local",
            model="test",
        )
        sources = [
            {
                "title": "spring_receipt.pdf",
                "summary": "A tuition payment receipt.",
            },
            {
                "title": "account_statement.pdf",
                "summary": "An account statement with recent balances.",
            },
        ]
        with patch(
            "backend.app.core.semantic_metadata.generate_local_structured_json",
            return_value=response,
        ):
            result = enrich_cluster_metadata(sources)
        self.assertNotEqual(result["name"], "50100628627553.pdf")
        self.assertEqual(
            result["description"],
            "Bank transaction receipts and account statements.",
        )


if __name__ == "__main__":
    unittest.main()
