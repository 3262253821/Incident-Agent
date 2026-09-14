"""Unit tests for the evidence allow-list and report verification (P0-3-2).

Covers the two halves of the feature:

- ``collect_allowed_sources``: what counts as real evidence from this run;
- ``verify_report_evidence``: stamp real references onto traceable citations and
  drop the ones that cannot be traced.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from app.incident_agent.graph.evidence import (
    CONTENT_OVERLAP_THRESHOLD,
    UNVERIFIED_DETAIL_LIMIT,
    _overlap_ratio,
    collect_allowed_sources,
    verify_report_evidence,
)
from app.incident_agent.schemas.incident import IncidentReport

KB_CONTENT = "订单服务返回 502 可能与数据库连接超时有关，建议检查 MySQL、连接池和网络连通性。"


def report_with(evidence: list[dict], *, confidence: str = "high") -> IncidentReport:
    return IncidentReport.model_validate(
        {
            "summary": "订单服务可能因数据库连接超时返回 502。",
            "category": "database",
            "evidence": evidence,
            "possible_causes": ["数据库连接超时"],
            "troubleshooting_steps": ["检查 MySQL 可用性"],
            "references": [],
            "confidence": confidence,
        }
    )


def search_observation(
    *,
    document_id: int = 10,
    version_id: int = 21,
    chunk_index: int = 2,
    filename: str = "订单服务故障排查手册.md",
    content: str = KB_CONTENT,
    ok: bool = True,
    tool_name: str = "search_knowledge",
) -> dict:
    return {
        "iteration": 1,
        "tool_name": tool_name,
        "tool_call_id": "call-search",
        "result": {
            "ok": ok,
            "data": {
                "question": "订单服务 502",
                "context": content,
                "sources": [
                    {
                        "document_id": document_id,
                        "version_id": version_id,
                        "version_number": 2,
                        "chunk_index": chunk_index,
                        "filename": filename,
                        "content": content,
                        "distance": 0.25,
                        "page_number": None,
                    }
                ],
            },
            "error_code": None,
            "error": None,
        },
    }


def log_observation(*, signals: list | None = None, ok: bool = True) -> dict:
    return {
        "iteration": 1,
        "tool_name": "analyze_log",
        "tool_call_id": "call-log",
        "result": {
            "ok": ok,
            "data": {
                "signals": signals if signals is not None else [{"type": "http_502"}],
                "signal_count": len(signals) if signals is not None else 1,
            },
            "error_code": None,
            "error": None,
        },
    }


def status_observation(*, service_name: str | None = "order-service", ok: bool = True) -> dict:
    return {
        "iteration": 1,
        "tool_name": "get_service_status",
        "tool_call_id": "call-status",
        "result": {
            "ok": ok,
            "data": {"service_name": service_name} if service_name else {},
            "error_code": None,
            "error": None,
        },
    }


# --------------------------------------------------------------------------
# collect_allowed_sources
# --------------------------------------------------------------------------


def test_allowed_sources_collect_knowledge_base_references():
    allowed = collect_allowed_sources([search_observation()])

    assert len(allowed.knowledge_bases) == 1
    source = allowed.knowledge_bases[0]
    assert source.document_id == 10
    assert source.version_id == 21
    assert source.chunk_index == 2
    assert source.filename == "订单服务故障排查手册.md"
    assert source.content == KB_CONTENT


def test_failed_tool_observations_contribute_no_allowed_sources():
    allowed = collect_allowed_sources(
        [
            search_observation(ok=False),
            log_observation(ok=False),
            status_observation(ok=False),
        ]
    )

    assert allowed.knowledge_bases == ()
    assert allowed.fault_log is False
    assert allowed.service_status is False


def test_log_evidence_needs_signals_not_just_a_successful_call():
    empty = collect_allowed_sources([log_observation(signals=[])])
    found = collect_allowed_sources([log_observation(signals=[{"type": "timeout"}])])

    assert empty.fault_log is False
    assert found.fault_log is True


def test_status_evidence_needs_a_resolved_service():
    assert collect_allowed_sources([status_observation(service_name=None)]).service_status is False
    assert collect_allowed_sources([status_observation()]).service_status is True


def test_malformed_observations_do_not_crash_collection():
    allowed = collect_allowed_sources(
        [None, "nope", {"result": "not-a-mapping"}, {"result": {"ok": True}}]
    )

    assert allowed.knowledge_bases == ()
    assert allowed.fault_log is False
    assert allowed.service_status is False


def test_collect_allowed_sources_tolerates_non_list_input():
    assert collect_allowed_sources(None).knowledge_bases == ()
    assert collect_allowed_sources({"observations": []}).fault_log is False


# --------------------------------------------------------------------------
# overlap scoring
# --------------------------------------------------------------------------


def test_overlap_ratio_matches_containment_in_both_directions():
    assert _overlap_ratio(KB_CONTENT, KB_CONTENT) == 1.0
    assert _overlap_ratio(KB_CONTENT[:20], KB_CONTENT) == 1.0
    assert _overlap_ratio(f"结论：{KB_CONTENT}", KB_CONTENT) == 1.0


def test_overlap_ratio_rejects_unrelated_text():
    assert _overlap_ratio("磁盘写满了，建议扩容。", KB_CONTENT) == 0.0
    assert _overlap_ratio("", KB_CONTENT) == 0.0
    assert _overlap_ratio(KB_CONTENT, "") == 0.0


def test_overlap_threshold_is_not_a_tautology():
    assert 0.0 < CONTENT_OVERLAP_THRESHOLD <= 1.0


# --------------------------------------------------------------------------
# verify_report_evidence
# --------------------------------------------------------------------------


def test_traceable_evidence_is_stamped_with_server_side_references():
    report = report_with([{"source": "knowledge_base", "detail": KB_CONTENT}])

    decision = verify_report_evidence(report, [search_observation()])

    assert decision.has_unverified is False
    item = decision.report.evidence[0]
    assert item.document_id == 10
    assert item.version_id == 21
    assert item.version_number == 2
    assert item.chunk_index == 2
    assert item.filename == "订单服务故障排查手册.md"
    assert decision.report.confidence == "high"


def test_server_reference_overrides_a_wrong_identifier_from_the_model():
    """A model that guesses the wrong chunk must not get its guess published."""

    report = report_with(
        [
            {
                "source": "knowledge_base",
                "detail": KB_CONTENT,
                "document_id": 10,
                "version_id": 21,
                "chunk_index": 99,
            }
        ]
    )

    decision = verify_report_evidence(report, [search_observation()])

    assert decision.has_unverified is False
    assert decision.report.evidence[0].chunk_index == 2


def test_claimed_document_id_wins_when_it_matches_a_real_source():
    report = report_with(
        [
            {
                "source": "knowledge_base",
                "detail": "内容被模型改写过，与原文并不完全一致。",
                "document_id": 10,
            }
        ]
    )

    decision = verify_report_evidence(report, [search_observation()])

    assert decision.has_unverified is False
    assert decision.report.evidence[0].version_id == 21


def test_claimed_document_id_that_does_not_exist_is_dropped():
    report = report_with(
        [
            {
                "source": "knowledge_base",
                "detail": "凭空捏造的结论。",
                "document_id": 999,
            }
        ]
    )

    decision = verify_report_evidence(report, [search_observation()])

    assert decision.has_unverified is True
    assert decision.report.evidence == []
    assert decision.unverified[0]["document_id"] == 999


def test_claimed_version_that_does_not_match_is_dropped():
    report = report_with(
        [
            {
                "source": "knowledge_base",
                "detail": "内容被模型改写过。",
                "document_id": 10,
                "version_id": 999,
            }
        ]
    )

    decision = verify_report_evidence(report, [search_observation()])

    assert decision.has_unverified is True
    assert decision.report.evidence == []


def test_knowledge_base_claim_without_any_retrieval_is_dropped():
    report = report_with([{"source": "knowledge_base", "detail": KB_CONTENT}])

    decision = verify_report_evidence(report, [log_observation()])

    assert decision.has_unverified is True
    assert decision.report.evidence == []
    assert decision.report.confidence == "low"


def test_only_the_fabricated_item_is_removed_and_the_rest_survives():
    report = report_with(
        [
            {
                "source": "knowledge_base",
                "detail": "编造的结论，与检索内容无关。",
                "document_id": 999,
            },
            {"source": "knowledge_base", "detail": KB_CONTENT},
            {"source": "fault_log", "detail": "日志命中 502 与 timeout。"},
        ]
    )

    decision = verify_report_evidence(
        report,
        [search_observation(), log_observation()],
    )

    assert decision.has_unverified is True
    assert len(decision.report.evidence) == 2
    assert decision.report.evidence[0].document_id == 10
    assert decision.report.evidence[1].source == "fault_log"
    assert len(decision.unverified) == 1
    assert decision.unverified[0]["document_id"] == 999
    assert decision.report.confidence == "low"
    assert decision.evidence_dropped is False


def test_fault_log_claim_without_the_log_tool_is_dropped():
    report = report_with([{"source": "fault_log", "detail": "日志命中 502。"}])

    decision = verify_report_evidence(report, [search_observation()])

    assert decision.has_unverified is True
    assert decision.report.evidence == []


def test_service_status_claim_without_the_status_tool_is_dropped():
    report = report_with([{"source": "service_status", "detail": "服务处于降级状态。"}])

    decision = verify_report_evidence(report, [log_observation()])

    assert decision.has_unverified is True
    assert decision.report.evidence == []


def test_unverified_detail_is_truncated_before_being_echoed_back():
    report = report_with(
        [{"source": "knowledge_base", "detail": "编造" * 500, "document_id": 999}]
    )

    decision = verify_report_evidence(report, [search_observation()])

    assert len(decision.unverified[0]["detail"]) <= UNVERIFIED_DETAIL_LIMIT + 1


def test_everything_verified_means_no_unverified_field_and_no_confidence_change():
    report = report_with(
        [
            {"source": "knowledge_base", "detail": KB_CONTENT},
            {"source": "fault_log", "detail": "日志命中 502。"},
        ],
        confidence="medium",
    )

    decision = verify_report_evidence(
        report,
        [search_observation(), log_observation()],
    )

    assert decision.unverified == ()
    assert decision.report.confidence == "medium"
    assert decision.report.unverified_evidence == []


@pytest.mark.parametrize("confidence", ["low", "medium", "high"])
def test_verification_never_raises_confidence(confidence: str):
    report = report_with(
        [{"source": "knowledge_base", "detail": "编造", "document_id": 999}],
        confidence=confidence,
    )

    decision = verify_report_evidence(report, [search_observation()])

    assert decision.report.confidence == "low"
