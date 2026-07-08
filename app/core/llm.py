# app/core/llm.py

from __future__ import annotations

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.core.config import get_settings

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


def get_chat_model(temperature: float = 0.0) -> ChatOpenAI:
    settings = get_settings()

    return ChatOpenAI(
        model=normalize_blank(settings.vllm_model, DEFAULT_VLLM_MODEL),
        base_url=normalize_blank(settings.vllm_base_url, DEFAULT_VLLM_BASE_URL),
        api_key=normalize_blank(settings.vllm_api_key, DEFAULT_VLLM_API_KEY),
        temperature=temperature,
    )
