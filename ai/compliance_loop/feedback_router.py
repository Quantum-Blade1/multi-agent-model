"""
Reviewer feedback REST API for the NBFC Compliance AI system.

Collects human verdicts on AI compliance decisions and provides summary
statistics that power the confidence calibration layer.

Authentication
--------------
- **POST** and **calibration-dataset**: require ``X-Reviewer-Key`` header.
- **GET** read endpoints: unauthenticated (internal service assumption).
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ai.audit.models import AuditRecord, OverrideRecord, ReviewerStatus
from ai.audit.store import AuditAlreadyOverriddenError, AuditStore
from ai.compliance_loop.feedback_store import (
    CalibrationDataset,
    FeedbackAlreadyExistsError,
    FeedbackRecord,
    FeedbackStore,
    InsufficientFeedbackError,
    ReviewerVerdict,
)
from ai.observability.logger import get_logger

log = get_logger("ai.compliance_loop.feedback_router")

feedback_router = APIRouter(prefix="/feedback", tags=["feedback"])

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

_REVIEWER_KEY = os.getenv("REVIEWER_API_KEY", "")


def _get_feedback_store(request: Request) -> FeedbackStore:
    store: FeedbackStore | None = getattr(request.app.state, "feedback_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Feedback store not initialised")
    return store


def _get_audit_store(request: Request) -> AuditStore:
    store: AuditStore | None = getattr(request.app.state, "audit_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Audit store not initialised")
    return store


def _require_reviewer_key(
    x_reviewer_key: str | None = Header(default=None),
) -> str:
    expected = os.getenv("REVIEWER_API_KEY", _REVIEWER_KEY)
    if not expected:
        raise HTTPException(
            status_code=503, detail="REVIEWER_API_KEY not configured on server"
        )
    if x_reviewer_key is None or x_reviewer_key != expected:
        raise HTTPException(status_code=403, detail="Invalid or missing reviewer key")
    return x_reviewer_key


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class FeedbackRequest(BaseModel):
    """Body for the POST /feedback endpoint."""

    request_id: str = Field(description="Links to the original compliance request.")
    audit_id: str = Field(description="Links to the AuditRecord.")
    reviewer_verdict: ReviewerVerdict = Field(description="AGREE, DISAGREE, or PARTIAL.")
    reviewer_id: str = Field(description="Authenticated reviewer identifier.")
    actual_status: str | None = Field(
        default=None, description="If DISAGREE: what the correct status should be."
    )
    reviewer_notes: str | None = Field(
        default=None, description="Free-text reviewer comments."
    )


class FeedbackSummary(BaseModel):
    """Aggregate feedback statistics over a time window."""

    total_feedback: int
    accuracy: float
    by_verdict: dict[str, int]
    by_original_ai_status: dict[str, dict[str, int]]
    avg_confidence_when_correct: float
    avg_confidence_when_wrong: float
    calibration_gap: float
    period: dict[str, str]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@feedback_router.post(
    "",
    response_model=FeedbackRecord,
    summary="Submit reviewer feedback on an AI compliance decision",
)
async def submit_feedback(
    body: FeedbackRequest,
    fb_store: FeedbackStore = Depends(_get_feedback_store),
    audit_store: AuditStore = Depends(_get_audit_store),
    _key: str = Depends(_require_reviewer_key),
) -> FeedbackRecord:
    audit_record = await audit_store.get_by_request_id(body.request_id)
    if audit_record is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "audit_not_found", "request_id": body.request_id},
        )

    signals = audit_record.agent_signals

    record = FeedbackRecord(
        request_id=body.request_id,
        audit_id=body.audit_id,
        ai_status=audit_record.final_status,
        ai_confidence=audit_record.confidence,
        ai_clauses=audit_record.clauses_cited,
        foir_value=signals.foir_value,
        sanctions_hit=signals.sanctions_hit,
        doc_check_passed=signals.doc_check_passed,
        temporal_passed=signals.temporal_passed,
        rag_chunks_retrieved=signals.rag_chunks_retrieved,
        reviewer_verdict=body.reviewer_verdict,
        reviewer_id=body.reviewer_id,
        actual_status=body.actual_status,
        reviewer_notes=body.reviewer_notes,
    )

    try:
        await fb_store.save_feedback(record)
    except FeedbackAlreadyExistsError:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "feedback_already_exists",
                "request_id": body.request_id,
            },
        )

    if (
        body.reviewer_verdict == ReviewerVerdict.DISAGREE
        and body.actual_status
        and audit_record.reviewer_status != ReviewerStatus.OVERRIDDEN
    ):
        try:
            override = OverrideRecord(
                audit_id=body.audit_id,
                reviewer_id=body.reviewer_id,
                reviewer_email=f"{body.reviewer_id}@nbfc.internal",
                original_status=audit_record.final_status,
                override_status=body.actual_status,
                override_reason=(
                    f"Feedback disagreement: reviewer set status to "
                    f"{body.actual_status}. Notes: {body.reviewer_notes or 'N/A'}"
                ),
            )
            await audit_store.apply_override(body.request_id, override)
            log.info(
                "Auto-override triggered by feedback disagreement",
                extra={
                    "request_id": body.request_id,
                    "original_status": audit_record.final_status,
                    "override_status": body.actual_status,
                    "reviewer_id": body.reviewer_id,
                    "operation": "submit_feedback",
                },
            )
        except AuditAlreadyOverriddenError:
            log.info(
                "Skipped auto-override — already overridden",
                extra={
                    "request_id": body.request_id,
                    "operation": "submit_feedback",
                },
            )
        except Exception as exc:
            log.error(
                "Auto-override failed (feedback still saved)",
                extra={
                    "request_id": body.request_id,
                    "error": str(exc),
                    "operation": "submit_feedback",
                },
            )

    return record


@feedback_router.get(
    "/summary",
    response_model=FeedbackSummary,
    summary="Aggregate feedback statistics (default: last 30 days)",
)
async def get_summary(
    fb_store: FeedbackStore = Depends(_get_feedback_store),
    from_dt: datetime | None = Query(default=None, description="ISO-8601 start"),
    to_dt: datetime | None = Query(default=None, description="ISO-8601 end"),
) -> FeedbackSummary:
    now = datetime.now(UTC)
    from_dt = from_dt or (now - timedelta(days=30))
    to_dt = to_dt or now

    queries = [
        fb_store.query_by_verdict(v.value, from_dt, to_dt, limit=500)
        for v in ReviewerVerdict
    ]
    results = await asyncio.gather(*queries, return_exceptions=True)

    all_records: list[FeedbackRecord] = []
    by_verdict: dict[str, int] = {}
    for verdict, result in zip(ReviewerVerdict, results):
        if isinstance(result, Exception):
            by_verdict[verdict.value] = 0
            continue
        by_verdict[verdict.value] = len(result)
        all_records.extend(result)

    total = len(all_records)
    agree_count = by_verdict.get("AGREE", 0)
    accuracy = agree_count / total if total > 0 else 0.0

    by_ai_status: dict[str, dict[str, int]] = {}
    for status in ("APPROVED", "REJECTED", "REVIEW"):
        subset = [r for r in all_records if r.ai_status == status]
        by_ai_status[status] = {
            "agree": sum(1 for r in subset if r.reviewer_verdict == ReviewerVerdict.AGREE),
            "disagree": sum(1 for r in subset if r.reviewer_verdict == ReviewerVerdict.DISAGREE),
        }

    correct_confs = [
        r.ai_confidence for r in all_records if r.was_correct
    ]
    wrong_confs = [
        r.ai_confidence
        for r in all_records
        if r.reviewer_verdict == ReviewerVerdict.DISAGREE
    ]
    avg_correct = (sum(correct_confs) / len(correct_confs)) if correct_confs else 0.0
    avg_wrong = (sum(wrong_confs) / len(wrong_confs)) if wrong_confs else 0.0
    calibration_gap = avg_correct - accuracy

    return FeedbackSummary(
        total_feedback=total,
        accuracy=round(accuracy, 4),
        by_verdict=by_verdict,
        by_original_ai_status=by_ai_status,
        avg_confidence_when_correct=round(avg_correct, 4),
        avg_confidence_when_wrong=round(avg_wrong, 4),
        calibration_gap=round(calibration_gap, 4),
        period={"from": from_dt.isoformat(), "to": to_dt.isoformat()},
    )


@feedback_router.get(
    "/calibration-dataset",
    response_model=CalibrationDataset,
    summary="Export calibration dataset for ML training",
)
async def get_calibration_dataset(
    fb_store: FeedbackStore = Depends(_get_feedback_store),
    _key: str = Depends(_require_reviewer_key),
    from_dt: datetime | None = Query(default=None, description="ISO-8601 start"),
    to_dt: datetime | None = Query(default=None, description="ISO-8601 end"),
    min_records: int = Query(default=30, ge=1, description="Minimum records required"),
) -> CalibrationDataset:
    try:
        return await fb_store.get_calibration_dataset(
            from_dt=from_dt, to_dt=to_dt, min_records=min_records
        )
    except InsufficientFeedbackError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "insufficient_feedback",
                "count": exc.count,
                "required": exc.required,
            },
        )


@feedback_router.get(
    "/{request_id}",
    response_model=FeedbackRecord,
    summary="Get feedback for a specific request",
)
async def get_feedback(
    request_id: str,
    fb_store: FeedbackStore = Depends(_get_feedback_store),
) -> FeedbackRecord:
    record = await fb_store.get_feedback(request_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "request_id": request_id},
        )
    return record
