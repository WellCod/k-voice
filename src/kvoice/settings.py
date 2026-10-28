from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://kvoice:kvoice@localhost:5432/kvoice"

    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key_id: str = "minioadmin"
    s3_secret_access_key: str = "minioadmin"
    s3_bucket_outputs: str = "kvoice-outputs"
    s3_bucket_references: str = "kvoice-references"

    elevenlabs_api_key: str = ""
    secret_key: str = "troque-em-producao"
    log_level: str = "INFO"

    qwen3_enabled: bool = False
    qwen3_model_id: str = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
    qwen3_base_model_id: str = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
    qwen3_speaker: str = "vivian"

    @property
    def sync_database_url(self) -> str:
        url = self.database_url.replace("+asyncpg", "+psycopg2")
        # strip asyncpg-specific query params unsupported by psycopg2
        if "?" in url:
            url = url.split("?")[0]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
