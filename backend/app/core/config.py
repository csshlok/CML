from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    data_dir: Path = Path("data")
    database_path: Path = Path("data/cml.sqlite3")
    models_dir: Path | None = None
    api_prefix: str = "/api/v1"
    llm_provider: str = "none"
    llm_base_url: str = "http://127.0.0.1:8080/v1"
    llm_model: str = "Qwen/Qwen3-4B-GGUF:Q4_K_M"
    llm_timeout_seconds: float = 45.0

    model_config = SettingsConfigDict(env_prefix="CML_", env_file=ROOT_DIR / ".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
