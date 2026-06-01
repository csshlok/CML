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
    api_prefix: str = "/api/v1"
    llm_provider: str = "none"
    llm_base_url: str = "http://127.0.0.1:8080/v1"
    llm_model: str = "Qwen/Qwen3-4B-GGUF:Q4_K_M"
    llm_timeout_seconds: float = 45.0
    embedding_provider: str = "sentence-transformers"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimensions: int = 384
    embedding_cache_dir: Path | None = None
    allow_hash_embeddings: bool = False
    ocr_binary_path: Path | None = None
    ocrmypdf_binary_path: Path | None = None
    api_token: str | None = None
    lora_trainer_command: str | None = None
    lora_min_quality_score: float = 60.0
    lora_min_sources: int = 1
    allow_lora_test_trainer: bool = False

    model_config = SettingsConfigDict(env_prefix="CML_", env_file=ROOT_DIR / ".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
