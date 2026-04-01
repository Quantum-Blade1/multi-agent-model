"""
Audit trail REST API for the NBFC Compliance AI system.

Exposes endpoints for querying audit records, applying human overrides,
verifying hash-chain integrity, and retrieving aggregate statistics.

Authentication
--------------
- **Read endpoints** (``GET``): unauthenticated — internal-service assumption.
- **Override endpoint** (``POST``): requires ``X-Reviewer-Key`` header
  matching the ``REVIEWER_API_KEY`` environment variable.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from audit.models import (
    AuditRecord,
    OverrideRecord,
    VerificationResult,
)
from audit.store import (
    AuditAlreadyOverriddenError,
    AuditNotFoundError,
    AuditQueryResult,
    AuditStore,
)
from observability.logger import get_logger

log = get_logger("audit.router")

audit_router = APIRouter(prefix="/audit", tags=["audit"])

# ---------------------------------------------------------------------------
# Dependency: AuditStore from app.state
# ---------------------------------------------------------------------------


def _get_store(request: Request) -> AuditStore:
    store: AuditStore | None = getattr(request.app.state, "audit_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Audit store not initialised")
    return store


# ---------------------------------------------------------------------------
# Auth dependency for override endpoint
# ---------------------------------------------------------------------------

_REVIEWER_KEY = os.getenv("REVIEWER_API_KEY", "")


def _require_reviewer_key(
    x_reviewer_key: str | None = Header(default=None),
) -> str:
    """Validate the ``X-Reviewer-Key`` header against the env var."""
    expected = os.getenv("REVIEWER_API_KEY", _REVIEWER_KEY)
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="REVIEWER_API_KEY not configured on server",
        )
    if x_reviewer_key is None or x_reviewer_key != expected:
        raise HTTPException(status_code=403, detail="Invalid or missing reviewer key")
    return x_reviewer_key


# ---------------------------------------------------------------------------
# Pagination helpers
# ---------------------------------------------------------------------------


def _encode_next_key(dynamo_key: dict[str, Any] | None) -> str | None:
    if dynamo_key is None:
        return None
    return base64.urlsafe_b64encode(
        json.dumps(dynamo_key, default=str).encode()
    ).decode()


def _decode_next_key(token: str | None) -> dict[str, Any] | None:
    if token is None:
        return None
    try:
        return json.loads(base64.urlsafe_b64decode(token.encode()))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid pagination token")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class OverrideRequest(BaseModel):
    """Body for the override endpoint."""

    override_status: str = Field(
        description="New status: APPROVED, REJECTED, or REVIEW.",
    )
    override_reason: str = Field(
        min_length=20,
        description="Mandatory justification (minimum 20 characters).",
    )
    reviewer_id: str = Field(description="Authenticated reviewer identifier.")
    reviewer_email: str = Field(description="Reviewer email for display.")
    regulatory_reference: str | None = Field(
        default=None,
        description="Optional RBI clause cited by the reviewer.",
    )


class PaginatedAuditResponse(BaseModel):
    """API-level response wrapping AuditQueryResult with opaque pagination."""

    records: list[AuditRecord]
    total_returned: int
    has_more: bool
    next_key: str | None = None


class AuditStats(BaseModel):
    """Aggregate statistics over the last 30 days."""

    total_records: int
    by_status: dict[str, int]
    by_reviewer_status: dict[str, int]
    override_rate: float
    avg_confidence: float
    period: dict[str, str]


# ---------------------------------------------------------------------------
# Stats cache (module-level, 60-second TTL)
# ---------------------------------------------------------------------------

_stats_cache: dict[str, Any] = {"data": None, "ts": 0.0}
_STATS_TTL = 60.0


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@audit_router.get(
    "/record/{request_id}",
    response_model=AuditRecord,
    summary="Get a single audit record",
)
async def get_audit_record(
    request_id: str,
    store: AuditStore = Depends(_get_store),
) -> AuditRecord:
    record = await store.get_by_request_id(request_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "request_id": request_id},
        )
    return record


@audit_router.get(
    "/records",
    response_model=PaginatedAuditResponse,
    summary="Query audit records",
)
async def query_audit_records(
    store: AuditStore = Depends(_get_store),
    status: str | None = Query(default=None, description="APPROVED / REJECTED / REVIEW"),
    reviewer_status: str | None = Query(default=None, description="PENDING / REVIEWED / OVERRIDDEN"),
    correlation_id: str | None = Query(default=None),
    from_dt: datetime | None = Query(default=None, description="ISO-8601 start"),
    to_dt: datetime | None = Query(default=None, description="ISO-8601 end"),
    limit: int = Query(default=50, ge=1, le=200),
    next_key: str | None = Query(default=None, description="Opaque pagination token"),
) -> PaginatedAuditResponse:
    now = datetime.now(UTC)
    from_dt = from_dt or (now - timedelta(days=7))
    to_dt = to_dt or now
    last_key = _decode_next_key(next_key)

    if correlation_id is not None:
        records = await store.query_by_correlation_id(correlation_id)
        return PaginatedAuditResponse(
            records=records,
            total_returned=len(records),
            has_more=False,
            next_key=None,
        )

    if status is not None:
        result = await store.query_by_status(
            status=status, from_dt=from_dt, to_dt=to_dt,
            limit=limit, last_key=last_key,
        )
    elif reviewer_status is not None:
        result = await store.query_by_reviewer_status(
            reviewer_status=reviewer_status, limit=limit, last_key=last_key,
        )
    else:
        result = await store.query_by_date_range(
            from_dt=from_dt, to_dt=to_dt, limit=limit, last_key=last_key,
        )

    return PaginatedAuditResponse(
        records=result.records,
        total_returned=result.total_returned,
        has_more=result.has_more,
        next_key=_encode_next_key(result.next_key),
    )


@audit_router.post(
    "/record/{request_id}/override",
    response_model=AuditRecord,
    summary="Override an AI compliance decision",
)
async def apply_override(
    request_id: str,
    body: OverrideRequest,
    store: AuditStore = Depends(_get_store),
    _key: str = Depends(_require_reviewer_key),
) -> AuditRecord:
    original = await store.get_by_request_id(request_id)
    if original is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "request_id": request_id},
        )

    override = OverrideRecord(
        audit_id=original.audit_id,
        reviewer_id=body.reviewer_id,
        reviewer_email=body.reviewer_email,
        original_status=original.final_status,
        override_status=body.override_status,
        override_reason=body.override_reason,
        regulatory_reference=body.regulatory_reference,
    )

    try:
        updated = await store.apply_override(request_id, override)
    except AuditAlreadyOverriddenError:
        raise HTTPException(
            status_code=409,
            detail={"error": "already_overridden", "request_id": request_id},
        )

    log.info(
        "Override applied",
        extra={
            "reviewer_id": body.reviewer_id,
            "original_status": original.final_status,
            "override_status": body.override_status,
            "request_id": request_id,
            "operation": "apply_override",
        },
    )
    return updated


@audit_router.get(
    "/chain/verify",
    response_model=VerificationResult,
    summary="Verify audit hash-chain integrity",
)
async def verify_chain(
    store: AuditStore = Depends(_get_store),
    from_sequence: int = Query(default=0, ge=0),
    to_sequence: int | None = Query(default=None),
) -> VerificationResult:
    result = await store.verify_chain_integrity(
        from_sequence=from_sequence, to_sequence=to_sequence,
    )
    if not result.valid:
        log.critical(
            "AUDIT CHAIN BROKEN",
            extra={
                "first_broken_at": result.first_broken_at,
                "total_records": result.total_records,
                "verified_records": result.verified_records,
                "operation": "verify_chain",
            },
        )
    return result


@audit_router.get(
    "/stats",
    response_model=AuditStats,
    summary="Aggregate audit statistics (30-day window, cached 60s)",
)
async def get_stats(
    store: AuditStore = Depends(_get_store),
) -> AuditStats:
    now = time.monotonic()
    if _stats_cache["data"] is not None and (now - _stats_cache["ts"]) < _STATS_TTL:
        return _stats_cache["data"]

    utc_now = datetime.now(UTC)
    from_dt = utc_now - timedelta(days=30)

    statuses = ["APPROVED", "REJECTED", "REVIEW"]
    reviewer_statuses = ["PENDING", "REVIEWED", "OVERRIDDEN"]

    status_queries = [
        store.query_by_status(s, from_dt, utc_now, limit=200)
        for s in statuses
    ]
    reviewer_queries = [
        store.query_by_reviewer_status(rs, limit=200)
        for rs in reviewer_statuses
    ]

    results = await asyncio.gather(
        *status_queries, *reviewer_queries, return_exceptions=True,
    )

    by_status: dict[str, int] = {}
    all_records: list[Any] = []
    for i, s in enumerate(statuses):
        r = results[i]
        count = r.total_returned if not isinstance(r, Exception) else 0
        by_status[s] = count
        if not isinstance(r, Exception):
            all_records.extend(r.records)

    by_reviewer: dict[str, int] = {}
    for i, rs in enumerate(reviewer_statuses):
        r = results[len(statuses) + i]
        by_reviewer[rs] = r.total_returned if not isinstance(r, Exception) else 0

    total = sum(by_status.values())
    overridden = by_reviewer.get("OVERRIDDEN", 0)
    override_rate = (overridden / total) if total > 0 else 0.0

    confidences = [rec.confidence for rec in all_records if hasattr(rec, "confidence")]
    avg_confidence = (sum(confidences) / len(confidences)) if confidences else 0.0

    stats = AuditStats(
        total_records=total,
        by_status=by_status,
        by_reviewer_status=by_reviewer,
        override_rate=round(override_rate, 4),
        avg_confidence=round(avg_confidence, 4),
        period={
            "from": from_dt.isoformat(),
            "to": utc_now.isoformat(),
        },
    )

    _stats_cache["data"] = stats
    _stats_cache["ts"] = now
    return stats
