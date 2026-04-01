"""
Pipeline module.

Compliance orchestration with an injected DecisionEngine and FastAPI routes
for production NBFC compliance processing.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import ValidationError

from ai.engine.decision_engine import DecisionEngine
from ai.schemas import ComplianceInput, ComplianceOutput, ComplianceStatus

logger = logging.getLogger(__name__)

BATCH_MAX = 20


class CompliancePipeline:
    """End-to-end compliance processing with an injected ``DecisionEngine``."""

    def __init__(self, engine: DecisionEngine) -> None:
        self.engine = engine

    async def process(
        self, compliance_in: ComplianceInput | dict
    ) -> ComplianceOutput:
        """
        Validate input (including manual Pydantic validation), log a trace hash,
        and run the decision engine.

        Accepts either a ``ComplianceInput`` instance or a raw dict (e.g. tests).
        """
        try:
            if isinstance(compliance_in, dict):
                validated = ComplianceInput.model_validate(compliance_in)
            else:
                validated = ComplianceInput.model_validate(compliance_in.model_dump())
        except ValidationError:
            return ComplianceOutput(
                request_id=str(uuid4()),
                correlation_id=None,
                status=ComplianceStatus.REVIEW,
                reason="Input validation failed",
                clauses=[],
                confidence=0.0,
                rules_used=[],
                agent_errors=[],
                short_circuit_reason=None,
                processing_ms=None,
            )

        raw = f"{validated.request_id}:{validated.query}"
        input_hash = hashlib.sha256(raw.encode()).hexdigest()[:12]
        logger.info("CompliancePipeline.process input_hash=%s", input_hash)

        return await self.engine.process(validated)

    async def process_batch(self, inputs: list[ComplianceInput]) -> list[ComplianceOutput]:
        """Delegate to the engine with a maximum batch size."""
        if len(inputs) > BATCH_MAX:
            raise HTTPException(
                status_code=413,
                detail=f"Batch size exceeds maximum of {BATCH_MAX}",
            )
        return await self.engine.process_batch(inputs)


def create_router(get_pipeline: Callable[..., CompliancePipeline]) -> APIRouter:
    """Build the ``/ai`` router with dependency-injected ``CompliancePipeline``."""

    router = APIRouter(prefix="/ai", tags=["compliance"])

    @router.post(
        "/process",
        response_model=ComplianceOutput,
        response_model_exclude_none=True,
        summary="Run compliance check",
        description=(
            "Accept a single compliance request body and return a structured "
            "compliance decision (status, reason, clauses, confidence, etc.)."
        ),
    )
    async def process_compliance(
        body: ComplianceInput,
        pipeline: Annotated[CompliancePipeline, Depends(get_pipeline)],
    ) -> ComplianceOutput:
        return await pipeline.process(body)

    @router.post(
        "/process/batch",
        response_model=list[ComplianceOutput],
        response_model_exclude_none=True,
        summary="Batch compliance checks",
        description=(
            "Run up to 20 compliance checks in one request. "
            "Response includes an ``X-Batch-Size`` header."
        ),
    )
    async def process_compliance_batch(
        body: list[ComplianceInput],
        response: Response,
        pipeline: Annotated[CompliancePipeline, Depends(get_pipeline)],
    ) -> list[ComplianceOutput]:
        out = await pipeline.process_batch(body)
        response.headers["X-Batch-Size"] = str(len(body))
        return out

    return router
