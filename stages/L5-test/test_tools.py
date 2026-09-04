import json
import sys
from pathlib import Path


# 让测试文件能够导入 L3-tools/tools.py
L3_TOOLS_DIR = Path(__file__).resolve().parents[1] / "L3-tools"

if str(L3_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(L3_TOOLS_DIR))

from tools import run_tool


def test_analyze_log_success():
    result = run_tool(
        "analyze_log",
        json.dumps(
            {
                "log_text": (
                    "gateway returned 502; "
                    "mysql connection timeout"
                )
            }
        ),
    )

    assert result.ok is True
    assert result.data["signal_count"] == 3


def test_get_known_service_status():
    result = run_tool(
        "get_service_status",
        json.dumps(
            {
                "service_name": "user-service",
            }
        ),
    )

    assert result.ok is True
    assert result.data["service_name"] == "user-service"
    assert result.data["status"] == "healthy"
    assert result.data["error_count"] == 0


def test_get_unknown_service_status():
    result = run_tool(
        "get_service_status",
        json.dumps(
            {
                "service_name": "gateway",
            }
        ),
    )

    assert result.ok is False
    assert result.error_code == "UNKNOWN_SERVICE"
    assert "gateway" in result.error


def test_empty_query_is_rejected():
    result = run_tool(
        "search_knowledge",
        json.dumps(
            {
                "query": "",
                "knowledge_base_id": 1,
            }
        ),
    )

    assert result.ok is False
    assert result.error_code == "INVALID_ARGUMENTS"


def test_invalid_json_is_rejected():
    result = run_tool(
        "search_knowledge",
        '{"query": "订单服务 502"',
    )

    assert result.ok is False
    assert result.error_code == "INVALID_JSON"


def test_unknown_tool_is_rejected():
    result = run_tool(
        "not_exists",
        json.dumps({}),
    )

    assert result.ok is False
    assert result.error_code == "UNKNOWN_TOOL"


def test_invalid_knowledge_base_id_is_rejected():
    result = run_tool(
        "search_knowledge",
        json.dumps(
            {
                "query": "订单服务 502",
                "knowledge_base_id": 0,
            }
        ),
    )

    assert result.ok is False
    assert result.error_code == "INVALID_ARGUMENTS"


def test_extra_argument_is_rejected():
    result = run_tool(
        "get_service_status",
        json.dumps(
            {
                "service_name": "order-service",
                "extra": "不允许的参数",
            }
        ),
    )

    assert result.ok is False
    assert result.error_code == "INVALID_ARGUMENTS"