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
    vllm_model: str = Field(default="gemma-4-e4b-it", alias="VLLM_MODEL")

    # External LLM provider keys. OPENAI_API_KEY is already used for embeddings;
    # ANTHROPIC_API_KEY is optional and only used when the model router selects Claude.
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")

    # Supervisor-driven model routing. The router keeps vLLM as the default local
    # path, but can select GPT/Claude models when their keys are configured.
    model_router_enabled: bool = Field(default=True, alias="MODEL_ROUTER_ENABLED")
    model_router_enable_vllm: bool = Field(default=True, alias="MODEL_ROUTER_ENABLE_VLLM")
    model_router_enable_openai: bool = Field(default=True, alias="MODEL_ROUTER_ENABLE_OPENAI")
    model_router_enable_anthropic: bool = Field(default=True, alias="MODEL_ROUTER_ENABLE_ANTHROPIC")
    model_router_target_seconds: float = Field(default=45.0, alias="MODEL_ROUTER_TARGET_SECONDS")
    model_router_cost_sensitivity: float = Field(default=0.35, alias="MODEL_ROUTER_COST_SENSITIVITY")

    # The Supervisor Agent is treated as the highest-risk orchestration role, so
    # it is pinned to this upper-tier model whenever the configured provider is available.
    supervisor_model_provider: str = Field(default="openai", alias="SUPERVISOR_MODEL_PROVIDER")
    supervisor_model_name: str = Field(default="gpt-4.1", alias="SUPERVISOR_MODEL_NAME")
    supervisor_llm_enabled: bool = Field(default=True, alias="SUPERVISOR_LLM_ENABLED")
    supervisor_minimal_human_approval: bool = Field(default=True, alias="SUPERVISOR_MINIMAL_HUMAN_APPROVAL")

    # Model candidates used by the cost/performance router. Prices are USD per
    # one million tokens and can be updated without code changes.
    openai_high_model: str = Field(default="gpt-4.1", alias="OPENAI_HIGH_MODEL")
    openai_balanced_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_BALANCED_MODEL")
    openai_fast_model: str = Field(default="gpt-4.1-nano", alias="OPENAI_FAST_MODEL")
    openai_high_input_cost_per_million: float = Field(default=2.00, alias="OPENAI_HIGH_INPUT_COST_PER_MILLION")
    openai_high_output_cost_per_million: float = Field(default=8.00, alias="OPENAI_HIGH_OUTPUT_COST_PER_MILLION")
    openai_balanced_input_cost_per_million: float = Field(default=0.40, alias="OPENAI_BALANCED_INPUT_COST_PER_MILLION")
    openai_balanced_output_cost_per_million: float = Field(default=1.60, alias="OPENAI_BALANCED_OUTPUT_COST_PER_MILLION")
    openai_fast_input_cost_per_million: float = Field(default=0.10, alias="OPENAI_FAST_INPUT_COST_PER_MILLION")
    openai_fast_output_cost_per_million: float = Field(default=0.40, alias="OPENAI_FAST_OUTPUT_COST_PER_MILLION")

    anthropic_high_model: str = Field(default="claude-3-5-sonnet-latest", alias="ANTHROPIC_HIGH_MODEL")
    anthropic_fast_model: str = Field(default="claude-3-5-haiku-latest", alias="ANTHROPIC_FAST_MODEL")
    anthropic_high_input_cost_per_million: float = Field(default=3.00, alias="ANTHROPIC_HIGH_INPUT_COST_PER_MILLION")
    anthropic_high_output_cost_per_million: float = Field(default=15.00, alias="ANTHROPIC_HIGH_OUTPUT_COST_PER_MILLION")
    anthropic_fast_input_cost_per_million: float = Field(default=0.80, alias="ANTHROPIC_FAST_INPUT_COST_PER_MILLION")
    anthropic_fast_output_cost_per_million: float = Field(default=4.00, alias="ANTHROPIC_FAST_OUTPUT_COST_PER_MILLION")

    # Local vLLM is normally treated as zero marginal API cost. The quality/speed
    # values let the router compare it fairly with paid API models.
    vllm_input_cost_per_million: float = Field(default=0.0, alias="VLLM_INPUT_COST_PER_MILLION")
    vllm_output_cost_per_million: float = Field(default=0.0, alias="VLLM_OUTPUT_COST_PER_MILLION")
    vllm_quality_score: float = Field(default=0.62, alias="VLLM_QUALITY_SCORE")
    vllm_speed_score: float = Field(default=0.72, alias="VLLM_SPEED_SCORE")
    vllm_context_window_tokens: int = Field(default=8192, alias="VLLM_CONTEXT_WINDOW_TOKENS")

    # Expert Agent loop controls. Extra loops require an explicit CLI/state command.
    agent_supervisor_max_tool_loops: int = Field(default=2, alias="AGENT_SUPERVISOR_MAX_TOOL_LOOPS")
    agent_supervisor_extra_loop_enabled: bool = Field(default=False, alias="AGENT_SUPERVISOR_EXTRA_LOOP_ENABLED")

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
