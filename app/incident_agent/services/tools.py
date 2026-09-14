"""Agent tools with deterministic behavior and dependency injection."""

from __future__ import annotations

import re
from typing import Any

from langchain_core.tools import BaseTool, tool
from pydantic import ValidationError

from ..schemas.tool import (
    AnalyzeLogArgs,
    GetServiceStatusArgs,
    SearchKnowledgeArgs,
    ToolResult,
)
from .rag_client import RagGateway, RagGatewayError

LOG_SIGNAL_PATTERNS: dict[str, re.Pattern[str]] = {
    # 显式数字边界：`(?<!\d)` / `(?!\d)` 比 `\b` 更准确，\b 会把 "15020"
    # 这类订单号里的 502 当成命中（反之也可能漏掉 5020 这类写法）。
    "http_5xx": re.compile(r"(?<!\d)5\d{2}(?!\d)"),
    "timeout": re.compile(r"timeout|timed out|超时", re.IGNORECASE),
    "database_error": re.compile(r"mysql|database|数据库|deadlock|连接池", re.IGNORECASE),
    "traceback": re.compile(r"traceback|stack trace|异常堆栈", re.IGNORECASE),
}

MAX_MATCHED_TEXT = 120
MAX_SIGNALS_PER_TYPE = 3


def analyze_log(log_text: str) -> dict[str, Any]:
    """Extract known incident signals without claiming a root cause.

    Each signal carries the matched fragment and its line number so the caller
    (and the user-facing degraded summary) can point at a concrete line instead
    of just asserting "a keyword matched".
    """

    try:
        args = AnalyzeLogArgs(log_text=log_text)
    except Exception as exc:
        return ToolResult(
            ok=False,
            error_code="INVALID_ARGUMENTS",
            error="日志参数校验失败",
            data={"details": str(exc)},
        ).model_dump()

    lines = args.log_text.splitlines() or [args.log_text]
    signals: list[dict[str, Any]] = []

    for signal_type, pattern in LOG_SIGNAL_PATTERNS.items():
        hits = 0
        for line_number, line in enumerate(lines, start=1):
            if hits >= MAX_SIGNALS_PER_TYPE:
                break
            match = pattern.search(line)
            if match is None:
                continue
            hits += 1
            matched_text = match.group(0)
            if len(matched_text) > MAX_MATCHED_TEXT:
                matched_text = matched_text[:MAX_MATCHED_TEXT]
            signals.append(
                {
                    "type": signal_type,
                    "value": f"第 {line_number} 行命中 {matched_text}",
                    "matched_text": matched_text,
                    "line_number": line_number,
                }
            )

    return ToolResult(
        ok=True,
        data={
            "signals": signals,
            "signal_count": len(signals),
        },
    ).model_dump()


def get_service_status(service_name: str) -> dict[str, Any]:
    """Return a status from the MVP's explicit mock service registry."""

    try:
        args = GetServiceStatusArgs(service_name=service_name)
    except Exception as exc:
        return ToolResult(
            ok=False,
            error_code="INVALID_ARGUMENTS",
            error="服务名称参数校验失败",
            data={"details": str(exc)},
        ).model_dump()

    statuses = {
        "order-service": {
            "status": "degraded",
            "deploy_version": "2026.08.31",
            "error_count": 27,
        },
        "user-service": {
            "status": "healthy",
            "deploy_version": "2026.08.30",
            "error_count": 0,
        },
    }

    service = statuses.get(args.service_name)

    if service is None:
        return ToolResult(
            ok=False,
            error_code="UNKNOWN_SERVICE",
            error=f"未知服务：{args.service_name}",
        ).model_dump()

    return ToolResult(
        ok=True,
        data={
            "service_name": args.service_name,
            **service,
        },
    ).model_dump()


def build_tools(
    rag_gateway: RagGateway,
    access_token: str | None = None,
    *,
    knowledge_base_id: int = 1,
    top_k: int = 5,
) -> list[BaseTool]:
    """Build LangChain tools with request-scoped RAG boundaries.

    The knowledge-base scope and recall count are injected by the service,
    rather than exposed as model-controlled tool arguments. Defaults exist
    only for isolated unit tests that build tools without a request context.
    """

    if knowledge_base_id <= 0:
        raise ValueError("knowledge_base_id 必须大于 0")
    if not 1 <= top_k <= 10:
        raise ValueError("top_k 必须在 1 到 10 之间")

    @tool
    def search_knowledge(
        query: str,
    ) -> dict[str, Any]:
        """在 DevAtlas 知识库中检索故障相关文档片段。"""

        try:
            args = SearchKnowledgeArgs(query=query)
            result = rag_gateway.search_knowledge(
                query=args.query,
                knowledge_base_id=knowledge_base_id,
                top_k=top_k,
                access_token=access_token,
            )
        except ValidationError as exc:
            return ToolResult(
                ok=False,
                error_code="INVALID_ARGUMENTS",
                error="知识库检索参数校验失败",
                data={"details": str(exc)},
            ).model_dump()
        except RagGatewayError as exc:
            return ToolResult(
                ok=False,
                error_code=exc.error_code,
                error=exc.message,
            ).model_dump()
        except Exception as exc:
            return ToolResult(
                ok=False,
                error_code="RAG_TOOL_ERROR",
                error="知识库工具执行失败",
                data={"details": str(exc)},
            ).model_dump()

        return ToolResult(
            ok=True,
            data=result.model_dump(),
        ).model_dump()

    @tool
    def analyze_log_tool(log_text: str) -> dict[str, Any]:
        """从故障日志中提取 502、超时和数据库错误信号。"""

        return analyze_log(log_text)

    @tool
    def get_service_status_tool(service_name: str) -> dict[str, Any]:
        """查询指定服务的当前模拟状态。"""

        return get_service_status(service_name)

    analyze_log_tool.name = "analyze_log"
    get_service_status_tool.name = "get_service_status"

    return [
        analyze_log_tool,
        search_knowledge,
        get_service_status_tool,
    ]
