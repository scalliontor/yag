from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_base_url: str = "http://localhost:8000"
    database_url: str = "data/yag.sqlite"

    google_client_secret_file: Optional[str] = None
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None

    openai_base_url: str = "https://platform.xiaomimimo.com/v1"
    openai_api_key: str = ""
    llm_model: str = "gemma-4"

    scheduler_enabled: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def db_path(self) -> Path:
        return Path(self.database_url.replace("sqlite:///", ""))

    @property
    def google_redirect_uri(self) -> str:
        return f"{self.app_base_url.rstrip('/')}/oauth/google/callback"


@lru_cache
def get_settings() -> Settings:
    return Settings()
