"""Request-level deadline used for cooperative timeout checks.

The per-call HTTP timeout in ``services/llm.py`` bounds one model request. This
module bounds the whole analysis: the graph asks whether its budget is still
available before each expensive step, so a slow model plus several tool rounds
cannot exceed the request budget.

The check is intentionally cooperative rather than a hard thread kill. Killing a
worker thread cannot be done safely in Python, and abandoning the graph would
leave writes in flight. Raising between steps keeps the failure deterministic and
testable, and lands in the same controlled degradation path as any other error.
"""

from __future__ import annotations

import time

from ..core.errors import REQUEST_TIMEOUT

MESSAGE = "本次分析已超过请求时间上限，已停止后续模型调用"


class RequestTimeoutError(Exception):
    """Raised when the request budget is exhausted."""

    def __init__(self, timeout_seconds: float):
        super().__init__(MESSAGE)
        self.error_code = REQUEST_TIMEOUT
        self.message = MESSAGE
        self.timeout_seconds = timeout_seconds


class RequestDeadline:
    """A monotonic budget shared by every step of one analysis request."""

    def __init__(
        self,
        timeout_seconds: float | None,
        *,
        started_at: float | None = None,
    ):
        self.timeout_seconds = timeout_seconds
        # ``started_at`` exists so an exhausted budget can be constructed
        # deterministically in tests instead of relying on real elapsed time.
        self._started_at = time.monotonic() if started_at is None else started_at

    @classmethod
    def expired(cls, timeout_seconds: float = 90.0) -> "RequestDeadline":
        """Build a deadline whose budget is already used up."""

        return cls(timeout_seconds, started_at=time.monotonic() - timeout_seconds - 1.0)

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self._started_at

    @property
    def remaining_seconds(self) -> float | None:
        if self.timeout_seconds is None:
            return None
        return self.timeout_seconds - self.elapsed_seconds

    @property
    def enabled(self) -> bool:
        return self.timeout_seconds is not None and self.timeout_seconds > 0

    def check(self) -> None:
        """Raise :class:`RequestTimeoutError` once the budget is gone."""

        if not self.enabled:
            return
        if self.elapsed_seconds >= self.timeout_seconds:  # type: ignore[operator]
            raise RequestTimeoutError(self.timeout_seconds)  # type: ignore[arg-type]
