from __future__ import annotations

import json
from pathlib import Path

from scripts.backend.benchmark_claim_consolidation import evaluate_cases


def test_claim_consolidation_provenance_fixture_passes() -> None:
    fixture = Path(__file__).parent / "fixtures" / "claim_consolidation_cases.json"
    report = evaluate_cases(json.loads(fixture.read_text(encoding="utf-8")))

    assert report["case_pass_rate"] == 1.0
    assert report["claim_precision"] == 1.0
    assert report["claim_recall"] == 1.0
    assert report["citation_validity_rate"] == 1.0
    assert report["expected_source_retention_rate"] == 1.0
    assert report["paid_api_calls"] == 0
