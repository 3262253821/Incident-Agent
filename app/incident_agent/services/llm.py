"""Factory for the request-independent DeepSeek chat model."""

from __future__ import annotations

import os

from langchain_openai import ChatOpenAI

from ..core.config import Settings


def create_chat_model(settings: Settings) -> ChatOpenAI:
    """Create a DeepSeek-compatible model without printing the API key."""

    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY，无法调用模型")

    return ChatOpenAI(
        model=settings.model,
        api_key=api_key,
        base_url=settings.model_base_url,
        temperature=0.1,
    )

