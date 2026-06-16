from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    data_dir: Path = Path("data")
    database_path: Path = Path("data/cml.sqlite3")
    backend_mode: str = "full_vault"
    startup_status_path: Path | None = None
    models_dir: Path | None = None
    model_integrity_manifest_path: Path | None = None
    model_integrity_manifest_url: str | None = None
    api_prefix: str = "/api/v1"
    llm_provider: str = "none"
    llm_base_url: str = "http://127.0.0.1:8080/v1"
    llm_model: str = "Qwen/Qwen3-4B-GGUF:Q4_K_M"
    llm_timeout_seconds: float = 45.0
    llm_context_token_budget: int = 1200
    embedding_provider: str = "sentence-transformers"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimensions: int = 384
    embedding_cache_dir: Path | None = None
    allow_hash_embeddings: bool = False
    vector_search_backend: str = "exact"
    turbovec_bit_width: int = 4
    turbovec_min_chunk_count: int = 10000
    ocr_binary_path: Path | None = None
    ocrmypdf_binary_path: Path | None = None
    pdf_parser_backend: str = "auto"
    pdf_parser_runtime_python: str | None = None
    opendataloader_pdf_command: str | None = None
    pdf_parser_timeout_seconds: int = 180
    api_token: str | None = None
    allow_unauthenticated_api: bool = False
    lora_trainer_command: str | None = None
    lora_min_quality_score: float = 60.0
    lora_min_quality_delta: float = 1.0
    lora_min_sources: int = 1
    lora_min_unique_sources: int = 1
    lora_min_tokens: int = 1200
    lora_min_validation_records: int = 1
    lora_max_duplicate_ratio: float = 0.25
    allow_lora_test_trainer: bool = False
    lora_model_dirs: str = ""
    lora_runtime_python: str | None = None
    lora_runtime_device: str = "auto"
    lora_runtime_dtype: str = "auto"
    lora_runtime_max_new_tokens: int = 48
    lora_runtime_prompt: str = "Reply with the single word CML."
    lora_training_device: str = "auto"
    lora_training_dtype: str = "auto"
    lora_training_cutoff_len: int = 4096
    lora_training_max_steps: int | None = None
    lora_training_batch_size: int = 1
    lora_training_gradient_accumulation_steps: int = 1
    model_scan_roots: str = ""
    model_scan_max_depth: int = 4
    model_scan_cache_seconds: int = 30
    enable_dynamic_web_ingestion: bool = False

    model_config = SettingsConfigDict(env_prefix="CML_", env_file=ROOT_DIR / ".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
