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

from ..schemas.incident import EvidenceItem, IncidentReport

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
