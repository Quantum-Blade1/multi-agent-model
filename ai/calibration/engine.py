"""
Confidence calibration engine for the NBFC Compliance AI system.

Observes human reviewer outcomes (via :class:`CalibrationDataset`) and
computes Expected Calibration Error (ECE), reliability-diagram buckets,
and directional bias metrics.  The derived ``recommended_confidence_penalty``
can be written back to the :class:`RuleEngine` to auto-tune the decision
agent's confidence scoring without redeployment.

Only uses numpy and stdlib -- no external ML libraries.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import numpy as np
from pydantic import BaseModel, Field

from ai.compliance_loop.feedback_store import (
    CalibrationDataset,
    FeedbackRecord,
    ReviewerVerdict,
)
from ai.compliance_loop.rule_engine import RuleEngine, RuleUpdate
from ai.observability.logger import get_logger

log = get_logger("ai.calibration.engine")

NUM_BUCKETS = 10

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ConfidenceBucket(BaseModel):
    """One bin of the reliability diagram (equal-width confidence interval)."""

    lower: float = Field(description="Inclusive lower bound of the bucket.")
    upper: float = Field(description="Exclusive upper bound (inclusive for last bucket).")
    count: int = Field(description="Number of records in this bucket.")
    accuracy: float = Field(description="Fraction of was_correct records in bucket.")
    avg_confidence: float = Field(description="Mean AI confidence in bucket.")
    calibration_error: float = Field(
        description="|avg_confidence - accuracy| for this bucket."
    )


class CalibrationReport(BaseModel):
    """Full calibration analysis over a feedback window."""

    report_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique identifier for this report.",
    )
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When this report was generated.",
    )
    feedback_count: int = Field(description="Total feedback records analysed.")
    feedback_period: dict[str, str] = Field(
        description="Date range: {'from': ISO, 'to': ISO}."
    )

    ece: float = Field(
        description=(
            "Expected Calibration Error. 0.0 = perfectly calibrated; "
            "higher values indicate worse calibration."
        ),
    )
    buckets: list[ConfidenceBucket] = Field(
        description="10 equal-width reliability-diagram buckets [0.0,0.1)...[0.9,1.0].",
    )

    avg_overconfidence: float = Field(
        description="Mean of (confidence - 1.0) for AGREE records.",
    )
    avg_underconfidence: float = Field(
        description="Mean of (0.0 - confidence) for DISAGREE records.",
    )
    is_overconfident: bool = Field(
        description="True if avg_overconfidence > 0.05.",
    )

    accuracy_by_status: dict[str, float] = Field(
        description="Per ai_status accuracy: {'APPROVED': 0.91, ...}.",
    )

    recommended_confidence_penalty: float = Field(
        description="Derived penalty: max(0.05, min(0.30, ece * 1.5)).",
    )
    recommendation_text: str = Field(
        description="Human-readable explanation of calibration state.",
    )


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class CalibrationEngine:
    """Computes calibration metrics and optionally writes adjustments to rules.

    Usage::

        engine = CalibrationEngine(rule_engine)
        report = await engine.compute_report(dataset)
        result = await engine.apply_report_to_rules(report, "reviewer-1")
    """

    def __init__(self, rule_engine: RuleEngine) -> None:
        self._rule_engine = rule_engine

    # ── Core computation ──────────────────────────────────────────────────

    async def compute_report(
        self, dataset: CalibrationDataset
    ) -> CalibrationReport:
        """Bin feedback records and compute ECE + directional metrics."""
        records = dataset.records
        n = len(records)

        # 1. Build reliability-diagram buckets
        buckets = self._build_buckets(records, n)

        # 2. ECE = weighted sum of per-bucket calibration error
        ece = sum((b.count / n) * b.calibration_error for b in buckets) if n else 0.0

        # 3. Directional bias
        agree_confs = [r.ai_confidence for r in records if r.reviewer_verdict == ReviewerVerdict.AGREE]
        disagree_confs = [r.ai_confidence for r in records if r.reviewer_verdict == ReviewerVerdict.DISAGREE]

        avg_overconfidence = float(np.mean([c - 1.0 for c in agree_confs])) if agree_confs else 0.0
        avg_underconfidence = float(np.mean([0.0 - c for c in disagree_confs])) if disagree_confs else 0.0

        # 4. Per-status accuracy
        accuracy_by_status = self._accuracy_by_status(records)

        # 5. Recommended penalty
        penalty = max(0.05, min(0.30, ece * 1.5))

        # 6. Recommendation text
        if ece < 0.05:
            text = "Model is well-calibrated. No adjustment needed."
        elif ece <= 0.15:
            text = (
                f"Moderate miscalibration (ECE={ece:.3f}). "
                f"Consider applying penalty of {penalty:.3f}."
            )
        else:
            text = (
                f"Significant miscalibration (ECE={ece:.3f}). "
                f"Recommend immediate penalty update to {penalty:.3f}."
            )

        return CalibrationReport(
            feedback_count=n,
            feedback_period={
                "from": dataset.from_dt.isoformat(),
                "to": dataset.to_dt.isoformat(),
            },
            ece=round(ece, 4),
            buckets=buckets,
            avg_overconfidence=round(avg_overconfidence, 4),
            avg_underconfidence=round(avg_underconfidence, 4),
            is_overconfident=avg_overconfidence > 0.05,
            accuracy_by_status=accuracy_by_status,
            recommended_confidence_penalty=round(penalty, 4),
            recommendation_text=text,
        )

    # ── Rule auto-update ──────────────────────────────────────────────────

    async def apply_report_to_rules(
        self,
        report: CalibrationReport,
        updated_by: str,
        force: bool = False,
    ) -> dict[str, Any]:
        """Optionally update ``CONFIDENCE_PENALTY_PER_ERROR`` in the rule engine.

        Updates only when:
        - ECE > 0.05 (meaningful miscalibration) OR ``force`` is True
        - The proposed penalty differs from the current by more than 0.01
        """
        old_penalty = await self._rule_engine.confidence_penalty_per_error()
        new_penalty = report.recommended_confidence_penalty

        should_update = (report.ece > 0.05 or force) and abs(new_penalty - old_penalty) > 0.01

        if not should_update:
            reason = (
                "No update needed: "
                + (f"ECE={report.ece:.3f} <= 0.05" if report.ece <= 0.05 and not force else "")
                + (f"delta={abs(new_penalty - old_penalty):.3f} <= 0.01" if abs(new_penalty - old_penalty) <= 0.01 else "")
            )
            return {
                "updated": False,
                "old_penalty": old_penalty,
                "new_penalty": new_penalty,
                "reason": reason.strip(": "),
                "ece": report.ece,
            }

        justification = (
            f"Auto-calibration: ECE={report.ece:.3f}, based on "
            f"{report.feedback_count} reviewer decisions. "
            f"Adjusted penalty from {old_penalty:.3f} to {new_penalty:.3f}."
        )

        update = RuleUpdate(
            rule_id="CONFIDENCE_PENALTY_PER_ERROR",
            new_value=new_penalty,
            updated_by=updated_by,
            justification=justification,
        )

        updated_rule, changelog = await self._rule_engine.update_rule(update)

        log.warning(
            "Confidence penalty auto-updated by calibration engine",
            extra={
                "old_penalty": old_penalty,
                "new_penalty": new_penalty,
                "ece": report.ece,
                "feedback_count": report.feedback_count,
                "updated_by": updated_by,
                "operation": "apply_report_to_rules",
            },
        )

        return {
            "updated": True,
            "old_penalty": old_penalty,
            "new_penalty": new_penalty,
            "reason": justification,
            "ece": report.ece,
        }

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _build_buckets(
        records: list[FeedbackRecord], total: int
    ) -> list[ConfidenceBucket]:
        """Partition records into 10 equal-width confidence buckets."""
        buckets: list[ConfidenceBucket] = []
        for i in range(NUM_BUCKETS):
            lower = i / NUM_BUCKETS
            upper = (i + 1) / NUM_BUCKETS

            if i == NUM_BUCKETS - 1:
                in_bucket = [r for r in records if lower <= r.ai_confidence <= upper]
            else:
                in_bucket = [r for r in records if lower <= r.ai_confidence < upper]

            count = len(in_bucket)
            if count == 0:
                buckets.append(
                    ConfidenceBucket(
                        lower=lower,
                        upper=upper,
                        count=0,
                        accuracy=0.0,
                        avg_confidence=0.0,
                        calibration_error=0.0,
                    )
                )
                continue

            accuracy = sum(1 for r in in_bucket if r.was_correct) / count
            avg_conf = float(np.mean([r.ai_confidence for r in in_bucket]))
            cal_error = abs(avg_conf - accuracy)

            buckets.append(
                ConfidenceBucket(
                    lower=round(lower, 1),
                    upper=round(upper, 1),
                    count=count,
                    accuracy=round(accuracy, 4),
                    avg_confidence=round(avg_conf, 4),
                    calibration_error=round(cal_error, 4),
                )
            )

        return buckets

    @staticmethod
    def _accuracy_by_status(records: list[FeedbackRecord]) -> dict[str, float]:
        """Group by ``ai_status`` and compute per-group accuracy."""
        groups: dict[str, list[FeedbackRecord]] = {}
        for r in records:
            groups.setdefault(r.ai_status, []).append(r)

        return {
            status: round(sum(1 for r in recs if r.was_correct) / len(recs), 4)
            for status, recs in groups.items()
        }
