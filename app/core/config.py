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

    # Expert Agent LLM planning. The planner chooses among tools assigned in AgentSpec.tool_specs.
    agent_llm_planner_enabled: bool = Field(default=True, alias="AGENT_LLM_PLANNER_ENABLED")
    agent_llm_planner_timeout_seconds: float = Field(default=3.0, alias="AGENT_LLM_PLANNER_TIMEOUT_SECONDS")

    # External data source secrets
    dart_api_key: str | None = Field(default=None, alias="DART_API_KEY")

    # External public web discovery. Disabled by default; use only with an explicit provider/API key.
    external_web_discovery_enabled: bool = Field(default=False, alias="EXTERNAL_WEB_DISCOVERY_ENABLED")
    external_web_search_provider: str = Field(default="brave", alias="EXTERNAL_WEB_SEARCH_PROVIDER")
    brave_search_api_key: str | None = Field(default=None, alias="BRAVE_SEARCH_API_KEY")
    serpapi_api_key: str | None = Field(default=None, alias="SERPAPI_API_KEY")
    external_web_max_results: int = Field(default=3, alias="EXTERNAL_WEB_MAX_RESULTS")

    # Replan loop guard. 0 disables replan and routes evidence gaps directly to Human Review.
    agent_replan_max_attempts: int = Field(default=1, alias="AGENT_REPLAN_MAX_ATTEMPTS")

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

    # Agent tool isolation. direct=normal Python call, docker=run declared command tools in a restricted Docker container.
    agent_tool_sandbox_mode: str = Field(default="direct", alias="AGENT_TOOL_SANDBOX_MODE")
    agent_tool_sandbox_image: str = Field(default="python:3.12-slim", alias="AGENT_TOOL_SANDBOX_IMAGE")
    agent_tool_sandbox_timeout_seconds: int = Field(default=30, alias="AGENT_TOOL_SANDBOX_TIMEOUT_SECONDS")
    agent_tool_sandbox_network: str = Field(default="none", alias="AGENT_TOOL_SANDBOX_NETWORK")

    # Graph node isolation. direct is default; subprocess isolates each node into a Python worker process.
    graph_node_execution_mode: str = Field(default="direct", alias="GRAPH_NODE_EXECUTION_MODE")
    graph_node_worker_timeout_seconds: int = Field(default=300, alias="GRAPH_NODE_WORKER_TIMEOUT_SECONDS")
    graph_node_worker_image: str = Field(default="ax-delivery-planner:latest", alias="GRAPH_NODE_WORKER_IMAGE")

    # Monitoring
    prometheus_scrape_interval: str = Field(default="15s", alias="PROMETHEUS_SCRAPE_INTERVAL")
    grafana_admin_user: str = Field(default="admin", alias="GRAFANA_ADMIN_USER")
    grafana_admin_password: str = Field(default="admin", alias="GRAFANA_ADMIN_PASSWORD")

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
