"""Normalized, client-safe error codes for model and dependency failures.

The Agent must never hand a raw SDK exception to a user: those messages can
contain request URLs, key prefixes or a traceback. Everything is mapped to a
small vocabulary here, and the degraded summary turns the code into a concrete
follow-up step.
"""

from __future__ import annotations

import openai

# Model-side failures.
MODEL_TIMEOUT = "MODEL_TIMEOUT"
MODEL_RATE_LIMITED = "MODEL_RATE_LIMITED"
MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
MODEL_AUTH_ERROR = "MODEL_AUTH_ERROR"
MODEL_INVALID_REQUEST = "MODEL_INVALID_REQUEST"
MODEL_ERROR = "MODEL_ERROR"

# Agent-side failures that are not the model's fault.
REQUEST_TIMEOUT = "REQUEST_TIMEOUT"
AGENT_INTERNAL_ERROR = "AGENT_INTERNAL_ERROR"


def describe_model_error(exc: BaseException) -> tuple[str, str]:
    """Map a model/dependency exception to ``(error_code, safe_message)``.

    Matching order matters: ``APITimeoutError`` is a subclass of
    ``APIConnectionError``, so the more specific type is checked first. The
    returned message is fixed text — never ``str(exc)``.
    """

    if isinstance(exc, openai.APITimeoutError):
        return MODEL_TIMEOUT, "调用模型超时"
    if isinstance(exc, openai.RateLimitError):
        return MODEL_RATE_LIMITED, "模型服务触发限流"
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return MODEL_AUTH_ERROR, "模型鉴权失败，请检查 API Key 配置"
    if isinstance(exc, openai.APIConnectionError):
        return MODEL_UNAVAILABLE, "无法连接模型服务"
    if isinstance(exc, (openai.BadRequestError, openai.UnprocessableEntityError)):
        return MODEL_INVALID_REQUEST, "模型拒绝了本次请求参数"
    if isinstance(exc, openai.InternalServerError):
        return MODEL_UNAVAILABLE, "模型服务内部错误"
    if isinstance(exc, openai.APIStatusError):
        return MODEL_ERROR, "模型返回了非预期的状态码"
    if isinstance(exc, openai.APIError):
        return MODEL_ERROR, "模型调用失败"
    if isinstance(exc, TimeoutError):
        return MODEL_TIMEOUT, "调用模型超时"
    return AGENT_INTERNAL_ERROR, "Agent 内部执行失败"
