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

    # API protection. If APP_JWT_SECRET is set, Bearer JWT is supported.
    app_api_key: str | None = Field(default=None, alias="APP_API_KEY")
    app_jwt_secret: str | None = Field(default=None, alias="APP_JWT_SECRET")
    app_jwt_algorithm: str = Field(default="HS256", alias="APP_JWT_ALGORITHM")
    app_jwt_exp_minutes: int = Field(default=480, alias="APP_JWT_EXP_MINUTES")

    # Original document storage. Use local for development, s3 for MinIO/S3.
    storage_backend: str = Field(default="local", alias="STORAGE_BACKEND")
    local_storage_dir: str = Field(default="storage", alias="LOCAL_STORAGE_DIR")
    s3_endpoint_url: str | None = Field(default=None, alias="S3_ENDPOINT_URL")
    s3_bucket: str | None = Field(default=None, alias="S3_BUCKET")
    s3_access_key_id: str | None = Field(default=None, alias="S3_ACCESS_KEY_ID")
    s3_secret_access_key: str | None = Field(default=None, alias="S3_SECRET_ACCESS_KEY")
    s3_region_name: str = Field(default="ap-northeast-2", alias="S3_REGION_NAME")

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
