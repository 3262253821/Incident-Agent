from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)


class EvidenceItem(BaseModel):
    """一条带来源的证据。"""

    model_config = ConfigDict(extra="allow")

    source: str
    detail: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_string_evidence(cls, value: Any) -> Any:
        """兼容模型返回的字符串证据。"""

        if isinstance(value, str):
            return {
                "source": "model_summary",
                "detail": value,
            }

        return value


class IncidentReport(BaseModel):
    """Incident Agent 的最终故障报告。"""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)

    category: Literal[
        "database",
        "network",
        "application",
        "dependency",
        "unknown",
    ]

    evidence: list[EvidenceItem] = Field(min_length=1)

    possible_causes: list[str] = Field(min_length=1)

    troubleshooting_steps: list[str] = Field(min_length=1)

    references: list[str] = Field(default_factory=list)

    confidence: Literal["low", "medium", "high"]


def validate_report(raw_report: str) -> IncidentReport | None:
    """将 JSON 字符串解析并校验为 IncidentReport。"""

    try:
        data = json.loads(raw_report)
        return IncidentReport.model_validate(data)
    except json.JSONDecodeError:
        print("错误：报告不是合法 JSON")
    except ValidationError as exc:
        print("错误：报告字段校验失败")
        print(json.dumps(exc.errors(), ensure_ascii=False, indent=2))

    return None


def main() -> None:
    valid_report = json.dumps(
        {
            "summary": "订单服务因数据库连接超时出现 502。",
            "category": "database",
            "evidence": [
                {
                    "source": "fault_log",
                    "detail": "日志出现 502 和 MySQL connection timeout",
                },
            ],
            "possible_causes": [
                "数据库不可用",
                "连接池无法获取连接",
            ],
            "troubleshooting_steps": [
                "检查 MySQL 实例状态",
                "检查订单服务连接池状态",
            ],
            "references": [
                "订单服务故障排查手册.md#version-3#chunk-2",
            ],
            "confidence": "medium",
        },
        ensure_ascii=False,
    )

    invalid_report = json.dumps(
        {
            "summary": "",
            "evidence": [],
            "possible_causes": [],
            "troubleshooting_steps": [],
            "references": [],
            "category": "cache",
            "confidence": "medium",
            "extra_field": "不允许出现的字段",
        },
        ensure_ascii=False,
    )

    print("===== 合法报告 =====")
    report = validate_report(valid_report)

    if report is not None:
        print(json.dumps(report.model_dump(), ensure_ascii=False, indent=2))

    print("\n===== 非法报告 =====")
    validate_report(invalid_report)


if __name__ == "__main__":
    main()
