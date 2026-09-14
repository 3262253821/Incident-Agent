"""Factory for the request-independent DeepSeek chat model."""

from __future__ import annotations

import os

from langchain_openai import ChatOpenAI

from ..core.config import Settings

# 连接超时按读取超时的固定比例缩放，避免把连接慢误判成整体不可用。
CONNECT_TIMEOUT_SECONDS = 5.0


def create_chat_model(settings: Settings) -> ChatOpenAI:
    """Create a DeepSeek-compatible model without printing the API key.

    Two defaults are deliberately overridden:

    - ``timeout``: the OpenAI SDK defaults to 600 seconds. A hung model call
      would hold a FastAPI worker thread and a MySQL session for ten minutes,
      long past the caller's own timeout, so the budget is explicit here.
    - ``max_retries``: the SDK defaults to 2 automatic retries. With the graph
      also limiting model rounds, invisible retries multiply worst-case latency
      and make timeouts hard to reason about. Failures are surfaced immediately
      and normalized into ``MODEL_*`` error codes instead.
    """

    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY，无法调用模型")

    model_timeout = settings.model_timeout_seconds
    connect_timeout = min(CONNECT_TIMEOUT_SECONDS, model_timeout)
    timeout = model_timeout if connect_timeout >= model_timeout else (
        connect_timeout,
        model_timeout,
    )

    return ChatOpenAI(
        model=settings.model,
        api_key=api_key,
        base_url=settings.model_base_url,
        temperature=0.1,
        timeout=timeout,
        max_retries=0,
    )
