"""
DynamoDB-backed feedback storage for human reviewer verdicts.

Captures whether human reviewers agreed with AI compliance decisions,
powering the confidence calibration layer and active learning loop.

DynamoDB table::

    nbfc-feedback
        PK: request_id (S)
        GSI-1: verdict-index   PK: reviewer_verdict  SK: feedback_at
        GSI-2: reviewer-index  PK: reviewer_id       SK: feedback_at
        TTL:   expires_at (N)  — 7 years per RBI retention
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import uuid4

import aiobotocore.session
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError
from pydantic import BaseModel, Field

from observability.logger import get_logger

log = get_logger("feedback.store")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FEEDBACK_TABLE = os.getenv("FEEDBACK_TABLE", "nbfc-feedback")
_RBI_RETENTION_SECONDS = int(7 * 365.25 * 86400)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ReviewerVerdict(str, Enum):
    """Human reviewer's assessment of an AI compliance decision."""

    AGREE = "AGREE"
    DISAGREE = "DISAGREE"
    PARTIAL = "PARTIAL"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class FeedbackRecord(BaseModel):
    """Links a human verdict back to an AI compliance decision.

    Stores both the AI outputs and the key agent signals so ML pipelines
    can train on structured features without joining back to the audit table.
    """

    feedback_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique identifier for this feedback entry.",
    )
    request_id: str = Field(description="Links to the original ComplianceInput request.")
    audit_id: str = Field(description="Links to the AuditRecord for this decision.")

    # AI outputs
    ai_status: str = Field(description="AI verdict: APPROVED, REJECTED, or REVIEW.")
    ai_confidence: float = Field(description="AI confidence score (0.0-1.0).")
    ai_clauses: list[str] = Field(
        default_factory=list,
        description="RBI clauses cited by the AI in the decision.",
    )

    # Agent signal snapshot (flat for ML feature extraction)
    foir_value: float = Field(description="FOIR computed by the transaction agent.")
    sanctions_hit: bool = Field(description="Whether sanctions check flagged a match.")
    doc_check_passed: bool = Field(description="Whether all required docs were present.")
    temporal_passed: bool = Field(description="Whether all docs were within validity.")
    rag_chunks_retrieved: int = Field(description="Number of RAG chunks used.")

    # Reviewer assessment
    reviewer_verdict: ReviewerVerdict = Field(description="AGREE, DISAGREE, or PARTIAL.")
    reviewer_id: str = Field(description="Authenticated reviewer identifier.")
    actual_status: str | None = Field(
        default=None,
        description="If DISAGREE: the status the reviewer set instead.",
    )
    reviewer_notes: str | None = Field(
        default=None,
        description="Free-text reviewer comments.",
    )
    feedback_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp when feedback was submitted.",
    )

    @property
    def was_correct(self) -> bool:
        """Whether the AI decision was at least partially accepted."""
        return self.reviewer_verdict in (ReviewerVerdict.AGREE, ReviewerVerdict.PARTIAL)

    @property
    def confidence_error(self) -> float | None:
        """Absolute calibration error.

        For AGREE: how far confidence was from 1.0 (ideal for correct).
        For DISAGREE: how far confidence was from 0.0 (ideal for wrong).
        For PARTIAL: returns None (ambiguous signal).
        """
        if self.reviewer_verdict == ReviewerVerdict.AGREE:
            return abs(self.ai_confidence - 1.0)
        elif self.reviewer_verdict == ReviewerVerdict.DISAGREE:
            return abs(self.ai_confidence - 0.0)
        return None


class CalibrationDataset(BaseModel):
    """Aggregate statistics over a feedback window for calibration."""

    records: list[FeedbackRecord]
    total: int
    agree_count: int
    disagree_count: int
    partial_count: int
    accuracy: float = Field(description="agree_count / total (0.0-1.0).")
    from_dt: datetime
    to_dt: datetime
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class FeedbackAlreadyExistsError(Exception):
    """Raised when feedback for a request_id has already been submitted."""


class InsufficientFeedbackError(Exception):
    """Raised when too few feedback records exist for calibration."""

    def __init__(self, count: int, required: int) -> None:
        self.count = count
        self.required = required
        super().__init__(
            f"Only {count} feedback records available, need at least {required}"
        )


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

_serializer = TypeSerializer()
_deserializer = TypeDeserializer()


def _floats_to_decimal(obj: Any) -> Any:
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_floats_to_decimal(item) for item in obj]
    return obj


def _decimals_to_float(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        if obj == int(obj):
            return int(obj)
        return float(obj)
    if isinstance(obj, dict):
        return {k: _decimals_to_float(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimals_to_float(item) for item in obj]
    return obj


def _feedback_to_dynamo(record: FeedbackRecord) -> dict[str, Any]:
    data = record.model_dump(mode="json")
    prepared = _floats_to_decimal(data)
    prepared["expires_at"] = (
        int(record.feedback_at.timestamp()) + _RBI_RETENTION_SECONDS
    )
    return {k: _serializer.serialize(v) for k, v in prepared.items()}


def _feedback_from_dynamo(item: dict[str, Any]) -> FeedbackRecord:
    raw = {k: _deserializer.deserialize(v) for k, v in item.items()}
    data = _decimals_to_float(raw)
    data.pop("expires_at", None)
    return FeedbackRecord.model_validate(data, strict=False)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class FeedbackStore:
    """Async DynamoDB-backed store for reviewer feedback records.

    Usage::

        store = FeedbackStore()
        await store.save_feedback(record)
        dataset = await store.get_calibration_dataset(min_records=30)
    """

    def __init__(
        self,
        table_name: str | None = None,
        region: str | None = None,
    ) -> None:
        self._table = table_name or FEEDBACK_TABLE
        self._region = region or os.getenv("AWS_REGION", "ap-south-1")
        self._session = aiobotocore.session.get_session()
        self._client: Any = None
        self._client_ctx: Any = None

    async def _get_client(self) -> Any:
        if self._client is None:
            self._client_ctx = self._session.create_client(
                "dynamodb", region_name=self._region
            )
            self._client = await self._client_ctx.__aenter__()
        return self._client

    async def close(self) -> None:
        if self._client_ctx is not None:
            await self._client_ctx.__aexit__(None, None, None)
            self._client = None
            self._client_ctx = None

    # ── Write ─────────────────────────────────────────────────────────────

    async def save_feedback(self, record: FeedbackRecord) -> str:
        """Save a feedback record. One per ``request_id`` (idempotent).

        Returns:
            The ``feedback_id``.

        Raises:
            FeedbackAlreadyExistsError: If feedback already exists for this request.
        """
        client = await self._get_client()
        item = _feedback_to_dynamo(record)

        try:
            await client.put_item(
                TableName=self._table,
                Item=item,
                ConditionExpression="attribute_not_exists(request_id)",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise FeedbackAlreadyExistsError(
                    f"Feedback already exists for request_id={record.request_id}"
                ) from exc
            raise

        log.info(
            "Feedback saved",
            extra={
                "feedback_id": record.feedback_id,
                "request_id": record.request_id,
                "verdict": record.reviewer_verdict.value,
                "operation": "save_feedback",
            },
        )
        return record.feedback_id

    # ── Read ──────────────────────────────────────────────────────────────

    async def get_feedback(self, request_id: str) -> FeedbackRecord | None:
        """Fetch feedback for a specific request."""
        client = await self._get_client()
        response = await client.query(
            TableName=self._table,
            KeyConditionExpression="request_id = :rid",
            ExpressionAttributeValues={":rid": {"S": request_id}},
            Limit=1,
        )
        items = response.get("Items", [])
        if not items:
            return None
        return _feedback_from_dynamo(items[0])

    async def query_by_verdict(
        self,
        verdict: str,
        from_dt: datetime,
        to_dt: datetime,
        limit: int = 100,
    ) -> list[FeedbackRecord]:
        """Query feedback records by verdict using GSI-1."""
        client = await self._get_client()
        response = await client.query(
            TableName=self._table,
            IndexName="verdict-index",
            KeyConditionExpression=(
                "reviewer_verdict = :v AND feedback_at BETWEEN :f AND :t"
            ),
            ExpressionAttributeValues={
                ":v": {"S": verdict},
                ":f": {"S": from_dt.isoformat()},
                ":t": {"S": to_dt.isoformat()},
            },
            Limit=limit,
            ScanIndexForward=False,
        )
        return [_feedback_from_dynamo(item) for item in response.get("Items", [])]

    async def get_calibration_dataset(
        self,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        min_records: int = 30,
    ) -> CalibrationDataset:
        """Fetch all feedback in the date range and compute calibration stats.

        Raises:
            InsufficientFeedbackError: If fewer than ``min_records`` exist.
        """
        now = datetime.now(UTC)
        to_dt = to_dt or now
        from_dt = from_dt or (now - timedelta(days=90))

        all_records: list[FeedbackRecord] = []
        for verdict in ReviewerVerdict:
            records = await self.query_by_verdict(
                verdict.value, from_dt, to_dt, limit=500
            )
            all_records.extend(records)

        total = len(all_records)
        if total < min_records:
            raise InsufficientFeedbackError(count=total, required=min_records)

        agree = sum(1 for r in all_records if r.reviewer_verdict == ReviewerVerdict.AGREE)
        disagree = sum(1 for r in all_records if r.reviewer_verdict == ReviewerVerdict.DISAGREE)
        partial = sum(1 for r in all_records if r.reviewer_verdict == ReviewerVerdict.PARTIAL)
        accuracy = agree / total if total > 0 else 0.0

        return CalibrationDataset(
            records=all_records,
            total=total,
            agree_count=agree,
            disagree_count=disagree,
            partial_count=partial,
            accuracy=round(accuracy, 4),
            from_dt=from_dt,
            to_dt=to_dt,
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_store: FeedbackStore | None = None
_store_lock = asyncio.Lock()


async def get_feedback_store() -> FeedbackStore:
    """Return the singleton :class:`FeedbackStore`."""
    global _store
    if _store is not None:
        return _store
    async with _store_lock:
        if _store is None:
            _store = FeedbackStore()
    return _store
