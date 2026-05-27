from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    data_dir: Path = Path("data")
    database_path: Path = Path("data/cml.sqlite3")
    api_prefix: str = "/api/v1"

    model_config = SettingsConfigDict(env_prefix="CML_", env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
