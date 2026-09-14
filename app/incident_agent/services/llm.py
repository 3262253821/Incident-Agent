"""Factory for the request-independent DeepSeek chat model.

Model settings live in ``Settings`` (see ``core/config.py`` and ``.env.example``)
instead of being literals in this module, so tuning a deployment does not require
a code change:

```text
INCIDENT_AGENT_MODEL                 决策模型
INCIDENT_AGENT_REPORT_MODEL          报告模型（默认与决策模型相同）
INCIDENT_AGENT_TEMPERATURE           默认 0.1
INCIDENT_AGENT_MAX_TOKENS            默认不限（None）
INCIDENT_MODEL_TIMEOUT_SECONDS       单次调用超时
INCIDENT_MODEL_MAX_RETRIES           默认 0
```
"""

from __future__ import annotations

import os

from langchain_openai import ChatOpenAI

from ..core.config import Settings

# 连接超时按读取超时的固定比例缩放，避免把连接慢误判成整体不可用。
CONNECT_TIMEOUT_SECONDS = 5.0


def _resolve_timeout(model_timeout: float) -> float | tuple[float, float]:
    """Build the httpx timeout: (connect, read) unless the budget is tiny."""

    connect_timeout = min(CONNECT_TIMEOUT_SECONDS, model_timeout)
    if connect_timeout >= model_timeout:
        return model_timeout
    return (connect_timeout, model_timeout)


def _build(
    *,
    model_name: str,
    api_key: str,
    settings: Settings,
) -> ChatOpenAI:
    kwargs: dict[str, object] = {
        "model": model_name,
        "api_key": api_key,
        "base_url": settings.model_base_url,
        "temperature": settings.model_temperature,
        "timeout": _resolve_timeout(settings.model_timeout_seconds),
        # SDK 默认 2 次自动重试：会让最坏延迟翻倍且难以推理，因此显式关闭。
        "max_retries": settings.model_max_retries,
    }
    if settings.model_max_tokens is not None:
        kwargs["max_tokens"] = settings.model_max_tokens
    return ChatOpenAI(**kwargs)


def require_api_key() -> str:
    """Return the configured API key or fail with a readable message."""

    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY，无法调用模型")
    return api_key


def create_chat_model(settings: Settings) -> ChatOpenAI:
    """Create the decision model.

    Two SDK defaults are deliberately overridden:

    - ``timeout``: the OpenAI SDK defaults to 600 seconds. A hung call would hold
      a FastAPI worker thread and a MySQL session for ten minutes, long past the
      caller's own deadline.
    - ``max_retries``: invisible retries multiply worst-case latency; failures are
      surfaced immediately and normalised into ``MODEL_*`` error codes instead.
    """

    return _build(
        model_name=settings.model,
        api_key=require_api_key(),
        settings=settings,
    )


def create_report_model(settings: Settings) -> ChatOpenAI:
    """Create the model used by the report node.

    Separate from the decision model on purpose: report generation is a
    formatting/validation task that benefits from a different (often cheaper or
    lower-temperature) model, and it must never be bound to tools.
    """

    return _build(
        model_name=settings.report_model,
        api_key=require_api_key(),
        settings=settings,
    )
