"""
Output Formatter module.

Responsible for final ComplianceOutput validation and API response serialization.
"""

import logging
import time
from datetime import datetime, timezone
from uuid import uuid4

from ai.core.schemas import ComplianceOutput, ComplianceStatus

logger = logging.getLogger(__name__)


class OutputFormatter:
    """Formats and validates compliance outputs for API consumption."""

    def format(self, output: ComplianceOutput, start_time: float) -> ComplianceOutput:
        """Normalize and clamp output, and enforce safety rules."""
        if not isinstance(output, ComplianceOutput):
            raise TypeError("output must be ComplianceOutput")

        elapsed_ms = (time.monotonic() - start_time) * 1000.0
        output.processing_ms = round(elapsed_ms, 2)

        try:
            output.status = ComplianceStatus(output.status.value if isinstance(output.status, ComplianceStatus) else str(output.status))
        except Exception:
            logger.warning("OutputFormatter: invalid status '%s', coercing to REVIEW", output.status)
            output.status = ComplianceStatus.REVIEW

        if not output.request_id:
            output.request_id = str(uuid4())

        if output.timestamp is None:
            output.timestamp = datetime.now(timezone.utc)

        if output.confidence is None:
            output.confidence = 0.0
        output.confidence = max(0.0, min(1.0, float(output.confidence)))

        nonrecoverable = any(not (err.recoverable if hasattr(err, "recoverable") else True) for err in (output.agent_errors or []))
        if nonrecoverable and output.status == ComplianceStatus.APPROVED:
            output.status = ComplianceStatus.REVIEW
            output.reason = (output.reason or "") + " (Overridden to REVIEW due to agent failures.)"

        return output

    def to_api_response(self, output: ComplianceOutput) -> dict:
        """Serialize ComplianceOutput to API response dictionary."""
        if not isinstance(output, ComplianceOutput):
            raise TypeError("output must be ComplianceOutput")

        payload = output.model_dump(mode="json")  # Ensures JSON-serialisable
        payload["api_version"] = "1.0"
        return payload
