from __future__ import annotations

import json
import re
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

# ---------- 统一的数据结构 ----------


class ToolResult(BaseModel):
    """所有工具都使用同一种返回结构。"""

    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error: str | None = None


# ---------- 每个工具的参数模型 ----------


class SearchKnowledgeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    knowledge_base_id: int = Field(gt=0)
    top_k: int = Field(default=3, ge=1, le=10)


class AnalyzeLogArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    log_text: str = Field(min_length=1)


class GetServiceStatusArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_name: str = Field(min_length=1)


# ---------- 三个真实工具 ----------


def search_knowledge(args: SearchKnowledgeArgs) -> ToolResult:
    """模拟知识库检索。"""

    return ToolResult(
        ok=True,
        data={
            "sources": [
                {
                    "content": (
                        "订单服务返回 502 可能与数据库连接超时有关，"
                        "建议检查 MySQL、连接池和网络连通性。"
                    ),
                    "filename": "订单服务故障排查手册.md",
                    "version_id": 3,
                    "chunk_index": 2,
                }
            ],
            "query": args.query,
            "top_k": args.top_k,
        },
    )


def analyze_log(args: AnalyzeLogArgs) -> ToolResult:
    """从日志中提取几个简单故障信号。"""

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
    )


def get_service_status(args: GetServiceStatusArgs) -> ToolResult:
    """查询本地模拟的服务状态。"""

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
        )

    return ToolResult(
        ok=True,
        data={
            "service_name": args.service_name,
            **service,
        },
    )


# ---------- 工具注册表 ----------


TOOL_HANDLERS: dict[str, tuple[type[BaseModel], Callable[..., ToolResult]]] = {
    "search_knowledge": (SearchKnowledgeArgs, search_knowledge),
    "analyze_log": (AnalyzeLogArgs, analyze_log),
    "get_service_status": (GetServiceStatusArgs, get_service_status),
}


def run_tool(tool_name: str, raw_arguments: str) -> ToolResult:
    """统一入口：解析参数、校验参数、执行工具。"""

    # 1. 根据工具名查找工具
    handler_info = TOOL_HANDLERS.get(tool_name)

    if handler_info is None:
        return ToolResult(
            ok=False,
            error_code="UNKNOWN_TOOL",
            error=f"未知工具：{tool_name}",
        )
    # 元组拆包，获取参数模型和工具函数
    args_model, handler = handler_info

    try:
        # 2. 解析json参数
        raw_data = json.loads(raw_arguments)
    except json.JSONDecodeError:
        return ToolResult(
            ok=False,
            error_code="INVALID_JSON",
            error="工具参数不是合法 JSON",
        )

    try:
        # 3. 校验Pydantic模型参数
        args = args_model.model_validate(raw_data)
    except ValidationError as exc:
        return ToolResult(
            ok=False,
            error_code="INVALID_ARGUMENTS",
            error="工具参数校验失败",
            data={"details": exc.errors()},
        )

    try:
        # 4. 执行工具
        return handler(args)
    except Exception as exc:
        return ToolResult(
            ok=False,
            error_code="TOOL_ERROR",
            error=f"工具执行失败：{exc}",
        )


def main() -> None:
    cases = [
        (
            "analyze_log",
            json.dumps(
                {"log_text": ("gateway returned 502; mysql connection timeout")}
            ),
        ),
        (
            "get_service_status",
            json.dumps({"service_name": "user-service"}),
        ),
        (
            "get_service_status",
            json.dumps({"service_name": "unknown-service"}),
        ),
        (
            "search_knowledge",
            json.dumps(
                {
                    "query": "订单服务 502",
                    "knowledge_base_id": 1,
                    "top_k": 3,
                }
            ),
        ),
        (
            "search_knowledge",
            json.dumps(
                {
                    "query": "",
                    "knowledge_base_id": 1,
                }
            ),
        ),
    ]

    for tool_name, raw_arguments in cases:
        print(f"\n工具：{tool_name}")
        print(f"参数：{raw_arguments}")

        result = run_tool(tool_name, raw_arguments)

        print("结果：")
        print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
