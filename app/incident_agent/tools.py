"""Agent tools with deterministic behavior and dependency injection."""

from __future__ import annotations

import re
from typing import Any

from langchain_core.tools import BaseTool, tool
from pydantic import ValidationError

from .rag_client import RagGateway, RagGatewayError
from .schemas import (
    AnalyzeLogArgs,
    GetServiceStatusArgs,
    SearchKnowledgeArgs,
    ToolResult,
)


def analyze_log(log_text: str) -> dict[str, Any]:
    """Extract known incident signals without claiming a root cause."""

    try:
        args = AnalyzeLogArgs(log_text=log_text)
    except Exception as exc:
        return ToolResult(
            ok=False,
            error_code="INVALID_ARGUMENTS",
            error="日志参数校验失败",
            data={"details": str(exc)},
        ).model_dump()

    patterns = {
        "http_502": r"\b502\b",
        "timeout": r"timeout|超时",
        "database_error": r"mysql|database|数据库",
        "traceback": r"traceback",
    }

    signals: list[dict[str, str]] = []

    for signal_type, pattern in patterns.items():
        if re.search(pattern, args.log_text, re.IGNORECASE):
            signals.append(
                {
                    "type": signal_type,
                    "value": "命中日志关键词",
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
) -> list[BaseTool]:
    """Build LangChain tools with a request-scoped RAG dependency."""

    @tool
    def search_knowledge(
        query: str,
        knowledge_base_id: int,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """在 DevAtlas 知识库中检索故障相关文档片段。"""

        try:
            args = SearchKnowledgeArgs(
                query=query,
                knowledge_base_id=knowledge_base_id,
                top_k=top_k,
            )
            result = rag_gateway.search_knowledge(
                query=args.query,
                knowledge_base_id=args.knowledge_base_id,
                top_k=args.top_k,
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
