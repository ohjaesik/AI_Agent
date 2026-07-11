# app/core/config.py

"""애플리케이션 전체 환경설정을 Pydantic Settings로 읽는다.

`.env`에 있는 DB, LLM, RAG, Supervisor autonomy, API 보안, storage 설정을 한곳에서
정의한다. 다른 모듈은 직접 os.environ을 읽지 않고 `get_settings()`를 통해 이 객체를
사용한다. 이렇게 해야 기본값, 타입 변환, alias 이름을 한곳에서 관리할 수 있다.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_OPENAI_EXTRA_MODEL_PROFILES_JSON = (
    '[{"model":"gpt-4.1-mini","tier":"economy","quality_score":0.74,'
    '"speed_score":0.94,"context_window_tokens":1048576,'
    '"input_cost_per_million":0.40,"output_cost_per_million":1.60},'
    '{"model":"gpt-4.1-nano","tier":"nano","quality_score":0.67,'
    '"speed_score":0.97,"context_window_tokens":1048576,'
    '"input_cost_per_million":0.10,"output_cost_per_million":0.40}]'
)


class Settings(BaseSettings):
    """환경변수 기반 설정 모델.

    Field alias는 `.env`에 쓰는 실제 키 이름이다. 코드에서는 snake_case 속성으로
    접근하고, 운영자는 대문자 env key로 값을 조정한다.
    """

    # PostgreSQL
    database_url: str = Field(alias="DATABASE_URL")

    postgres_host: str | None = Field(default=None, alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_db: str | None = Field(default=None, alias="POSTGRES_DB")
    postgres_user: str | None = Field(default=None, alias="POSTGRES_USER")
    postgres_password: str | None = Field(default=None, alias="POSTGRES_PASSWORD")

    # OpenAI Embedding / RAG chunking
    # embedding_model/dim은 pgvector 색인 차원과 맞아야 한다.
    # chunk strategy는 기본 semantic이며, recursive로 되돌릴 수 있다.
    openai_api_key: str = Field(alias="OPENAI_API_KEY")
    embedding_model: str = Field(default="text-embedding-3-small", alias="EMBEDDING_MODEL")
    embedding_dim: int = Field(default=1536, alias="EMBEDDING_DIM")
    rag_chunk_strategy: str = Field(default="semantic", alias="RAG_CHUNK_STRATEGY")
    rag_semantic_similarity_threshold: float = Field(default=0.16, alias="RAG_SEMANTIC_SIMILARITY_THRESHOLD")
    rag_semantic_min_chunk_chars: int = Field(default=360, alias="RAG_SEMANTIC_MIN_CHUNK_CHARS")

    # vLLM OpenAI-compatible endpoint
    # vLLM은 OpenAI SDK 호환 endpoint로 호출한다. model_router에서 vLLM을 선택하면
    # 여기에 적힌 base_url/model이 그대로 사용된다.
    vllm_base_url: str = Field(default="http://localhost:8000/v1", alias="VLLM_BASE_URL")
    vllm_api_key: str = Field(default="EMPTY", alias="VLLM_API_KEY")
    vllm_model: str = Field(default="gemma-4-e4b-it", alias="VLLM_MODEL")

    # External LLM provider keys. OPENAI_API_KEY is already used for embeddings;
    # ANTHROPIC_API_KEY is optional and only used when the model router selects Claude.
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")

    # Supervisor-driven model routing. The router keeps vLLM as the default local
    # path, but can select GPT/Claude models when their keys are configured.
    # enable_* flag로 특정 provider를 실험적으로 제외할 수 있다.
    model_router_enabled: bool = Field(default=True, alias="MODEL_ROUTER_ENABLED")
    model_router_enable_vllm: bool = Field(default=True, alias="MODEL_ROUTER_ENABLE_VLLM")
    model_router_enable_openai: bool = Field(default=True, alias="MODEL_ROUTER_ENABLE_OPENAI")
    model_router_enable_anthropic: bool = Field(default=True, alias="MODEL_ROUTER_ENABLE_ANTHROPIC")
    model_router_target_seconds: float = Field(default=45.0, alias="MODEL_ROUTER_TARGET_SECONDS")
    model_router_cost_sensitivity: float = Field(default=0.35, alias="MODEL_ROUTER_COST_SENSITIVITY")
    model_router_quality_floor_margin: float = Field(default=0.12, alias="MODEL_ROUTER_QUALITY_FLOOR_MARGIN")

    # The Supervisor Agent is treated as the highest-risk orchestration role, so
    # it is pinned to this upper-tier model whenever the configured provider is available.
    # Expert Agent는 cost/performance 수식을 타지만 Supervisor는 품질 우선 고정 정책이다.
    supervisor_model_provider: str = Field(default="openai", alias="SUPERVISOR_MODEL_PROVIDER")
    supervisor_model_name: str = Field(default="gpt-5.6-sol", alias="SUPERVISOR_MODEL_NAME")
    supervisor_llm_enabled: bool = Field(default=True, alias="SUPERVISOR_LLM_ENABLED")
    supervisor_minimal_human_approval: bool = Field(default=True, alias="SUPERVISOR_MINIMAL_HUMAN_APPROVAL")
    supervisor_llm_timeout_seconds: float = Field(default=45.0, alias="SUPERVISOR_LLM_TIMEOUT_SECONDS")
    supervisor_llm_retry_count: int = Field(default=2, alias="SUPERVISOR_LLM_RETRY_COUNT")
    supervisor_llm_retry_timeout_multiplier: float = Field(default=1.8, alias="SUPERVISOR_LLM_RETRY_TIMEOUT_MULTIPLIER")
    agent_llm_timeout_seconds: float = Field(default=10.0, alias="AGENT_LLM_TIMEOUT_SECONDS")
    agent_llm_retry_count: int = Field(default=1, alias="AGENT_LLM_RETRY_COUNT")
    agent_llm_retry_timeout_multiplier: float = Field(default=1.6, alias="AGENT_LLM_RETRY_TIMEOUT_MULTIPLIER")

    # Long-goal autonomy controls. Supervisor keeps the workflow autonomous inside
    # this bounded budget, while still escalating sensitive/high-impact/final
    # business decisions to Human Review.
    # max_stage_loops는 stage 단위 상한이고 extra_loop_budget은 base loop 위에 더할 수
    # 있는 추가 반복 수다. cost_budget은 추정 LLM 비용 기준 stop-loss다.
    supervisor_autonomy_enabled: bool = Field(default=True, alias="SUPERVISOR_AUTONOMY_ENABLED")
    supervisor_autonomy_level: str = Field(default="controlled_high", alias="SUPERVISOR_AUTONOMY_LEVEL")
    supervisor_autonomous_max_stage_loops: int = Field(default=4, alias="SUPERVISOR_AUTONOMOUS_MAX_STAGE_LOOPS")
    supervisor_autonomous_extra_loop_budget: int = Field(default=2, alias="SUPERVISOR_AUTONOMOUS_EXTRA_LOOP_BUDGET")
    supervisor_autonomous_cost_budget_usd: float = Field(default=1.5, alias="SUPERVISOR_AUTONOMOUS_COST_BUDGET_USD")

    # Model candidates used by the cost/performance router. Prices are USD per
    # one million tokens and can be updated without code changes.
    # 가격표가 바뀌면 코드 수정 없이 .env만 바꿔도 cost_calculation trace가 갱신된다.
    openai_high_model: str = Field(default="gpt-5.6-sol", alias="OPENAI_HIGH_MODEL")
    openai_balanced_model: str = Field(default="gpt-5.6-terra", alias="OPENAI_BALANCED_MODEL")
    openai_fast_model: str = Field(default="gpt-5.6-luna", alias="OPENAI_FAST_MODEL")
    openai_extra_model_profiles_json: str = Field(
        default=DEFAULT_OPENAI_EXTRA_MODEL_PROFILES_JSON,
        alias="OPENAI_EXTRA_MODEL_PROFILES_JSON",
    )
    openai_high_input_cost_per_million: float = Field(default=5.00, alias="OPENAI_HIGH_INPUT_COST_PER_MILLION")
    openai_high_output_cost_per_million: float = Field(default=30.00, alias="OPENAI_HIGH_OUTPUT_COST_PER_MILLION")
    openai_balanced_input_cost_per_million: float = Field(default=2.50, alias="OPENAI_BALANCED_INPUT_COST_PER_MILLION")
    openai_balanced_output_cost_per_million: float = Field(default=15.00, alias="OPENAI_BALANCED_OUTPUT_COST_PER_MILLION")
    openai_fast_input_cost_per_million: float = Field(default=1.00, alias="OPENAI_FAST_INPUT_COST_PER_MILLION")
    openai_fast_output_cost_per_million: float = Field(default=6.00, alias="OPENAI_FAST_OUTPUT_COST_PER_MILLION")

    anthropic_high_model: str = Field(default="claude-3-5-sonnet-latest", alias="ANTHROPIC_HIGH_MODEL")
    anthropic_fast_model: str = Field(default="claude-3-5-haiku-latest", alias="ANTHROPIC_FAST_MODEL")
    anthropic_high_input_cost_per_million: float = Field(default=3.00, alias="ANTHROPIC_HIGH_INPUT_COST_PER_MILLION")
    anthropic_high_output_cost_per_million: float = Field(default=15.00, alias="ANTHROPIC_HIGH_OUTPUT_COST_PER_MILLION")
    anthropic_fast_input_cost_per_million: float = Field(default=0.80, alias="ANTHROPIC_FAST_INPUT_COST_PER_MILLION")
    anthropic_fast_output_cost_per_million: float = Field(default=4.00, alias="ANTHROPIC_FAST_OUTPUT_COST_PER_MILLION")

    # Local vLLM is normally treated as zero marginal API cost. The quality/speed
    # values let the router compare it fairly with paid API models.
    # 품질/속도 점수는 실제 benchmark가 아니라 router 비교용 상대 점수다.
    vllm_input_cost_per_million: float = Field(default=0.0, alias="VLLM_INPUT_COST_PER_MILLION")
    vllm_output_cost_per_million: float = Field(default=0.0, alias="VLLM_OUTPUT_COST_PER_MILLION")
    vllm_quality_score: float = Field(default=0.62, alias="VLLM_QUALITY_SCORE")
    vllm_speed_score: float = Field(default=0.72, alias="VLLM_SPEED_SCORE")
    vllm_context_window_tokens: int = Field(default=8192, alias="VLLM_CONTEXT_WINDOW_TOKENS")

    # Expert Agent loop controls. Extra loops are enabled by default for the
    # controlled autonomous Supervisor, and can still be disabled explicitly.
    # CLI의 --disable-agent-extra-loop가 들어오면 이 기본값보다 CLI가 우선한다.
    agent_supervisor_max_tool_loops: int = Field(default=2, alias="AGENT_SUPERVISOR_MAX_TOOL_LOOPS")
    agent_supervisor_extra_loop_enabled: bool = Field(default=True, alias="AGENT_SUPERVISOR_EXTRA_LOOP_ENABLED")

    # External data source secrets
    dart_api_key: str | None = Field(default=None, alias="DART_API_KEY")

    # External public web discovery. Disabled by default; use only with an explicit provider/API key.
    # replan 단계에서 공식 도메인만으로 근거 보강이 어려울 때 선택적으로 쓴다.
    external_web_discovery_enabled: bool = Field(default=False, alias="EXTERNAL_WEB_DISCOVERY_ENABLED")
    external_web_search_provider: str = Field(default="brave", alias="EXTERNAL_WEB_SEARCH_PROVIDER")
    brave_search_api_key: str | None = Field(default=None, alias="BRAVE_SEARCH_API_KEY")
    serpapi_api_key: str | None = Field(default=None, alias="SERPAPI_API_KEY")
    external_web_max_results: int = Field(default=3, alias="EXTERNAL_WEB_MAX_RESULTS")

    # Replan loop guard. 0 disables replan and routes evidence gaps directly to Human Review.
    # 이 값은 "새 출처 수집/재색인" loop 상한이고, Agent stage extra loop와는 별도다.
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
    """Settings 객체를 캐시해서 여러 모듈이 같은 설정을 재사용하게 한다."""

    return Settings()
