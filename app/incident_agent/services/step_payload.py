"""The public step payload shared by every endpoint that returns a trajectory.

P1-5-2 的背景（实测，不是推测）：``POST /api/v1/incidents/analyze`` 曾经把 Graph
内部的步骤字典**原样**透出，而 ``GET /api/v1/runs/{run_id}`` 返回的是落库后重新
组装的 11 个字段。同一次运行的 5 条步骤在两个接口上的形状差异是：

- analyze 独有：``_started_at``（``time.monotonic()`` 起点，纯内部字段）、``ok``、
  ``attempts``、``tool_call_count``、``unverified_count``；而且每个 action 的字段
  集合都不一样（5 条步骤 4 种形状，字段并集 15 个）；
- detail 独有：``step_index``（持久化时按 1..N 编号）。

后果不只是"类型难看"：``step_index`` 在前端被当作列表 key 使用，analyze 响应里它
永远是 ``undefined``；而前端类型只能写成"两种形状的并集"，`ok`、`step_index` 这类
字段被迫标成可选，漂移就无法被发现（P1-5-2 要做的类型统一因此失去前提）。

现在两个接口都走这里的投影函数：``STEP_PAYLOAD_FIELDS`` 与 ``agent_steps`` 表一一
对应，是步骤轨迹唯一的公开契约。
"""

from __future__ import annotations

from typing import Any

from ..models.agent_run import AgentStep

#: 公开的步骤字段，与 ``agent_steps`` 表的列一一对应，顺序即响应里的键顺序。
STEP_PAYLOAD_FIELDS: tuple[str, ...] = (
    "step_index",
    "iteration",
    "node",
    "action",
    "tool_name",
    "tool_call_id",
    "arguments_summary",
    "result_summary",
    "status",
    "error_code",
    "duration_ms",
)


def step_payload_from_row(step: AgentStep) -> dict[str, Any]:
    """Project a persisted ``AgentStep`` row onto the public contract."""

    return {name: getattr(step, name) for name in STEP_PAYLOAD_FIELDS}


def step_payload_from_state(step: dict[str, Any], *, step_index: int) -> dict[str, Any]:
    """Project one Graph-state step onto the same contract.

    ``step_index`` is 1-based and follows the order of ``state["steps"]`` — exactly
    the numbering ``append_steps`` writes, so the immediate response and a later
    history read agree field for field.

    Graph-internal keys are dropped deliberately: none of them is persisted, and a
    field that exists in only one of the two endpoints is what forced the frontend
    type to be an ambiguous union.
    """

    payload = {name: step.get(name) for name in STEP_PAYLOAD_FIELDS}
    payload["step_index"] = step_index
    return payload
