"""
Calibration REST API for the NBFC Compliance AI system.

Provides endpoints to trigger calibration runs, inspect historical
reports, and check the health of the calibration subsystem.

Authentication
--------------
- **POST /calibration/run**: requires ``X-Reviewer-Key`` header.
- **GET** read endpoints: unauthenticated (internal service assumption).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ai.calibration.engine import CalibrationEngine, CalibrationReport
from ai.calibration.store import CalibrationStore
from ai.compliance_loop.feedback_store import (
    FeedbackStore,
    InsufficientFeedbackError,
    ReviewerVerdict,
)
from ai.observability.logger import get_logger

log = get_logger("ai.calibration.router")

calibration_router = APIRouter(prefix="/calibration", tags=["calibration"])

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

_REVIEWER_KEY = os.getenv("REVIEWER_API_KEY", "")


def _get_calibration_engine(request: Request) -> CalibrationEngine:
    engine = getattr(request.app.state, "calibration_engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Calibration engine not initialised")
    return engine


def _get_calibration_store(request: Request) -> CalibrationStore:
    store = getattr(request.app.state, "calibration_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Calibration store not initialised")
    return store


def _get_feedback_store(request: Request) -> FeedbackStore:
    store = getattr(request.app.state, "feedback_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Feedback store not initialised")
    return store


def _get_rule_engine(request: Request):
    engine = getattr(request.app.state, "rule_engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Rule engine not initialised")
    return engine


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


class CalibrationRunRequest(BaseModel):
    """Body for the POST /calibration/run endpoint."""

    from_dt: datetime | None = Field(default=None, description="ISO-8601 start date.")
    to_dt: datetime | None = Field(default=None, description="ISO-8601 end date.")
    apply_to_rules: bool = Field(
        default=False,
        description="If True, also update CONFIDENCE_PENALTY_PER_ERROR rule.",
    )
    force: bool = Field(
        default=False,
        description="Apply rule update even if change is small.",
    )


class CalibrationRunResult(BaseModel):
    """Response for the POST /calibration/run endpoint."""

    report: CalibrationReport
    rule_update: dict[str, Any] | None = None
    dataset_size: int


class CalibrationHealth(BaseModel):
    """Response for the GET /calibration/health endpoint."""

    latest_ece: float | None
    feedback_count_last_30d: int
    current_confidence_penalty: float
    last_calibration_run: str | None
    status: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@calibration_router.post(
    "/run",
    response_model=CalibrationRunResult,
    summary="Run a calibration analysis and optionally update rules",
)
async def run_calibration(
    body: CalibrationRunRequest,
    cal_engine: CalibrationEngine = Depends(_get_calibration_engine),
    cal_store: CalibrationStore = Depends(_get_calibration_store),
    fb_store: FeedbackStore = Depends(_get_feedback_store),
    _key: str = Depends(_require_reviewer_key),
) -> CalibrationRunResult:
    try:
        dataset = await fb_store.get_calibration_dataset(
            from_dt=body.from_dt, to_dt=body.to_dt
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

    report = await cal_engine.compute_report(dataset)
    await cal_store.save_report(report)

    rule_update: dict[str, Any] | None = None
    if body.apply_to_rules:
        rule_update = await cal_engine.apply_report_to_rules(
            report, updated_by="calibration-engine", force=body.force
        )

    log.info(
        "Calibration run completed",
        extra={
            "report_id": report.report_id,
            "ece": report.ece,
            "dataset_size": dataset.total,
            "rules_updated": rule_update.get("updated") if rule_update else False,
            "operation": "run_calibration",
        },
    )

    return CalibrationRunResult(
        report=report,
        rule_update=rule_update,
        dataset_size=dataset.total,
    )


@calibration_router.get(
    "/latest",
    response_model=CalibrationReport,
    summary="Get the most recent calibration report",
)
async def get_latest(
    cal_store: CalibrationStore = Depends(_get_calibration_store),
) -> CalibrationReport:
    report = await cal_store.get_latest_report()
    if report is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "no_calibration_reports", "message": "No reports exist yet"},
        )
    return report


@calibration_router.get(
    "/history",
    response_model=list[CalibrationReport],
    summary="List recent calibration reports",
)
async def get_history(
    cal_store: CalibrationStore = Depends(_get_calibration_store),
    limit: int = Query(default=20, ge=1, le=100, description="Max reports to return"),
) -> list[CalibrationReport]:
    return await cal_store.list_reports(limit=limit)


@calibration_router.get(
    "/health",
    response_model=CalibrationHealth,
    summary="Calibration system health check",
)
async def get_health(
    cal_store: CalibrationStore = Depends(_get_calibration_store),
    fb_store: FeedbackStore = Depends(_get_feedback_store),
    rule_engine=Depends(_get_rule_engine),
) -> CalibrationHealth:
    latest = await cal_store.get_latest_report()

    now = datetime.now(UTC)
    from_dt = now - timedelta(days=30)
    feedback_count = 0
    for verdict in ReviewerVerdict:
        try:
            records = await fb_store.query_by_verdict(
                verdict.value, from_dt, now, limit=500
            )
            feedback_count += len(records)
        except Exception:
            pass

    current_penalty = await rule_engine.confidence_penalty_per_error()

    if latest is None:
        status = "uncalibrated"
        latest_ece = None
        last_run = None
    else:
        latest_ece = latest.ece
        last_run = latest.generated_at.isoformat()
        age = now - latest.generated_at
        status = "stale" if age > timedelta(days=7) else "healthy"

    return CalibrationHealth(
        latest_ece=latest_ece,
        feedback_count_last_30d=feedback_count,
        current_confidence_penalty=current_penalty,
        last_calibration_run=last_run,
        status=status,
    )
