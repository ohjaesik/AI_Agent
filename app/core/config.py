# app/core/config.py

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # PostgreSQL
    database_url: str = Field(alias="DATABASE_URL")

    postgres_host: str | None = Field(default=None, alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_db: str | None = Field(default=None, alias="POSTGRES_DB")
    postgres_user: str | None = Field(default=None, alias="POSTGRES_USER")
    postgres_password: str | None = Field(default=None, alias="POSTGRES_PASSWORD")

    # OpenAI Embedding
    openai_api_key: str = Field(alias="OPENAI_API_KEY")
    embedding_model: str = Field(default="text-embedding-3-small", alias="EMBEDDING_MODEL")
    embedding_dim: int = Field(default=1536, alias="EMBEDDING_DIM")

    # vLLM OpenAI-compatible endpoint
    vllm_base_url: str = Field(default="http://localhost:8000/v1", alias="VLLM_BASE_URL")
    vllm_api_key: str = Field(default="EMPTY", alias="VLLM_API_KEY")
    vllm_model: str = Field(default="google/gemma-2-9b-it", alias="VLLM_MODEL")

    # External data source secrets
    dart_api_key: str | None = Field(default=None, alias="DART_API_KEY")

    # API protection. If unset, local/test mode remains open.
    app_api_key: str | None = Field(default=None, alias="APP_API_KEY")

    # App
    app_env: str = Field(default="local", alias="APP_ENV")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
