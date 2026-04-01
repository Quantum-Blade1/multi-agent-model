"""
Compliance rule management REST API.

Exposes endpoints for reading, updating, and resetting runtime-configurable
compliance rules.  All write operations require ``X-Reviewer-Key``
authentication and produce an auditable ``RuleChangeLog`` entry.

Authentication
--------------
- **Read endpoints** (``GET``): unauthenticated — internal-service assumption.
- **Write endpoints** (``PUT``, ``POST``): require ``X-Reviewer-Key`` header
  matching the ``REVIEWER_API_KEY`` environment variable.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ai.compliance_loop.rule_engine import (
    ComplianceRule,
    DEFAULT_RULES,
    RuleChangeLog,
    RuleEngine,
    RuleUpdate,
)
from ai.observability.logger import get_logger

log = get_logger("ai.compliance_loop.rule_router")

rule_router = APIRouter(prefix="/rules", tags=["compliance-rules"])

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

_REVIEWER_KEY = os.getenv("REVIEWER_API_KEY", "")


def _get_engine(request: Request) -> RuleEngine:
    """Retrieve the ``RuleEngine`` from ``app.state``."""
    engine: RuleEngine | None = getattr(request.app.state, "rule_engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Rule engine not initialised")
    return engine


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
# Response models
# ---------------------------------------------------------------------------


class RuleUpdateResponse(BaseModel):
    """Response returned after a rule update or reset."""

    rule: ComplianceRule
    changelog: RuleChangeLog
    effective_immediately: bool = True
    cache_invalidated_at: str = Field(
        description="ISO-8601 UTC timestamp when the in-process cache was invalidated.",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@rule_router.get(
    "",
    response_model=list[ComplianceRule],
    summary="List all compliance rules",
)
async def list_rules(
    engine: RuleEngine = Depends(_get_engine),
) -> list[ComplianceRule]:
    return await engine.get_all_rules()


@rule_router.get(
    "/changelog",
    response_model=list[RuleChangeLog],
    summary="Get rule change history",
)
async def get_changelog(
    rule_id: str | None = Query(default=None, description="Filter by rule ID"),
    limit: int = Query(default=50, ge=1, le=200),
    engine: RuleEngine = Depends(_get_engine),
) -> list[RuleChangeLog]:
    return await engine.get_changelog(rule_id=rule_id, limit=limit)


@rule_router.get(
    "/{rule_id}",
    response_model=ComplianceRule,
    summary="Get a single compliance rule",
)
async def get_rule(
    rule_id: str,
    engine: RuleEngine = Depends(_get_engine),
) -> ComplianceRule:
    try:
        return await engine.get_rule(rule_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "rule_id": rule_id},
        )


@rule_router.put(
    "/{rule_id}",
    response_model=RuleUpdateResponse,
    summary="Update a compliance rule value",
)
async def update_rule(
    rule_id: str,
    body: RuleUpdate,
    engine: RuleEngine = Depends(_get_engine),
    _key: str = Depends(_require_reviewer_key),
) -> RuleUpdateResponse:
    if body.rule_id != rule_id:
        body = body.model_copy(update={"rule_id": rule_id})

    try:
        old_rule = await engine.get_rule(rule_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "rule_id": rule_id},
        )

    try:
        updated_rule, changelog = await engine.update_rule(body)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "rule_id": rule_id},
        )
    except (ValueError, Exception) as exc:
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=422, detail=str(exc))
        raise

    log.warning(
        "Rule updated via API",
        extra={
            "rule_id": rule_id,
            "old_value": str(old_rule.current_value),
            "new_value": str(body.new_value),
            "updated_by": body.updated_by,
            "operation": "update_rule",
        },
    )

    return RuleUpdateResponse(
        rule=updated_rule,
        changelog=changelog,
        cache_invalidated_at=datetime.now(UTC).isoformat(),
    )


@rule_router.post(
    "/reset/{rule_id}",
    response_model=RuleUpdateResponse,
    summary="Reset a rule to its default value",
)
async def reset_rule(
    rule_id: str,
    updated_by: str = Query(description="Reviewer ID performing the reset"),
    justification: str = Query(
        min_length=20,
        description="Reason for resetting to default (min 20 chars)",
    ),
    engine: RuleEngine = Depends(_get_engine),
    _key: str = Depends(_require_reviewer_key),
) -> RuleUpdateResponse:
    default = DEFAULT_RULES.get(rule_id)
    if default is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "rule_id": rule_id},
        )

    try:
        old_rule = await engine.get_rule(rule_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "rule_id": rule_id},
        )

    update = RuleUpdate(
        rule_id=rule_id,
        new_value=default.default_value,
        updated_by=updated_by,
        justification=justification,
    )

    try:
        updated_rule, changelog = await engine.update_rule(update)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    log.warning(
        "Rule reset to default via API",
        extra={
            "rule_id": rule_id,
            "old_value": str(old_rule.current_value),
            "default_value": str(default.default_value),
            "updated_by": updated_by,
            "operation": "reset_rule",
        },
    )

    return RuleUpdateResponse(
        rule=updated_rule,
        changelog=changelog,
        cache_invalidated_at=datetime.now(UTC).isoformat(),
    )
