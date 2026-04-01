"""
Pipeline module.

Compliance orchestration with an injected DecisionEngine and FastAPI routes
for production NBFC compliance processing.  When an :class:`AuditStore` is
provided, every compliance decision is automatically written to the
tamper-evident audit trail.
"""

from __future__ import annotations

import asyncio
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
    """End-to-end compliance processing with an injected ``DecisionEngine``.

    When *audit_store* is provided, each successful compliance decision is
    persisted to DynamoDB as a hash-chained audit record.  Audit failures
    are logged at CRITICAL level but **never** block the compliance response.
    """

    def __init__(
        self,
        engine: DecisionEngine,
        audit_store: "AuditStore | None" = None,
    ) -> None:
        self.engine = engine
        self.audit_store = audit_store

    async def _write_audit(
        self,
        compliance_input: ComplianceInput,
        compliance_output: ComplianceOutput,
        agent_state: dict,
    ) -> None:
        """Best-effort audit write — failures are logged, never raised."""
        if self.audit_store is None:
            return

        from ai.audit.models import build_audit_record
        from ai.audit.store import AuditWriteError

        try:
            previous_hash = await self.audit_store.get_latest_chain_hash()
            audit_record = await build_audit_record(
                compliance_input=compliance_input,
                compliance_output=compliance_output,
                agent_state=agent_state,
                previous_chain_hash=previous_hash,
            )
            await self.audit_store.save_record(audit_record)
            logger.info(
                "Audit record saved audit_id=%s request_id=%s chain_hash=%s...",
                audit_record.audit_id,
                compliance_output.request_id,
                audit_record.chain_hash[:16],
            )
        except AuditWriteError as exc:
            logger.critical(
                "Audit write failed — compliance response still returned: %s "
                "request_id=%s",
                exc,
                compliance_output.request_id,
            )
        except Exception as exc:
            logger.critical(
                "Unexpected audit error — compliance response still returned: %s "
                "request_id=%s",
                exc,
                compliance_output.request_id,
            )

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

        output, final_state = await self.engine.process(validated)

        await self._write_audit(validated, output, final_state)

        return output

    async def process_batch(self, inputs: list[ComplianceInput]) -> list[ComplianceOutput]:
        """Delegate to the engine with a maximum batch size."""
        if len(inputs) > BATCH_MAX:
            raise HTTPException(
                status_code=413,
                detail=f"Batch size exceeds maximum of {BATCH_MAX}",
            )
        results = await self.engine.process_batch(inputs)

        outputs: list[ComplianceOutput] = []
        audit_coros = []
        for idx, (co, state) in enumerate(results):
            outputs.append(co)
            if self.audit_store is not None:
                audit_coros.append(
                    self._write_audit(inputs[idx], co, state)
                )

        if audit_coros:
            await asyncio.gather(*audit_coros, return_exceptions=True)

        return outputs


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
