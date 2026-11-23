from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://dockintel:dockintel@localhost:5432/dockintel"
    redis_url: str = "redis://localhost:6379/0"
    storage_dir: str = "storage"
    max_upload_bytes: int = 20 * 1024 * 1024
    celery_eager: bool = False
    app_name: str = "DockIntel API"
    app_version: str = "0.1.0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
