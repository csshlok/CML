from __future__ import annotations

from backend.app.core.project_graph import _projection_seed_score


def test_exact_source_symbol_outranks_test_and_prefix_matches() -> None:
    terms = ["authorize", "request"]
    source = {
        "label": "authorize",
        "qualified_id": "auth:authorize",
        "relative_path": "backend/app/auth.py",
        "signature": "authorize(request)",
        "kind": "function",
        "file_role": "source",
    }
    test = {
        "label": "authorize_request_fixture",
        "qualified_id": "tests:authorize_request_fixture",
        "relative_path": "backend/tests/fixtures/auth.py",
        "signature": "authorize_request_fixture()",
        "kind": "function",
        "file_role": "fixture",
    }

    assert _projection_seed_score(source, terms) > _projection_seed_score(test, terms)


def test_query_term_coverage_beats_a_single_generic_match() -> None:
    terms = ["project", "graph", "context"]
    broad = {
        "label": "projectGraphContext",
        "qualified_id": "core:projectGraphContext",
        "relative_path": "backend/app/core/project_graph.py",
        "signature": "projectGraphContext(query)",
        "kind": "function",
        "file_role": "source",
    }
    narrow = {
        "label": "project",
        "qualified_id": "models:project",
        "relative_path": "backend/app/models.py",
        "signature": "Project()",
        "kind": "class",
        "file_role": "source",
    }

    assert _projection_seed_score(broad, terms) > _projection_seed_score(narrow, terms)
