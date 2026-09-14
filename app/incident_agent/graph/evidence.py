"""Server-side verification of report evidence.

``IncidentReport`` is validated by Pydantic, which proves that the *shape* is
right. It cannot prove that ``document_id`` / ``version_id`` / ``chunk_index``
point at something the retrieval tool actually returned. This module closes that
gap.

Two deliberate design decisions:

1. **The server stamps the reference metadata, the model does not.** Asking a
   language model to reproduce DevAtlas identifiers invites fabrication, and a
   model that simply omits them would make every citation unverifiable. So the
   model only has to describe what it found; the real
   ``document_id`` / ``version_id`` / ``version_number`` / ``chunk_index`` /
   ``filename`` are filled in from the run's own observations.
2. **Verification is by content overlap, not by identifier equality.** An
   evidence item is accepted when its ``detail`` can be traced to the text of a
   source this run really retrieved; otherwise it is dropped.

Policy for unverifiable items: drop only those, keep the rest, force
``confidence`` to ``low`` and record an ``UNVERIFIED_EVIDENCE`` step. A single
hallucinated citation must not destroy a run that also produced real evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from ..schemas.incident import (
    DegradedKnowledgeBaseSource,
    DegradedLogSignal,
    DegradedSummary,
    EvidenceItem,
    IncidentReport,
)

EVIDENCE_KNOWLEDGE_BASE = "knowledge_base"
EVIDENCE_FAULT_LOG = "fault_log"
EVIDENCE_SERVICE_STATUS = "service_status"

SEARCH_KNOWLEDGE_TOOL = "search_knowledge"
ANALYZE_LOG_TOOL = "analyze_log"
GET_SERVICE_STATUS_TOOL = "get_service_status"

# Untrusted evidence text is echoed back for diagnosis, so keep it tiny.
UNVERIFIED_DETAIL_LIMIT = 200

# How much of the evidence detail must be traceable to a retrieved source.
CONTENT_OVERLAP_THRESHOLD = 0.6

_WHITESPACE = re.compile(r"\s+")
_TOKEN = re.compile(r"[A-Za-z0-9_.:/\-]{2,}|[\u4e00-\u9fff]{2,}")


@dataclass(frozen=True)
class KnowledgeBaseSource:
    """One knowledge-base source that really came back from DevAtlas."""

    document_id: int | None = None
    version_id: int | None = None
    version_number: int | None = None
    chunk_index: int | None = None
    filename: str | None = None
    content: str | None = None

    def reference(self) -> dict[str, Any]:
        """The reference metadata the server stamps onto verified evidence.

        Keys must exist on ``EvidenceItem``: ``model_copy(update=...)`` silently
        ignores unknown keys, so a typo here would drop the reference without any
        error. ``_assert_reference_keys_are_known()`` guards that.
        """

        reference = {
            "document_id": self.document_id,
            "version_id": self.version_id,
            "version_number": self.version_number,
            "chunk_index": self.chunk_index,
            "filename": self.filename,
        }
        unknown = set(reference) - set(EvidenceItem.model_fields)
        if unknown:
            raise ValueError(f"证据引用字段不存在：{sorted(unknown)}")
        return reference


@dataclass(frozen=True)
class AllowedSources:
    """Everything the current run actually observed, by evidence source."""

    knowledge_bases: tuple[KnowledgeBaseSource, ...] = ()
    fault_log: bool = False
    service_status: bool = False


@dataclass(frozen=True)
class VerificationDecision:
    """Outcome of verifying one report against one run's observations."""

    report: IncidentReport
    verified_count: int
    unverified: tuple[dict[str, Any], ...] = ()

    @property
    def has_unverified(self) -> bool:
        return bool(self.unverified)

    @property
    def evidence_dropped(self) -> bool:
        return self.has_unverified and not self.report.evidence


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _truncate(text: str) -> str:
    if len(text) <= UNVERIFIED_DETAIL_LIMIT:
        return text
    return f"{text[:UNVERIFIED_DETAIL_LIMIT]}…"


def _normalize(text: str) -> str:
    return _WHITESPACE.sub("", text).lower()


def _tokens(text: str) -> set[str]:
    return {match.group(0).lower() for match in _TOKEN.finditer(text)}


def _overlap_ratio(detail: str, content: str) -> float:
    """Score how much of ``detail`` can be traced to ``content``.

    Chinese text has no word boundaries, so a character containment check runs
    first; token overlap is the fallback for Latin text.
    """

    if not detail or not content:
        return 0.0

    normalized_detail = _normalize(detail)
    normalized_content = _normalize(content)
    if not normalized_detail or not normalized_content:
        return 0.0

    if normalized_detail in normalized_content:
        return 1.0
    if normalized_content in normalized_detail:
        return 1.0

    detail_tokens = _tokens(detail)
    if len(detail_tokens) < 3:
        # Too short to judge by tokens; require a character-level match instead.
        return 0.0
    content_tokens = _tokens(content)
    if not content_tokens:
        return 0.0
    return len(detail_tokens & content_tokens) / len(detail_tokens)


def collect_allowed_sources(observations: Any) -> AllowedSources:
    """Extract the real, tool-produced evidence allow-list from observations.

    Only ``result.ok is True`` observations count, and a log/status tool only
    counts when it actually produced data: a tool that ran but returned nothing
    must not legitimise a claim about it.
    """

    knowledge_bases: list[KnowledgeBaseSource] = []
    fault_log = False
    service_status = False

    if not isinstance(observations, list):
        return AllowedSources()

    for observation in observations:
        if not isinstance(observation, Mapping):
            continue
        result = observation.get("result")
        if not isinstance(result, Mapping) or not result.get("ok"):
            continue

        tool_name = observation.get("tool_name")
        data = result.get("data")
        if not isinstance(data, Mapping):
            continue

        if tool_name == SEARCH_KNOWLEDGE_TOOL:
            sources = data.get("sources")
            if not isinstance(sources, list):
                continue
            for source in sources:
                if not isinstance(source, Mapping):
                    continue
                filename = source.get("filename")
                content = source.get("content")
                knowledge_bases.append(
                    KnowledgeBaseSource(
                        document_id=_as_int(source.get("document_id")),
                        version_id=_as_int(source.get("version_id")),
                        version_number=_as_int(source.get("version_number")),
                        chunk_index=_as_int(source.get("chunk_index")),
                        filename=filename if isinstance(filename, str) else None,
                        content=content if isinstance(content, str) else None,
                    )
                )
        elif tool_name == ANALYZE_LOG_TOOL:
            signals = data.get("signals")
            fault_log = bool(signals) if isinstance(signals, list) else fault_log
        elif tool_name == GET_SERVICE_STATUS_TOOL:
            service_status = bool(data.get("service_name")) or service_status

    return AllowedSources(
        knowledge_bases=tuple(knowledge_bases),
        fault_log=fault_log,
        service_status=service_status,
    )


def _best_knowledge_base_match(
    item: EvidenceItem,
    allowed: AllowedSources,
) -> KnowledgeBaseSource | None:
    """Pick the retrieved source this evidence item most plausibly came from.

    A claimed identifier wins outright when it matches a real source, so a model
    that happens to quote correct metadata is still accepted. Otherwise the
    decision falls back to content overlap.
    """

    claimed_document = item.document_id
    if claimed_document is not None:
        for source in allowed.knowledge_bases:
            if source.document_id != claimed_document:
                continue
            if item.version_id is not None and source.version_id != item.version_id:
                continue
            return source

    best: KnowledgeBaseSource | None = None
    best_score = 0.0
    for source in allowed.knowledge_bases:
        score = _overlap_ratio(item.detail, source.content or "")
        if score > best_score:
            best, best_score = source, score

    if best is not None and best_score >= CONTENT_OVERLAP_THRESHOLD:
        return best
    return None


def _is_verified(item: EvidenceItem, allowed: AllowedSources) -> bool:
    if item.source == EVIDENCE_KNOWLEDGE_BASE:
        return _best_knowledge_base_match(item, allowed) is not None
    if item.source == EVIDENCE_FAULT_LOG:
        return allowed.fault_log
    if item.source == EVIDENCE_SERVICE_STATUS:
        return allowed.service_status
    # Any source added to the schema later must be verified explicitly instead of
    # silently trusted.
    return False


def verify_report_evidence(
    report: IncidentReport,
    observations: Any,
) -> VerificationDecision:
    """Stamp real references onto traceable evidence, drop the rest."""

    allowed = collect_allowed_sources(observations)

    verified: list[EvidenceItem] = []
    unverified: list[dict[str, Any]] = []

    for item in report.evidence:
        if item.source == EVIDENCE_KNOWLEDGE_BASE:
            source = _best_knowledge_base_match(item, allowed)
            if source is not None:
                # Identifiers come from the server, never from the model.
                verified.append(
                    item.model_copy(update=source.reference())
                )
                continue
        elif _is_verified(item, allowed):
            verified.append(item)
            continue

        unverified.append(
            {
                "source": item.source,
                "detail": _truncate(item.detail),
                "document_id": item.document_id,
                "version_id": item.version_id,
                "chunk_index": item.chunk_index,
            }
        )

    if not unverified:
        # Still return the decision report: it carries the server-stamped
        # reference metadata on every verified knowledge-base item.
        return VerificationDecision(
            report=report.model_copy(update={"evidence": verified}),
            verified_count=len(verified),
        )

    return VerificationDecision(
        report=report.model_copy(
            update={
                "evidence": verified,
                "confidence": "low",
                "unverified_evidence": unverified,
            }
        ),
        verified_count=len(verified),
        unverified=tuple(unverified),
    )


# --------------------------------------------------------------------------
# Deterministic degraded summary (P0-3-3)
# --------------------------------------------------------------------------

MAX_LOG_SIGNALS = 10
MAX_MATCHED_TEXT = 120
MAX_KB_SOURCES = 10
MAX_SERVICE_STATUSES = 5

# Rule-based follow-ups, keyed by the normalized error code. These are asset
# *suggestions*, never conclusions, and come from code rather than the model.
ERROR_SUGGESTIONS: dict[str, str] = {
    "RAG_UNAVAILABLE": "确认 DevAtlas 检索服务已启动、网络可达后重试。",
    "RAG_NETWORK_ERROR": "确认 Agent 能访问 DevAtlas 地址，并检查本机网络与代理。",
    "RAG_TIMEOUT": "DevAtlas 检索超时，可在其服务侧查看响应耗时后重试。",
    "RAG_UNAUTHORIZED": "登录状态可能已过期，请重新登录后再试。",
    "RAG_KNOWLEDGE_BASE_NOT_FOUND": "确认知识库 ID 存在且当前账号有权访问。",
    "RAG_INVALID_ARGUMENTS": "检索参数不合法，请检查知识库 ID 与召回数量。",
    "RAG_INVALID_RESPONSE": "DevAtlas 返回结构与约定不一致，需要检查其接口版本。",
    "RAG_HTTP_ERROR": "DevAtlas 返回非预期状态码，请查看其服务日志。",
    "RAG_TOOL_ERROR": "检索工具内部异常，请查看服务端日志中的 run_id。",
    "UNKNOWN_SERVICE": "当前服务状态工具只有内置 mock 服务，请改用已登记的服务名。",
    "INVALID_ARGUMENTS": "工具参数校验失败，通常是模型传参不符合契约，可重试或换一种描述。",
    "INVALID_TOOL_RESULT": "工具返回结构不合法，说明工具实现或外部响应有变更。",
}

GENERIC_SUGGESTION = "请根据上面的失败工具和错误码人工核对，并参考服务端日志中的同一 run_id。"

# Model-side and request-level failures are normalized in ``core/errors.py``.
ERROR_SUGGESTIONS.update(
    {
        "MODEL_TIMEOUT": "本次调用模型超时（可能是模型服务变慢或网络抖动），可在网络恢复后重试，或缩短日志内容。",
        "MODEL_RATE_LIMITED": "模型服务限流，请稍后重试，或降低并发分析数量。",
        "MODEL_UNAVAILABLE": "无法连接模型服务，请检查网络、代理，以及 INCIDENT_AGENT_BASE_URL 是否可达。",
        "MODEL_AUTH_ERROR": "模型鉴权失败，请检查 DEEPSEEK_API_KEY 是否有效且未被撤销。",
        "MODEL_INVALID_REQUEST": "模型拒绝了本次参数（常见于上下文过长），可缩短日志后重试。",
        "MODEL_ERROR": "模型调用返回异常状态，请稍后重试并查看服务端日志中的同一 run_id。",
        "REQUEST_TIMEOUT": "本次分析超过了请求时间预算，请缩短日志或提高 INCIDENT_REQUEST_TIMEOUT_SECONDS 后重试。",
        "AGENT_INTERNAL_ERROR": "Agent 内部执行异常，请查看服务端日志中的同一 run_id 定位具体节点。",
    }
)


def _normalized_error_code(value: Any) -> str:
    return str(value).strip().upper() if value else ""


def _suggestion_for(error_code: str) -> str:
    return ERROR_SUGGESTIONS.get(error_code, GENERIC_SUGGESTION)


def extract_error_codes(text: str | None) -> list[str]:
    """Pull known error codes out of a message, e.g. ``...（MODEL_TIMEOUT）``.

    Model and request failures happen before any observation exists, so the code
    is not in ``observations``; it travels in the error text instead. Only codes
    present in :data:`ERROR_SUGGESTIONS` are recognized, so arbitrary text
    (a JSON validation message, a stack frame) cannot produce a false match.
    """

    if not text:
        return []
    normalized = text.upper()
    return [code for code in ERROR_SUGGESTIONS if code in normalized]


def build_degraded_summary(
    observations: Any,
    *,
    status: str,
    error: str | None,
    error_code: str | None = None,
) -> DegradedSummary:
    """Build a model-free summary of what a failed run actually established.

    Everything here is derived from recorded observations, so a degraded run
    still reports the log signals and real knowledge-base sources it did obtain
    instead of collapsing into a single error string. ``error_code`` covers the
    case where the failure happened before any observation existed.
    """

    failed_tools: list[str] = []
    successful_tools: list[str] = []
    error_codes: list[str] = []
    log_signals: list[DegradedLogSignal] = []
    knowledge_base_sources: list[DegradedKnowledgeBaseSource] = []
    service_statuses: list[str] = []

    # 失败发生得比任何工具观察都早时（模型超时、请求预算耗尽），错误码只能
    # 从参数或错误文案里取，否则只会给出通用建议。
    explicit_code = _normalized_error_code(error_code)
    if explicit_code:
        error_codes.append(explicit_code)
    else:
        error_codes.extend(extract_error_codes(error))

    items = observations if isinstance(observations, list) else []

    for observation in items:
        if not isinstance(observation, Mapping):
            continue
        raw_tool_name = observation.get("tool_name")
        if not isinstance(raw_tool_name, str) or not raw_tool_name:
            # Not a usable record; do not invent a tool name for it.
            continue
        tool_name = raw_tool_name
        result = observation.get("result")
        if not isinstance(result, Mapping):
            failed_tools.append(tool_name)
            continue

        if not result.get("ok"):
            failed_tools.append(tool_name)
            code = _normalized_error_code(result.get("error_code"))
            if code:
                error_codes.append(code)
            continue

        successful_tools.append(tool_name)
        data = result.get("data")
        if not isinstance(data, Mapping):
            continue

        if tool_name == ANALYZE_LOG_TOOL:
            signals = data.get("signals")
            if isinstance(signals, list):
                for signal in signals:
                    if len(log_signals) >= MAX_LOG_SIGNALS:
                        break
                    if not isinstance(signal, Mapping):
                        continue
                    matched = signal.get("matched_text") or signal.get("value") or ""
                    log_signals.append(
                        DegradedLogSignal(
                            type=str(signal.get("type") or "unknown"),
                            matched_text=_truncate(str(matched)),
                            line_number=_as_int(signal.get("line_number")),
                        )
                    )

        elif tool_name == SEARCH_KNOWLEDGE_TOOL:
            sources = data.get("sources")
            if isinstance(sources, list):
                for source in sources:
                    if len(knowledge_base_sources) >= MAX_KB_SOURCES:
                        break
                    if not isinstance(source, Mapping):
                        continue
                    filename = source.get("filename")
                    knowledge_base_sources.append(
                        DegradedKnowledgeBaseSource(
                            document_id=_as_int(source.get("document_id")),
                            version_id=_as_int(source.get("version_id")),
                            version_number=_as_int(source.get("version_number")),
                            chunk_index=_as_int(source.get("chunk_index")),
                            filename=filename if isinstance(filename, str) else None,
                        )
                    )

        elif tool_name == GET_SERVICE_STATUS_TOOL:
            service_name = data.get("service_name")
            status_value = data.get("status")
            if isinstance(service_name, str) and len(service_statuses) < MAX_SERVICE_STATUSES:
                label = service_name
                if isinstance(status_value, str):
                    label = f"{service_name}：{status_value}"
                service_statuses.append(label)

    # Deduplicate while keeping the first-seen order.
    seen_codes: set[str] = set()
    suggestions: list[str] = []
    for code in error_codes:
        if code in seen_codes:
            continue
        seen_codes.add(code)
        suggestions.append(_suggestion_for(code))
    if not suggestions:
        suggestions.append(GENERIC_SUGGESTION)

    text = _compose_summary_text(
        status=status,
        error=error,
        failed_tools=failed_tools,
        successful_tools=successful_tools,
        error_codes=list(dict.fromkeys(error_codes)),
        log_signals=log_signals,
        knowledge_base_sources=knowledge_base_sources,
        service_statuses=service_statuses,
    )

    return DegradedSummary(
        reason=status,
        text=text,
        failed_tools=list(dict.fromkeys(failed_tools)),
        successful_tools=list(dict.fromkeys(successful_tools)),
        log_signals=log_signals,
        knowledge_base_sources=knowledge_base_sources,
        service_statuses=service_statuses,
        suggestions=suggestions,
    )


def _compose_summary_text(
    *,
    status: str,
    error: str | None,
    failed_tools: list[str],
    successful_tools: list[str],
    error_codes: list[str],
    log_signals: list[DegradedLogSignal],
    knowledge_base_sources: list[DegradedKnowledgeBaseSource],
    service_statuses: list[str],
) -> str:
    """Human-readable Chinese text assembled only from recorded facts."""

    lines: list[str] = []
    lead = f"本次分析未生成可核实的报告（状态：{status}）。"
    if error:
        lead += f"原因：{error}"
    lines.append(lead)

    if failed_tools:
        detail = "、".join(dict.fromkeys(failed_tools))
        if error_codes:
            detail += f"（错误码：{'、'.join(error_codes)}）"
        lines.append(f"失败工具：{detail}")

    if successful_tools:
        lines.append(f"已成功执行的工具：{'、'.join(dict.fromkeys(successful_tools))}")

    if log_signals:
        rendered = "、".join(
            f"{signal.type}(第 {signal.line_number} 行)" if signal.line_number
            else signal.type
            for signal in log_signals
        )
        lines.append(f"已命中的日志信号：{rendered}")

    if knowledge_base_sources:
        rendered = "、".join(
            f"{source.filename or '未命名文档'} chunk {source.chunk_index}"
            if source.chunk_index is not None
            else (source.filename or "未命名文档")
            for source in knowledge_base_sources
        )
        lines.append(f"已检索到的知识库来源：{rendered}")

    if service_statuses:
        lines.append(f"已查询到的服务状态：{'、'.join(service_statuses)}")

    if not (
        failed_tools
        or successful_tools
        or log_signals
        or knowledge_base_sources
        or service_statuses
    ):
        lines.append("本次运行没有产生任何可用的工具观察结果。")

    return "\n".join(lines)

