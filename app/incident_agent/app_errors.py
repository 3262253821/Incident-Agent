"""Unified, client-safe error responses (P1-2-4).

Two problems this module closes:

1. Exceptions raised *outside* ``execute_incident`` (a database write failure, a
   schema deserialisation error, a bug in a dependency) used to reach FastAPI's
   default handler, which returns a bare ``{"detail": "Internal Server Error"}``
   and prints the traceback to the server log.
2. Clients had no way to quote a request when reporting a problem.

Design rules:

- the response body is **always** ``{"detail", "error_code", "request_id"}``, so
  the frontend's existing ``detail`` handling keeps working unchanged;
- ``str(exc)`` never reaches the client — it can contain file paths, SQL and
  secrets. Only fixed text plus a code is returned;
- the server log gets the full exception (with traceback) **plus** the
  ``request_id``, which is also echoed in the ``X-Request-ID`` header.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .core.errors import AGENT_INTERNAL_ERROR
from .core.logging import get_logger

LOGGER_NAME = "errors"
REQUEST_ID_HEADER = "X-Request-ID"

# Fixed, non-leaking messages per status code.
STATUS_MESSAGES: dict[int, str] = {
    400: "请求格式不正确",
    401: "登录状态无效或已过期",
    403: "没有权限执行该操作",
    404: "请求的资源不存在",
    422: "请求参数校验失败",
    429: "请求过于频繁，请稍后重试",
    500: "服务内部错误，请稍后重试",
    502: "上游服务返回错误",
    503: "依赖服务暂不可用，请稍后重试",
}

# Stable error codes handed to clients and reused in logs.
STATUS_ERROR_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: AGENT_INTERNAL_ERROR,
    502: "UPSTREAM_ERROR",
    503: "DEPENDENCY_UNAVAILABLE",
}

logger = get_logger(LOGGER_NAME)


def resolve_request_id(request: Request) -> str:
    """Reuse the incoming ``X-Request-ID`` when present, else mint one."""

    state_id = getattr(request.state, "request_id", None)
    if isinstance(state_id, str) and state_id:
        return state_id
    incoming = request.headers.get(REQUEST_ID_HEADER)
    if incoming and len(incoming) <= 128:
        return incoming
    return uuid.uuid4().hex


def error_code_for(status_code: int) -> str:
    return STATUS_ERROR_CODES.get(status_code, f"HTTP_{status_code}")


def message_for(status_code: int, detail: object | None):
    """Resolve the body's ``detail`` value.

    - a non-empty string is passed through (routers write user-facing text there);
    - a **list is passed through unchanged** — that is the field-level validation
      shape the frontend looks for via ``Array.isArray(detail)``; collapsing it
      into fixed text would silently downgrade field-level hints to a generic
      message;
    - anything else falls back to a fixed message for the status code.
    """

    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    if isinstance(detail, list) and detail:
        return detail
    return STATUS_MESSAGES.get(status_code, "请求失败")


def build_error_response(
    *,
    status_code: int,
    detail: object | None,
    request_id: str,
    error_code: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build the single error shape used by every endpoint.

    Extra keys are additive: the frontend reads ``detail`` and the HTTP status,
    so adding ``error_code`` / ``request_id`` cannot break existing handling.
    """

    body = {
        "detail": message_for(status_code, detail),
        "error_code": error_code or error_code_for(status_code),
        "request_id": request_id,
    }
    response_headers = dict(headers or {})
    response_headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(
        status_code=status_code,
        content=body,
        headers=response_headers,
    )


async def request_id_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable],
):
    """Attach a request id and expose it so failures can be correlated."""

    request_id = resolve_request_id(request)
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


def register_exception_handlers(app: FastAPI) -> None:
    """Install the handlers that make every error response safe and traceable."""

    from fastapi import HTTPException

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request,
        exc: HTTPException,
    ) -> JSONResponse:
        request_id = resolve_request_id(request)
        status_code = exc.status_code
        if status_code >= 500:
            logger.error(
                "接口返回服务器错误",
                extra={
                    "request_id": request_id,
                    "path": request.url.path,
                    "method": request.method,
                    "status_code": status_code,
                    "error_code": error_code_for(status_code),
                },
            )
        return build_error_response(
            status_code=status_code,
            detail=exc.detail,
            request_id=request_id,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        request_id = resolve_request_id(request)
        # detail 必须保持为**列表**：前端用 Array.isArray(detail) 判断是否做
        # 字段级提示。Pydantic v2.13 把 errors() 包成 {"detail": {...}} 形状，
        # 直接用会让 detail 变成 str/dict，字段级提示就退化成通用文案。
        field_errors = jsonable_encoder(exc.errors())
        if isinstance(field_errors, dict):
            field_errors = field_errors.get("detail", field_errors)
        if not isinstance(field_errors, list):
            field_errors = [field_errors]
        # 服务端日志只记字段路径摘要，不整段落盘。
        logger.info(
            "请求参数校验失败",
            extra={
                "request_id": request_id,
                "path": request.url.path,
                "method": request.method,
                "status_code": 422,
                "error_code": error_code_for(422),
                "invalid_fields": [
                    ".".join(str(part) for part in error.get("loc", ()))
                    for error in field_errors
                    if isinstance(error, dict)
                ],
            },
        )
        return build_error_response(
            status_code=422,
            detail=field_errors,
            request_id=request_id,
            error_code=error_code_for(422),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        request_id = resolve_request_id(request)
        # Full traceback server-side (the logger's formatter keeps only the
        # exception class name in the JSON payload), fixed text client-side.
        logger.error(
            "未处理的异常，已转为安全响应",
            extra={
                "request_id": request_id,
                "path": request.url.path,
                "method": request.method,
                "status_code": 500,
                "error_code": error_code_for(500),
                "exception_type": type(exc).__name__,
            },
            exc_info=True,
        )
        return build_error_response(
            status_code=500,
            detail=STATUS_MESSAGES[500],
            request_id=request_id,
        )
