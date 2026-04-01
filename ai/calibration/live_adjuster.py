"""
Live confidence adjuster for the NBFC Compliance AI system.

Takes the raw confidence score from the LLM response and applies
empirically-derived deductions before it reaches the final
:class:`ComplianceOutput`.  Deduction amounts come from the
``CONFIDENCE_PENALTY_PER_ERROR`` rule, which is auto-tuned by the
calibration engine based on human reviewer feedback.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ai.compliance_loop.rule_engine import RuleEngine
from ai.observability.logger import get_logger
from ai.schemas import AgentError

log = get_logger("ai.calibration.live_adjuster")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Deduction(BaseModel):
    """A single confidence deduction with its reason and magnitude."""

    reason: str = Field(description="Why this deduction was applied.")
    amount: float = Field(description="Absolute confidence reduction (0.0-1.0).")


class AdjustedConfidence(BaseModel):
    """Result of the live confidence adjustment pipeline."""

    raw: float = Field(description="Original confidence from the LLM.")
    adjusted: float = Field(description="Final confidence after all deductions.")
    total_deduction: float = Field(description="Sum of all deduction amounts.")
    deductions: list[Deduction] = Field(
        default_factory=list,
        description="Ordered list of deductions applied.",
    )


# ---------------------------------------------------------------------------
# Adjuster
# ---------------------------------------------------------------------------


class LiveConfidenceAdjuster:
    """Applies rule-engine-driven confidence deductions at inference time.

    Usage::

        adjuster = LiveConfidenceAdjuster(rule_engine)
        result = await adjuster.adjust(
            raw_confidence=0.92,
            agent_errors=state["agent_errors"],
            rag_context_empty=len(state["rag_context"]) == 0,
            sanctions_hit=state["sanctions_hit"],
            short_circuit_reason=state["short_circuit_reason"],
        )
        final_confidence = result.adjusted
    """

    def __init__(self, rule_engine: RuleEngine) -> None:
        self._rule_engine = rule_engine

    async def adjust(
        self,
        raw_confidence: float,
        agent_errors: list[AgentError],
        rag_context_empty: bool,
        sanctions_hit: bool,
        short_circuit_reason: str | None,
    ) -> AdjustedConfidence:
        """Compute deductions and return the adjusted confidence."""
        penalty = await self._rule_engine.confidence_penalty_per_error()
        deductions: list[Deduction] = []

        non_recoverable = [e for e in agent_errors if not e.recoverable]
        recoverable = [e for e in agent_errors if e.recoverable]

        for error in non_recoverable:
            deductions.append(
                Deduction(
                    reason=f"Non-recoverable agent error: {error.agent}",
                    amount=penalty,
                )
            )

        for error in recoverable:
            deductions.append(
                Deduction(
                    reason=f"Recoverable agent error: {error.agent}",
                    amount=round(penalty * 0.5, 4),
                )
            )

        if rag_context_empty:
            deductions.append(
                Deduction(
                    reason="RAG context empty — decision made without regulatory reference",
                    amount=penalty,
                )
            )

        if short_circuit_reason:
            deductions.append(
                Deduction(
                    reason=f"Pipeline short-circuited: {short_circuit_reason}",
                    amount=round(penalty * 0.5, 4),
                )
            )

        total_deduction = sum(d.amount for d in deductions)
        adjusted = max(0.0, min(1.0, raw_confidence - total_deduction))

        log.debug(
            "Confidence adjusted",
            extra={
                "raw": raw_confidence,
                "adjusted": round(adjusted, 4),
                "total_deduction": round(total_deduction, 4),
                "deduction_count": len(deductions),
                "operation": "live_adjust",
            },
        )

        return AdjustedConfidence(
            raw=raw_confidence,
            adjusted=round(adjusted, 4),
            total_deduction=round(total_deduction, 4),
            deductions=deductions,
        )
