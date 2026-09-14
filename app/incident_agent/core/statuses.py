"""Canonical run status values shared by the graph and the persistence layer.

Keeping these in one place stops the status vocabulary from drifting between
``graph/nodes.py``, ``services/incident.py``, ``services/storage.py`` and the
frontend display map.

Lifecycle:

```text
running                     run row created, graph not finished
completed                   report validated and backed by tool evidence
insufficient_evidence       report validated but no successful tool observation
degraded                    a tool failed, or the model/外部依赖不可用
report_validation_failed    the report node could not produce a valid report
max_iterations              the model-request budget was exhausted

tool_failed                 internal only; mapped to ``degraded`` before the
                            API response is built
```
"""

from __future__ import annotations


class RunStatus:
    """Run lifecycle statuses exposed by the API."""

    RUNNING = "running"
    COMPLETED = "completed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    DEGRADED = "degraded"
    REPORT_VALIDATION_FAILED = "report_validation_failed"
    MAX_ITERATIONS = "max_iterations"


class InternalRunStatus:
    """Statuses that only exist inside the graph."""

    TOOL_FAILED = "tool_failed"


class StepStatus:
    """Status values used by individual execution steps."""

    SUCCESS = "success"
    FAILED = "failed"


class StepErrorCode:
    """Error codes recorded on steps for diagnosis."""

    NO_TOOL_EVIDENCE = "NO_TOOL_EVIDENCE"
    UNVERIFIED_EVIDENCE = "UNVERIFIED_EVIDENCE"
    INVALID_JSON = "INVALID_JSON"
    INVALID_REPORT = "INVALID_REPORT"
