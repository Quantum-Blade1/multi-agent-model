"""
Pipeline module.

Top-level orchestration that connects input validation, the LangGraph
compliance pipeline, and output formatting.  Also exposes a FastAPI
router for HTTP access.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from ai.engine.decision_engine import DecisionEngine
from ai.engine.output_formatter import OutputFormatter
from ai.schemas import ComplianceInput

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Core pipeline class
# ---------------------------------------------------------------------------

class CompliancePipeline:
    """End-to-end compliance processing: validate → decide → format."""

    def __init__(self) -> None:
        self.engine = DecisionEngine()
        self.formatter = OutputFormatter()

    def process(self, input_data: dict) -> dict:
        """
        Run a full compliance check.

        Args:
            input_data: Raw dict matching the ComplianceInput schema.

        Returns:
            A JSON-serialisable dict with the compliance decision, metadata,
            and any error information.
        """
        # --- 1. Validate input -------------------------------------------------
        try:
            compliance_input = ComplianceInput(**input_data)
        except ValidationError as exc:
            logger.warning("Pipeline: input validation failed — %s", exc)
            return {
                "status": "Error",
                "reason": "Invalid input schema",
                "errors": exc.errors(),
            }

        # --- 2. Run the decision engine ----------------------------------------
        try:
            decision = self.engine.run(compliance_input)
        except Exception as exc:
            logger.error("Pipeline: decision engine error — %s", exc)
            return {
                "status": "Review",
                "reason": "Processing error",
                "error": str(exc),
            }

        # --- 3. Format the output ----------------------------------------------
        try:
            return self.formatter.format(decision)
        except Exception as exc:
            logger.error("Pipeline: output formatting error — %s", exc)
            return {
                "status": "Review",
                "reason": "Processing error",
                "error": str(exc),
            }


# ---------------------------------------------------------------------------
# FastAPI router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/ai", tags=["compliance"])
_pipeline = CompliancePipeline()


@router.post("/process")
async def process_compliance(input_body: ComplianceInput) -> dict:
    """
    Accept a compliance check request and return the decision.

    **POST /ai/process**

    - Body: ``ComplianceInput`` JSON
    - Returns: compliance decision dict with status, reason, clauses,
      confidence, rules_used, request_id, and timestamp.
    """
    input_hash = hashlib.sha256(
        json.dumps(input_body.model_dump(), sort_keys=True, default=str).encode()
    ).hexdigest()[:12]

    logger.info(
        "POST /ai/process — input_hash=%s  timestamp=%s",
        input_hash,
        datetime.now(timezone.utc).isoformat(),
    )

    try:
        result = _pipeline.process(input_body.model_dump())
    except Exception as exc:
        logger.error("POST /ai/process — unhandled error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    logger.info(
        "POST /ai/process — input_hash=%s  status=%s",
        input_hash,
        result.get("status", "unknown"),
    )

    return result
