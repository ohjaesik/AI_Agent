# app/core/llm.py

from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.core.config import get_settings
from app.core.retry import retry_call

DEFAULT_VLLM_BASE_URL = "http://localhost:8000/v1"
DEFAULT_VLLM_API_KEY = "EMPTY"
DEFAULT_VLLM_MODEL = "google/gemma-2-9b-it"


def normalize_blank(value: str | None, default: str) -> str:
    if value is None:
        return default

    value = str(value).strip()

    if not value:
        return default

    return value


def get_embedding_model() -> OpenAIEmbeddings:
    settings = get_settings()

    return OpenAIEmbeddings(
        model=settings.embedding_model,
        dimensions=settings.embedding_dim,
        api_key=settings.openai_api_key,
    )


def embed_documents_with_retry(texts: list[str], retries: int = 2) -> list[list[float]]:
    embeddings = get_embedding_model()
    return retry_call(lambda: embeddings.embed_documents(texts), retries=retries, backoff_seconds=1.0)


def embed_query_with_retry(query: str, retries: int = 2) -> list[float]:
    embeddings = get_embedding_model()
    return retry_call(lambda: embeddings.embed_query(query), retries=retries, backoff_seconds=1.0)


def get_chat_model(temperature: float = 0.0, timeout: float | None = None) -> ChatOpenAI:
    settings = get_settings()
    kwargs: dict[str, Any] = {}
    if timeout is not None:
        kwargs["timeout"] = timeout

    return ChatOpenAI(
        model=normalize_blank(settings.vllm_model, DEFAULT_VLLM_MODEL),
        base_url=normalize_blank(settings.vllm_base_url, DEFAULT_VLLM_BASE_URL),
        api_key=normalize_blank(settings.vllm_api_key, DEFAULT_VLLM_API_KEY),
        temperature=temperature,
        **kwargs,
    )


def invoke_chat_with_retry(llm: ChatOpenAI, messages: list[Any], retries: int = 2) -> Any:
    return retry_call(lambda: llm.invoke(messages), retries=retries, backoff_seconds=1.0)
