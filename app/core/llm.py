# app/core/llm.py

"""OpenAI/Anthropic/vLLM LLM client와 embedding 호출 helper.

model_assignment에 따라 provider를 선택하고, report writer/critic/Supervisor/Agent가
같은 방식으로 chat model을 얻도록 한다.
"""

from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.core.config import get_settings
from app.core.model_policy import (
    is_model_availability_exception as policy_is_model_availability_exception,
    normalize_blank as policy_normalize_blank,
)
from app.core.retry import retry_call

DEFAULT_VLLM_BASE_URL = "http://localhost:8000/v1"
DEFAULT_VLLM_API_KEY = "EMPTY"
DEFAULT_VLLM_MODEL = "gemma-4-e4b-it"


def normalize_blank(value: str | None, default: str) -> str:
    """normalize_blank 함수. 비교/저장/출력을 안정화하기 위해 입력값 형식을 정규화한다."""
    return policy_normalize_blank(value, default)


def is_model_availability_exception(exc: Exception) -> bool:
    """선택한 모델명이 없거나 계정 접근권한이 없을 때 재라우팅 가능한 오류로 판단한다.

    GPT-5.6 계열처럼 계정별 rollout/권한 차이가 생길 수 있는 모델은 처음 선택이
    실패해도 workflow 전체를 포기하지 말고 다음 후보로 재시도해야 한다. 인증키 자체가
    틀린 오류와 구분하기 위해 "model/access/deployment" 관련 문구만 좁게 본다.
    """

    return policy_is_model_availability_exception(exc)


def get_embedding_model() -> OpenAIEmbeddings:
    """get_embedding_model 함수. DB나 설정/state에서 필요한 값을 조회해 호출자에게 반환한다."""
    settings = get_settings()

    return OpenAIEmbeddings(
        model=settings.embedding_model,
        dimensions=settings.embedding_dim,
        api_key=settings.openai_api_key,
    )


def embed_documents_with_retry(texts: list[str], retries: int = 2) -> list[list[float]]:
    """문서 chunk 목록을 embedding vector 목록으로 변환한다."""
    embeddings = get_embedding_model()
    return retry_call(lambda: embeddings.embed_documents(texts), retries=retries, backoff_seconds=1.0)


def embed_query_with_retry(query: str, retries: int = 2) -> list[float]:
    """RAG 검색 query를 embedding vector로 변환한다."""
    embeddings = get_embedding_model()
    return retry_call(lambda: embeddings.embed_query(query), retries=retries, backoff_seconds=1.0)


def get_chat_model(
    temperature: float = 0.0,
    timeout: float | None = None,
    model_assignment: dict[str, Any] | None = None,
) -> Any:
    """LLM chat client를 생성한다.

    기본값은 기존 동작과 동일하게 .env의 vLLM OpenAI-compatible endpoint를
    사용한다. model_assignment가 들어오면 Supervisor 모델 라우터가 고른
    provider/model 조합을 따른다.
    """

    settings = get_settings()
    kwargs: dict[str, Any] = {}
    if timeout is not None:
        kwargs["timeout"] = timeout

    provider = str((model_assignment or {}).get("provider") or "vllm").lower()
    model_name = str((model_assignment or {}).get("model") or "").strip()

    if provider == "openai":
        return ChatOpenAI(
            model=normalize_blank(model_name, settings.openai_high_model),
            api_key=settings.openai_api_key,
            temperature=temperature,
            **kwargs,
        )

    if provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:
            raise RuntimeError(
                "Anthropic 모델이 선택되었지만 langchain-anthropic 패키지가 설치되어 있지 않습니다. "
                "requirements.txt 설치를 다시 확인하세요."
            ) from exc

        return ChatAnthropic(
            model=normalize_blank(model_name, settings.anthropic_high_model),
            api_key=settings.anthropic_api_key,
            temperature=temperature,
            **kwargs,
        )

    # vLLM은 OpenAI-compatible endpoint로 호출한다. 모델명/base_url/api_key는
    # 모두 .env의 VLLM_* 값을 기준으로 두어 로컬 모델 교체가 코드 변경 없이 가능하다.
    return ChatOpenAI(
        model=normalize_blank(model_name or settings.vllm_model, DEFAULT_VLLM_MODEL),
        base_url=normalize_blank(settings.vllm_base_url, DEFAULT_VLLM_BASE_URL),
        api_key=normalize_blank(settings.vllm_api_key, DEFAULT_VLLM_API_KEY),
        temperature=temperature,
        **kwargs,
    )


def invoke_chat_with_retry(llm: Any, messages: list[Any], retries: int = 2) -> Any:
    """chat model 호출을 retry policy로 감싸 일시적 실패를 완화한다."""
    return retry_call(lambda: llm.invoke(messages), retries=retries, backoff_seconds=1.0)
