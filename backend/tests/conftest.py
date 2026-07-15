from __future__ import annotations

from pathlib import Path

import pytest


INTEGRATION_FILES = {
    "test_additional_qa_cases.py",
    "test_bridge_phase10.py",
    "test_lora_to_rag_phase12.py",
    "test_source_pages.py",
}

SYSTEM_FILES = {
    "test_encrypted_storage_phase3.py",
    "test_migration_planner_phase5.py",
    "test_quarantine_phase6.py",
    "test_reconciliation_phase12.py",
    "test_security_phase14.py",
    "test_system_vault_lock_and_embeddings.py",
    "test_unlock_phase2.py",
    "test_vault_crypto_phase1.py",
}

BENCHMARK_FILES = {
    "test_benchmark_corpus.py",
    "test_benchmark_graphs.py",
    "test_benchmark_matrix.py",
    "test_turbovec_benchmark.py",
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Assign stable suite tiers without duplicating decorators across test modules."""

    for item in items:
        filename = Path(str(item.fspath)).name
        if filename == "test_odin_scale.py":
            item.add_marker(pytest.mark.scale)
        elif filename in BENCHMARK_FILES:
            item.add_marker(pytest.mark.benchmark)
        elif filename in SYSTEM_FILES:
            item.add_marker(pytest.mark.system)
        elif filename in INTEGRATION_FILES:
            item.add_marker(pytest.mark.integration)
