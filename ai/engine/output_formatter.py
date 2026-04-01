"""
Output Formatter module.

Converts a ComplianceOutput into a clean, JSON-serialisable dictionary
with added metadata (timestamp, request ID) and field validation.
"""

import logging
from datetime import datetime, timezone
from uuid import uuid4

from ai.schemas import ComplianceOutput, ComplianceStatus

logger = logging.getLogger(__name__)

_VALID_STATUSES = {s.value for s in ComplianceStatus}


class OutputFormatter:
    """Formats and validates a ComplianceOutput for API / report consumption."""

    def format(self, output: ComplianceOutput) -> dict:
        """
        Convert a ComplianceOutput to a JSON-serialisable dict with metadata.

        Adds:
            - ``request_id``  — a unique UUID4 string
            - ``timestamp``   — ISO-8601 UTC timestamp

        Validates:
            - ``status`` must be Approved / Rejected / Review; forced to
              ``"Review"`` if invalid.
            - Missing fields are filled with safe defaults.

        Args:
            output: A ComplianceOutput instance.

        Returns:
            A plain dict ready for ``json.dumps()`` or API response.
        """
        # --- Validate / coerce status ------------------------------------------
        status_value = getattr(output.status, "value", str(output.status))
        if status_value not in _VALID_STATUSES:
            logger.warning(
                "OutputFormatter: invalid status '%s' — forcing 'Review'.",
                status_value,
            )
            status_value = ComplianceStatus.REVIEW.value

        # --- Build the response dict -------------------------------------------
        result: dict = {
            "request_id": str(uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": status_value,
            "reason": output.reason if output.reason else "No reason provided.",
            "clauses": output.clauses if output.clauses else [],
            "confidence": (
                output.confidence if output.confidence is not None else 0.0
            ),
            "rules_used": output.rules_used if output.rules_used else [],
        }

        return result
