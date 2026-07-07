from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.core.model_registry import MODEL_REGISTRY


@dataclass(frozen=True)
class CatalogBenchmark:
    score: float | None
    source: str
    confidence: float
    updated_at: str


@dataclass(frozen=True)
class CatalogModelSpec:
    id: str
    name: str
    repo: str
    family: str
    family_line: str
    architecture: str
    context_length: int
    parameter_count_total_b: float
    parameter_count_active_b: float | None
    runtime_format: str
    quantization: str
    download_bytes: int
    estimated_weight_bytes: int
    benchmark: CatalogBenchmark
    minimum_chat_tier: str
    windows_supported: bool
    llama_cpp_supported: bool
    benchmark_keys: tuple[str, ...]
    release_date: str
    source_kind: str


_CATALOG_SPECS: dict[str, CatalogModelSpec] = {
    "qwen3-4b-q4_k_m": CatalogModelSpec(
        id="qwen3-4b-q4_k_m",
        name="Qwen3 4B Q4_K_M",
        repo="Qwen/Qwen3-4B-GGUF",
        family="qwen",
        family_line="qwen3",
        architecture="qwen3",
        context_length=32768,
        parameter_count_total_b=4.0,
        parameter_count_active_b=None,
        runtime_format="gguf",
        quantization="Q4_K_M",
        download_bytes=int(2.5 * 1024**3),
        estimated_weight_bytes=int(2.5 * 1024**3),
        benchmark=CatalogBenchmark(score=73.0, source="direct", confidence=0.88, updated_at="2026-06-20"),
        minimum_chat_tier="cpu_minimum_spec",
        windows_supported=True,
        llama_cpp_supported=True,
        benchmark_keys=("qwen3-4b", "qwen3-4b-q4_k_m"),
        release_date="2025-01-01",
        source_kind="default_choice",
    ),
    "phi-4-mini-instruct-q4_k_m": CatalogModelSpec(
        id="phi-4-mini-instruct-q4_k_m",
        name="Phi-4 Mini Instruct Q4_K_M",
        repo="unsloth/Phi-4-mini-instruct-GGUF",
        family="phi",
        family_line="phi-4",
        architecture="phi4",
        context_length=16384,
        parameter_count_total_b=4.0,
        parameter_count_active_b=None,
        runtime_format="gguf",
        quantization="Q4_K_M",
        download_bytes=int(2.5 * 1024**3),
        estimated_weight_bytes=int(2.5 * 1024**3),
        benchmark=CatalogBenchmark(score=68.0, source="direct", confidence=0.84, updated_at="2026-06-20"),
        minimum_chat_tier="cpu_minimum_spec",
        windows_supported=True,
        llama_cpp_supported=True,
        benchmark_keys=("phi-4-mini", "phi-4-mini-instruct"),
        release_date="2025-01-01",
        source_kind="default_choice",
    ),
    "qwen3-8b-q4_k_m": CatalogModelSpec(
        id="qwen3-8b-q4_k_m",
        name="Qwen3 8B Q4_K_M",
        repo="Qwen/Qwen3-8B-GGUF",
        family="qwen",
        family_line="qwen3",
        architecture="qwen3",
        context_length=32768,
        parameter_count_total_b=8.0,
        parameter_count_active_b=None,
        runtime_format="gguf",
        quantization="Q4_K_M",
        download_bytes=int(4.8 * 1024**3),
        estimated_weight_bytes=int(4.8 * 1024**3),
        benchmark=CatalogBenchmark(score=80.0, source="direct", confidence=0.9, updated_at="2026-06-20"),
        minimum_chat_tier="cpu_high_spec",
        windows_supported=True,
        llama_cpp_supported=True,
        benchmark_keys=("qwen3-8b", "qwen3-8b-q4_k_m"),
        release_date="2025-01-01",
        source_kind="default_choice",
    ),
    "gemma-3-4b-it-q4_k_m": CatalogModelSpec(
        id="gemma-3-4b-it-q4_k_m",
        name="Gemma 3 4B IT Q4_K_M",
        repo="Aldaris/gemma-3-4b-it-Q4_K_M-GGUF",
        family="gemma",
        family_line="gemma3",
        architecture="gemma3",
        context_length=32768,
        parameter_count_total_b=4.0,
        parameter_count_active_b=None,
        runtime_format="gguf",
        quantization="Q4_K_M",
        download_bytes=int(2.5 * 1024**3),
        estimated_weight_bytes=int(2.5 * 1024**3),
        benchmark=CatalogBenchmark(score=70.0, source="direct", confidence=0.84, updated_at="2026-06-20"),
        minimum_chat_tier="cpu_minimum_spec",
        windows_supported=True,
        llama_cpp_supported=True,
        benchmark_keys=("gemma-3-4b", "gemma3-4b"),
        release_date="2025-01-01",
        source_kind="default_choice",
    ),
    "gemma-3-12b-it-q4_k_m": CatalogModelSpec(
        id="gemma-3-12b-it-q4_k_m",
        name="Gemma 3 12B IT Q4_K_M",
        repo="nocturne23/gemma-3-12b-it-Q4_K_M-GGUF",
        family="gemma",
        family_line="gemma3",
        architecture="gemma3",
        context_length=32768,
        parameter_count_total_b=12.0,
        parameter_count_active_b=None,
        runtime_format="gguf",
        quantization="Q4_K_M",
        download_bytes=int(6.9 * 1024**3),
        estimated_weight_bytes=int(6.9 * 1024**3),
        benchmark=CatalogBenchmark(score=83.0, source="direct", confidence=0.88, updated_at="2026-06-20"),
        minimum_chat_tier="gpu_or_high_spec_candidate",
        windows_supported=True,
        llama_cpp_supported=True,
        benchmark_keys=("gemma-3-12b", "gemma3-12b"),
        release_date="2025-01-01",
        source_kind="default_choice",
    ),
}

_HARDWARE_TIER_RANK = {
    "unsupported": 0,
    "unknown": 0,
    "cpu_minimum_spec": 1,
    "cpu_high_spec": 2,
    "gpu_or_high_spec_candidate": 3,
}


def catalog_specs() -> dict[str, CatalogModelSpec]:
    return dict(_CATALOG_SPECS)

def tier_rank(tier: str) -> int:
    return _HARDWARE_TIER_RANK.get(str(tier or "unknown"), 0)


def minimum_tier_satisfied(actual_tier: str, minimum_tier: str) -> bool:
    return tier_rank(actual_tier) >= tier_rank(minimum_tier)


def default_catalog_models() -> list[dict[str, Any]]:
    registry_rows = {model.id: model for model in MODEL_REGISTRY}
    rows: list[dict[str, Any]] = []
    for model_id, spec in _CATALOG_SPECS.items():
        registry_row = registry_rows.get(model_id)
        if registry_row is None:
            continue
        rows.append(
            {
                "id": model_id,
                "name": spec.name or registry_row.name,
                "repo": spec.repo,
                "family": spec.family,
                "family_line": spec.family_line,
                "architecture": spec.architecture,
                "context_length": spec.context_length,
                "parameter_count_total_b": spec.parameter_count_total_b,
                "parameter_count_active_b": spec.parameter_count_active_b,
                "runtime_format": spec.runtime_format,
                "quantization": spec.quantization,
                "download_bytes": spec.download_bytes,
                "estimated_weight_bytes": spec.estimated_weight_bytes,
                "minimum_chat_tier": spec.minimum_chat_tier,
                "benchmark_keys": list(spec.benchmark_keys),
                "release_date": spec.release_date,
                "source_kind": spec.source_kind,
            }
        )
    return rows
