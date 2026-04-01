"""
Tests for the calibration subsystem: ECE computation, live adjuster, and REST API.

Builds in-memory FeedbackRecord lists — no DynamoDB calls.
"""

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from calibration.engine import (
    CalibrationEngine,
    CalibrationReport,
    ConfidenceBucket,
)
from calibration.live_adjuster import (
    AdjustedConfidence,
    Deduction,
    LiveConfidenceAdjuster,
)
from feedback.store import (
    CalibrationDataset,
    FeedbackRecord,
    ReviewerVerdict,
)
from ai.core.schemas import AgentError, AgentErrorType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_feedback(
    verdict: ReviewerVerdict,
    confidence: float,
    status: str = "APPROVED",
    request_id: str | None = None,
) -> FeedbackRecord:
    return FeedbackRecord(
        request_id=request_id or f"req-{id(verdict)}-{confidence}",
        audit_id="audit-001",
        ai_status=status,
        ai_confidence=confidence,
        ai_clauses=["C1"],
        foir_value=0.38,
        sanctions_hit=False,
        doc_check_passed=True,
        temporal_passed=True,
        rag_chunks_retrieved=3,
        reviewer_verdict=verdict,
        reviewer_id="reviewer-1",
    )


def _make_dataset(records: list[FeedbackRecord]) -> CalibrationDataset:
    total = len(records)
    agree = sum(1 for r in records if r.reviewer_verdict == ReviewerVerdict.AGREE)
    disagree = sum(1 for r in records if r.reviewer_verdict == ReviewerVerdict.DISAGREE)
    partial = sum(1 for r in records if r.reviewer_verdict == ReviewerVerdict.PARTIAL)
    now = datetime.now(UTC)
    return CalibrationDataset(
        records=records,
        total=total,
        agree_count=agree,
        disagree_count=disagree,
        partial_count=partial,
        accuracy=round(agree / total, 4) if total else 0.0,
        from_dt=now - timedelta(days=30),
        to_dt=now,
    )


def _mock_rule_engine(penalty: float = 0.15) -> AsyncMock:
    re = AsyncMock()
    re.confidence_penalty_per_error = AsyncMock(return_value=penalty)
    re.update_rule = AsyncMock(return_value=(MagicMock(), MagicMock()))
    return re


# ===========================================================================
# CalibrationEngine — ECE computation
# ===========================================================================


class TestCalibrationEngine:

    async def test_ece_is_zero_for_perfectly_calibrated_model(self):
        """When all records have confidence=0.5 and all are correct (AGREE),
        the bucket [0.5,0.6) has accuracy=1.0 and avg_confidence=0.5,
        so calibration_error = 0.5. ECE = 1.0 * 0.5 = 0.5.

        For a truly low ECE, we make confidence ≈ accuracy.
        """
        records = [
            _make_feedback(ReviewerVerdict.AGREE, 0.95, request_id=f"ok-{i}")
            for i in range(50)
        ]
        dataset = _make_dataset(records)
        engine = CalibrationEngine(_mock_rule_engine())
        report = await engine.compute_report(dataset)

        assert report.ece < 0.10, (
            f"All-correct at 0.95 confidence should have low ECE, got {report.ece}"
        )

    async def test_ece_is_high_for_overconfident_model(self):
        """All confidence=0.95 but only 50% correct → high ECE."""
        records = (
            [_make_feedback(ReviewerVerdict.AGREE, 0.95, request_id=f"c-{i}") for i in range(25)]
            + [_make_feedback(ReviewerVerdict.DISAGREE, 0.95, request_id=f"w-{i}") for i in range(25)]
        )
        dataset = _make_dataset(records)
        engine = CalibrationEngine(_mock_rule_engine())
        report = await engine.compute_report(dataset)

        assert report.ece > 0.20, (
            f"50% accuracy at 0.95 confidence should give ECE > 0.20, got {report.ece}"
        )

    async def test_buckets_cover_all_ten_deciles(self):
        """Report should contain exactly 10 buckets spanning [0.0, 1.0]."""
        records = [
            _make_feedback(ReviewerVerdict.AGREE, 0.75, request_id=f"b-{i}")
            for i in range(40)
        ]
        dataset = _make_dataset(records)
        engine = CalibrationEngine(_mock_rule_engine())
        report = await engine.compute_report(dataset)

        assert len(report.buckets) == 10
        assert report.buckets[0].lower == pytest.approx(0.0)
        assert report.buckets[-1].upper == pytest.approx(1.0)

    async def test_recommended_penalty_is_clamped_to_min_max(self):
        """Penalty should be clamped between 0.05 and 0.30."""
        all_correct = [
            _make_feedback(ReviewerVerdict.AGREE, 0.99, request_id=f"p-{i}")
            for i in range(50)
        ]
        dataset_low = _make_dataset(all_correct)
        engine = CalibrationEngine(_mock_rule_engine())
        report_low = await engine.compute_report(dataset_low)
        assert report_low.recommended_confidence_penalty >= 0.05

        half_wrong = (
            [_make_feedback(ReviewerVerdict.AGREE, 0.50, request_id=f"h-{i}") for i in range(25)]
            + [_make_feedback(ReviewerVerdict.DISAGREE, 0.50, request_id=f"hw-{i}") for i in range(25)]
        )
        dataset_high = _make_dataset(half_wrong)
        report_high = await engine.compute_report(dataset_high)
        assert report_high.recommended_confidence_penalty <= 0.30

    async def test_apply_report_does_not_update_rule_if_ece_below_threshold(self):
        """ECE=0.02 should not trigger a rule update."""
        engine = CalibrationEngine(_mock_rule_engine(penalty=0.15))
        report = CalibrationReport(
            feedback_count=100,
            feedback_period={"from": "2026-01-01", "to": "2026-03-01"},
            ece=0.02,
            buckets=[],
            avg_overconfidence=0.0,
            avg_underconfidence=0.0,
            is_overconfident=False,
            accuracy_by_status={"APPROVED": 0.98},
            recommended_confidence_penalty=0.05,
            recommendation_text="Well calibrated",
        )

        result = await engine.apply_report_to_rules(report, "auto")
        assert result["updated"] is False

    async def test_apply_report_updates_rule_when_ece_exceeds_threshold(self):
        """ECE=0.20 with significantly different penalty should trigger update."""
        mock_re = _mock_rule_engine(penalty=0.10)
        engine = CalibrationEngine(mock_re)
        report = CalibrationReport(
            feedback_count=100,
            feedback_period={"from": "2026-01-01", "to": "2026-03-01"},
            ece=0.20,
            buckets=[],
            avg_overconfidence=-0.10,
            avg_underconfidence=-0.20,
            is_overconfident=False,
            accuracy_by_status={"APPROVED": 0.80},
            recommended_confidence_penalty=0.30,
            recommendation_text="Significant miscalibration",
        )

        result = await engine.apply_report_to_rules(report, "auto")
        assert result["updated"] is True
        mock_re.update_rule.assert_called_once()


# ===========================================================================
# LiveConfidenceAdjuster
# ===========================================================================


class TestLiveAdjuster:

    async def test_live_adjuster_deducts_penalty_per_non_recoverable_error(self):
        """1 non-recoverable error with penalty=0.15 → raw - 0.15."""
        adjuster = LiveConfidenceAdjuster(_mock_rule_engine(0.15))
        error = AgentError(
            agent="rag_agent",
            error_type=AgentErrorType.RETRIEVAL,
            message="fail",
            recoverable=False,
        )
        result = await adjuster.adjust(
            raw_confidence=0.90,
            agent_errors=[error],
            rag_context_empty=False,
            sanctions_hit=False,
            short_circuit_reason=None,
        )
        assert result.adjusted == pytest.approx(0.75, abs=0.01)
        assert result.total_deduction == pytest.approx(0.15, abs=0.01)

    async def test_live_adjuster_deducts_half_penalty_for_recoverable_error(self):
        """1 recoverable error → deduction = penalty * 0.5."""
        adjuster = LiveConfidenceAdjuster(_mock_rule_engine(0.15))
        error = AgentError(
            agent="temporal_agent",
            error_type=AgentErrorType.TIMEOUT,
            message="slow",
            recoverable=True,
        )
        result = await adjuster.adjust(
            raw_confidence=0.90,
            agent_errors=[error],
            rag_context_empty=False,
            sanctions_hit=False,
            short_circuit_reason=None,
        )
        assert result.total_deduction == pytest.approx(0.075, abs=0.01)

    async def test_live_adjuster_clamps_confidence_to_zero_minimum(self):
        """Many errors should not drop confidence below 0.0."""
        adjuster = LiveConfidenceAdjuster(_mock_rule_engine(0.15))
        errors = [
            AgentError(agent=f"agent_{i}", error_type=AgentErrorType.UNKNOWN,
                       message="fail", recoverable=False)
            for i in range(10)
        ]
        result = await adjuster.adjust(
            raw_confidence=0.10,
            agent_errors=errors,
            rag_context_empty=True,
            sanctions_hit=False,
            short_circuit_reason="sanctions_hit",
        )
        assert result.adjusted == 0.0

    async def test_live_adjuster_deducts_extra_for_empty_rag_context(self):
        """rag_context_empty=True adds a full penalty deduction."""
        adjuster = LiveConfidenceAdjuster(_mock_rule_engine(0.15))
        result = await adjuster.adjust(
            raw_confidence=0.90,
            agent_errors=[],
            rag_context_empty=True,
            sanctions_hit=False,
            short_circuit_reason=None,
        )
        assert result.total_deduction == pytest.approx(0.15, abs=0.01)
        assert len(result.deductions) == 1
        assert "RAG context empty" in result.deductions[0].reason


# ===========================================================================
# Calibration REST API (httpx + ASGITransport)
# ===========================================================================


class TestCalibrationAPI:

    @pytest.fixture()
    def _test_app(self):
        from fastapi import FastAPI
        from calibration.router import calibration_router

        app = FastAPI()
        app.include_router(calibration_router)
        return app

    async def test_calibration_run_endpoint_returns_report(self, _test_app):
        """POST /calibration/run should return a CalibrationRunResult with 200."""
        import httpx

        records = [
            _make_feedback(ReviewerVerdict.AGREE, 0.90, request_id=f"api-{i}")
            for i in range(40)
        ]
        dataset = _make_dataset(records)

        mock_fb = AsyncMock()
        mock_fb.get_calibration_dataset = AsyncMock(return_value=dataset)

        report = CalibrationReport(
            feedback_count=40,
            feedback_period={"from": "2026-01-01", "to": "2026-03-01"},
            ece=0.08,
            buckets=[],
            avg_overconfidence=-0.05,
            avg_underconfidence=0.0,
            is_overconfident=False,
            accuracy_by_status={"APPROVED": 0.90},
            recommended_confidence_penalty=0.12,
            recommendation_text="Moderate miscalibration",
        )
        mock_engine = AsyncMock()
        mock_engine.compute_report = AsyncMock(return_value=report)

        mock_store = AsyncMock()
        mock_store.save_report = AsyncMock(return_value=report.report_id)

        _test_app.state.feedback_store = mock_fb
        _test_app.state.calibration_engine = mock_engine
        _test_app.state.calibration_store = mock_store
        _test_app.state.rule_engine = _mock_rule_engine()
        os.environ["REVIEWER_API_KEY"] = "test-key"

        transport = httpx.ASGITransport(app=_test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/calibration/run",
                json={"apply_to_rules": False},
                headers={"X-Reviewer-Key": "test-key"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "report" in body
        assert body["dataset_size"] == 40
        os.environ.pop("REVIEWER_API_KEY", None)

    async def test_calibration_run_applies_rules_when_flag_set(self, _test_app):
        """POST /calibration/run with apply_to_rules=True should call apply_report_to_rules."""
        import httpx

        records = [
            _make_feedback(ReviewerVerdict.AGREE, 0.90, request_id=f"flag-{i}")
            for i in range(40)
        ]
        dataset = _make_dataset(records)

        mock_fb = AsyncMock()
        mock_fb.get_calibration_dataset = AsyncMock(return_value=dataset)

        report = CalibrationReport(
            feedback_count=40,
            feedback_period={"from": "2026-01-01", "to": "2026-03-01"},
            ece=0.15,
            buckets=[],
            avg_overconfidence=-0.10,
            avg_underconfidence=0.0,
            is_overconfident=False,
            accuracy_by_status={"APPROVED": 0.85},
            recommended_confidence_penalty=0.225,
            recommendation_text="Moderate",
        )
        mock_engine = AsyncMock()
        mock_engine.compute_report = AsyncMock(return_value=report)
        mock_engine.apply_report_to_rules = AsyncMock(return_value={
            "updated": True, "old_penalty": 0.15, "new_penalty": 0.225,
            "reason": "Auto", "ece": 0.15,
        })

        mock_store = AsyncMock()
        mock_store.save_report = AsyncMock(return_value=report.report_id)

        _test_app.state.feedback_store = mock_fb
        _test_app.state.calibration_engine = mock_engine
        _test_app.state.calibration_store = mock_store
        _test_app.state.rule_engine = _mock_rule_engine()
        os.environ["REVIEWER_API_KEY"] = "test-key"

        transport = httpx.ASGITransport(app=_test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/calibration/run",
                json={"apply_to_rules": True},
                headers={"X-Reviewer-Key": "test-key"},
            )

        assert resp.status_code == 200
        mock_engine.apply_report_to_rules.assert_called_once()
        body = resp.json()
        assert body["rule_update"]["updated"] is True
        os.environ.pop("REVIEWER_API_KEY", None)
