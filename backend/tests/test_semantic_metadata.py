import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.app.core.llm_runtime import LLMResult, LLMRuntimeError
from backend.app.core.semantic_metadata import (
    SemanticModelUnavailable,
    clean_extracted_text,
    enrich_cluster_metadata,
    enrich_source_metadata,
    fallback_source_summary,
    representative_preview,
    representative_source_excerpt,
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

    def test_source_excerpt_is_bounded_and_samples_the_whole_document(self) -> None:
        text = "HEAD_MARKER " + ("alpha " * 500) + "MIDDLE_MARKER " + ("omega " * 500) + "TAIL_MARKER"

        excerpt = representative_source_excerpt(text, max_chars=360)

        self.assertLessEqual(len(excerpt), 360)
        self.assertIn("HEAD_MARKER", excerpt)
        self.assertIn("MIDDLE_MARKER", excerpt)
        self.assertIn("TAIL_MARKER", excerpt)
        self.assertEqual(excerpt.count("\n...\n"), 2)

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

    def test_source_enrichment_prompt_uses_the_configured_representative_budget(self) -> None:
        text = "HEAD_MARKER " + ("alpha " * 500) + "MIDDLE_MARKER " + ("omega " * 500) + "TAIL_MARKER"
        response = LLMResult(
            text=json.dumps({"summary": "A representative summary.", "keywords": ["sample"]}),
            provider="local",
            model="test",
        )
        with (
            patch(
                "backend.app.core.semantic_metadata.get_settings",
                return_value=SimpleNamespace(
                    atomic_semantic_max_source_chars=1_000,
                    llm_context_token_budget=1_200,
                ),
            ),
            patch(
                "backend.app.core.semantic_metadata.generate_local_structured_json",
                return_value=response,
            ) as generate,
        ):
            enrich_source_metadata(title="large.txt", source_type="file", text=text)

        prompt = generate.call_args.kwargs["user_prompt"]
        excerpt = prompt.split("Representative document excerpts:\n", 1)[1].split(
            "\n\nReturn a concise summary",
            1,
        )[0]
        self.assertLessEqual(len(excerpt), 1_000)
        self.assertIn("HEAD_MARKER", excerpt)
        self.assertIn("MIDDLE_MARKER", excerpt)
        self.assertIn("TAIL_MARKER", excerpt)

    def test_source_enrichment_retries_context_rejection_with_a_smaller_excerpt(self) -> None:
        text = "HEAD " + ("large document content " * 300) + " TAIL"
        response = LLMResult(
            text=json.dumps({"summary": "A bounded summary.", "keywords": ["bounded"]}),
            provider="local",
            model="test",
        )
        with (
            patch(
                "backend.app.core.semantic_metadata.get_settings",
                return_value=SimpleNamespace(
                    atomic_semantic_max_source_chars=1_000,
                    llm_context_token_budget=1_200,
                ),
            ),
            patch(
                "backend.app.core.semantic_metadata.generate_local_structured_json",
                side_effect=[
                    LLMRuntimeError("request exceeds the available context size"),
                    response,
                ],
            ) as generate,
        ):
            result = enrich_source_metadata(title="large.txt", source_type="file", text=text)

        self.assertEqual(result["summary"], "A bounded summary.")
        self.assertEqual(generate.call_count, 2)
        first_prompt = generate.call_args_list[0].kwargs["user_prompt"]
        second_prompt = generate.call_args_list[1].kwargs["user_prompt"]
        self.assertLess(len(second_prompt), len(first_prompt))

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
