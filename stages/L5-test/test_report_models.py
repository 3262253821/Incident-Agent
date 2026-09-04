import json
import sys
from pathlib import Path


L3_TOOLS_DIR = Path(__file__).resolve().parents[1] / "L3-tools"

if str(L3_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(L3_TOOLS_DIR))

from report_models import IncidentReport, validate_report


def valid_report_data():
    return {
        "summary": "订单服务因数据库连接超时返回 502。",
        "category": "database",
        "evidence": [
            {
                "source": "fault_log",
                "detail": "日志出现 502 和 MySQL connection timeout",
            }
        ],
        "possible_causes": [
            "数据库连接超时",
            "连接池资源耗尽",
        ],
        "troubleshooting_steps": [
            "检查 MySQL 状态",
            "检查连接池状态",
        ],
        "references": [
            "订单服务故障排查手册.md#version-3#chunk-2",
        ],
        "confidence": "medium",
    }


def test_valid_report():
    raw_report = json.dumps(
        valid_report_data(),
        ensure_ascii=False,
    )

    report = validate_report(raw_report)

    assert isinstance(report, IncidentReport)
    assert report.category == "database"
    assert report.confidence == "medium"


def test_invalid_category():
    data = valid_report_data()
    data["category"] = "cache"

    report = validate_report(
        json.dumps(data, ensure_ascii=False)
    )

    assert report is None


def test_string_evidence_is_normalized():
    data = valid_report_data()
    data["evidence"] = ["日志命中 502 和 timeout"]

    report = validate_report(
        json.dumps(data, ensure_ascii=False)
    )

    assert report is not None
    assert report.evidence[0].source == "model_summary"
    assert report.evidence[0].detail == "日志命中 502 和 timeout"