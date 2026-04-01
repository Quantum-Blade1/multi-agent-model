"""
Async DynamoDB-backed audit store for the NBFC Compliance AI system.

Provides persistent storage for audit records with:

- **Transactional writes** ensuring atomicity of record + chain entry via
  ``TransactWriteItems``.  Records are immutable after creation —
  ``ConditionExpression: attribute_not_exists(request_id)`` prevents
  overwrites.
- **GSI-backed queries** by compliance status, reviewer state, correlation
  ID, and date range, all with cursor-based pagination.
- **Human override tracking** with conditional updates that prevent
  double-overrides.  Hash fields are never modified — the override is
  appended data, not a mutation of the original AI decision.
- **Full hash-chain verification** that fetches records in sequence order
  and delegates to :class:`HashChainEngine` for tamper detection.

DynamoDB tables required:

===============================  ====================================
Table                            Purpose
===============================  ====================================
``nbfc-audit-records``           Primary storage for AuditRecords
``nbfc-audit-chain``             Ordered chain registry (sequence → hash)
``nbfc-audit-sequence``          Atomic counter for sequence numbers
===============================  ====================================
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import aiobotocore.session
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError
from pydantic import BaseModel, Field

from audit.models import (
    AuditRecord,
    HashChainEngine,
    OverrideRecord,
    ReviewerStatus,
    VerificationResult,
)
from observability.logger import get_logger

log = get_logger("audit.store")

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AuditWriteError(Exception):
    """Raised when a transactional write to DynamoDB fails.

    The ``detail`` attribute contains DynamoDB cancellation reasons so the
    caller can log or surface the root cause.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class AuditNotFoundError(Exception):
    """Raised when a requested audit record does not exist in the store."""


class AuditAlreadyOverriddenError(Exception):
    """Raised when an override is attempted on a record that has already
    been overridden (``reviewer_status == OVERRIDDEN``)."""


# ---------------------------------------------------------------------------
# Query result model
# ---------------------------------------------------------------------------


class AuditQueryResult(BaseModel):
    """Paginated result set returned by audit record queries.

    ``next_key`` is an opaque DynamoDB pagination token — pass it back
    as ``last_key`` in the subsequent call to fetch the next page.
    """

    records: list[AuditRecord] = Field(
        description="Audit records in this page.",
    )
    total_returned: int = Field(
        description="Number of records in this response.",
    )
    has_more: bool = Field(
        description="Whether additional pages are available.",
    )
    next_key: dict[str, Any] | None = Field(
        default=None,
        description="Opaque pagination token for the next page.",
    )


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

_serializer = TypeSerializer()
_deserializer = TypeDeserializer()

_RBI_RETENTION_SECONDS = int(7 * 365.25 * 86400)


def _floats_to_decimal(obj: Any) -> Any:
    """Recursively convert ``float`` → ``Decimal`` for DynamoDB."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_floats_to_decimal(item) for item in obj]
    return obj


def _decimals_to_float(obj: Any) -> Any:
    """Recursively convert ``Decimal`` back to ``int`` or ``float``."""
    if isinstance(obj, Decimal):
        if obj == int(obj):
            return int(obj)
        return float(obj)
    if isinstance(obj, dict):
        return {k: _decimals_to_float(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimals_to_float(item) for item in obj]
    return obj


def to_dynamo_item(record: AuditRecord) -> dict[str, Any]:
    """Serialize an :class:`AuditRecord` to DynamoDB wire format.

    Uses Pydantic's ``model_dump(mode="json")`` so datetimes become
    ISO-8601 strings and enums become their string values.  All floats
    are then converted to ``Decimal`` (DynamoDB rejects native floats).

    A TTL attribute ``expires_at`` is appended, set 7 years into the
    future per RBI data-retention requirements.
    """
    data = record.model_dump(mode="json")
    prepared = _floats_to_decimal(data)
    prepared["expires_at"] = (
        int(record.created_at.timestamp()) + _RBI_RETENTION_SECONDS
    )
    return {k: _serializer.serialize(v) for k, v in prepared.items()}


def from_dynamo_item(item: dict[str, Any]) -> AuditRecord:
    """Deserialize a DynamoDB item back to an :class:`AuditRecord`.

    Uses ``strict=False`` for validation because the data originates from
    our own store and needs ``str`` → ``datetime`` / ``str`` → ``Enum``
    coercion that strict mode would reject.
    """
    raw = {k: _deserializer.deserialize(v) for k, v in item.items()}
    data = _decimals_to_float(raw)
    data.pop("expires_at", None)
    return AuditRecord.model_validate(data, strict=False)


# ---------------------------------------------------------------------------
# Module-level locks
# ---------------------------------------------------------------------------

_chain_lock = asyncio.Lock()

# ---------------------------------------------------------------------------
# Store implementation
# ---------------------------------------------------------------------------


class AuditStore:
    """Async DynamoDB-backed store for compliance audit records.

    Manages three DynamoDB tables:

    - **Records table** — stores full ``AuditRecord`` documents.
    - **Chain table** — ordered registry of ``(sequence_number, audit_id,
      chain_hash, request_id, created_at)`` enabling chain verification
      via direct ``GetItem`` lookups on the records table.
    - **Sequence table** — single-item atomic counter for generating
      monotonically increasing sequence numbers.

    The aiobotocore client is created lazily on first use and cached for
    the lifetime of the store.  Call :meth:`close` during application
    shutdown to release the underlying HTTP session.
    """

    def __init__(
        self,
        region: str | None = None,
        records_table: str | None = None,
        chain_table: str | None = None,
        sequence_table: str | None = None,
    ) -> None:
        self._region = region or os.getenv("AWS_REGION", "ap-south-1")
        self._records_table = records_table or os.getenv(
            "AUDIT_RECORDS_TABLE", "nbfc-audit-records"
        )
        self._chain_table = chain_table or os.getenv(
            "AUDIT_CHAIN_TABLE", "nbfc-audit-chain"
        )
        self._sequence_table = sequence_table or os.getenv(
            "AUDIT_SEQUENCE_TABLE", "nbfc-audit-sequence"
        )
        self._session = aiobotocore.session.get_session()
        self._client: Any = None
        self._client_ctx: Any = None

    async def _get_client(self) -> Any:
        """Return a cached async DynamoDB client, creating it on first call."""
        if self._client is None:
            self._client_ctx = self._session.create_client(
                "dynamodb", region_name=self._region
            )
            self._client = await self._client_ctx.__aenter__()
        return self._client

    async def close(self) -> None:
        """Release the aiobotocore client and its underlying HTTP session."""
        if self._client_ctx is not None:
            await self._client_ctx.__aexit__(None, None, None)
            self._client = None
            self._client_ctx = None

    # ── Write operations ──────────────────────────────────────────────────

    async def save_record(self, record: AuditRecord) -> str:
        """Atomically write an audit record and its chain entry.

        Uses ``TransactWriteItems`` to ensure both the record and the
        chain entry are persisted together or not at all.  The records
        table write carries ``attribute_not_exists(request_id)`` to
        guarantee immutability — a duplicate request_id is rejected.

        Args:
            record: A fully-populated ``AuditRecord`` with valid hashes
                (built via :func:`build_audit_record`).

        Returns:
            The ``audit_id`` of the saved record.

        Raises:
            AuditWriteError: If the DynamoDB transaction is cancelled
                (e.g. duplicate request_id or chain conflict).
        """
        client = await self._get_client()
        item = to_dynamo_item(record)
        sequence = await self._get_next_sequence()

        chain_entry = {
            "chain_id": _serializer.serialize("MAIN"),
            "sequence_number": _serializer.serialize(sequence),
            "audit_id": _serializer.serialize(record.audit_id),
            "chain_hash": _serializer.serialize(record.chain_hash),
            "request_id": _serializer.serialize(record.request_id),
            "created_at": _serializer.serialize(record.created_at.isoformat()),
        }

        try:
            await client.transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": self._records_table,
                            "Item": item,
                            "ConditionExpression": "attribute_not_exists(request_id)",
                        }
                    },
                    {
                        "Put": {
                            "TableName": self._chain_table,
                            "Item": chain_entry,
                        }
                    },
                ]
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "TransactionCanceledException":
                reasons = exc.response.get("CancellationReasons", [])
                detail = (
                    f"Audit write transaction cancelled for "
                    f"request_id={record.request_id}: {reasons}"
                )
                log.error(
                    detail,
                    extra={
                        "audit_id": record.audit_id,
                        "request_id": record.request_id,
                        "operation": "save_record",
                    },
                )
                raise AuditWriteError(detail) from exc
            raise

        log.info(
            "Audit record saved",
            extra={
                "audit_id": record.audit_id,
                "request_id": record.request_id,
                "sequence_number": sequence,
                "operation": "save_record",
            },
        )
        return record.audit_id

    async def get_latest_chain_hash(self) -> str:
        """Retrieve the ``chain_hash`` of the most recent audit record.

        Queries the chain table for the entry with the highest
        ``sequence_number``.  An ``asyncio.Lock`` serialises concurrent
        callers so two requests never read the same "latest" hash — this
        prevents two records being chained to the same predecessor.

        Returns:
            The latest ``chain_hash``, or
            :attr:`HashChainEngine.GENESIS_HASH` if the chain is empty.
        """
        async with _chain_lock:
            client = await self._get_client()
            response = await client.query(
                TableName=self._chain_table,
                KeyConditionExpression="chain_id = :cid",
                ExpressionAttributeValues={":cid": {"S": "MAIN"}},
                ScanIndexForward=False,
                Limit=1,
                ProjectionExpression="chain_hash",
            )
            items = response.get("Items", [])
            if not items:
                return HashChainEngine.GENESIS_HASH
            return _deserializer.deserialize(items[0]["chain_hash"])

    async def _get_next_sequence(self) -> int:
        """Atomically increment and return the next chain sequence number.

        Uses ``UpdateItem`` with ``ADD`` on a dedicated counter table,
        guaranteeing uniqueness even under high write concurrency.
        """
        client = await self._get_client()
        response = await client.update_item(
            TableName=self._sequence_table,
            Key={"counter_id": {"S": "MAIN"}},
            UpdateExpression="ADD #val :inc",
            ExpressionAttributeNames={"#val": "value"},
            ExpressionAttributeValues={":inc": {"N": "1"}},
            ReturnValues="UPDATED_NEW",
        )
        return int(response["Attributes"]["value"]["N"])

    # ── Read / query operations ───────────────────────────────────────────

    async def get_by_request_id(self, request_id: str) -> AuditRecord | None:
        """Fetch an audit record by its ``request_id``.

        Queries the records table partition key and returns the most
        recent entry.  Under normal operation there is exactly one record
        per ``request_id`` (enforced by the immutability condition on
        writes).

        Args:
            request_id: The compliance request identifier.

        Returns:
            The matching ``AuditRecord``, or ``None`` if not found.
        """
        client = await self._get_client()
        response = await client.query(
            TableName=self._records_table,
            KeyConditionExpression="request_id = :rid",
            ExpressionAttributeValues={":rid": {"S": request_id}},
            ScanIndexForward=False,
            Limit=1,
        )
        items = response.get("Items", [])
        if not items:
            return None
        return from_dynamo_item(items[0])

    async def query_by_status(
        self,
        status: str,
        from_dt: datetime,
        to_dt: datetime,
        limit: int = 50,
        last_key: dict[str, Any] | None = None,
    ) -> AuditQueryResult:
        """Query audit records by compliance status within a date range.

        Uses **GSI-1** (``status-index``) with partition key
        ``final_status`` and sort key ``created_at``.

        Args:
            status: Compliance status filter (``APPROVED`` / ``REJECTED``
                / ``REVIEW``).
            from_dt: Start of the date range (inclusive).
            to_dt: End of the date range (inclusive).
            limit: Maximum records per page.
            last_key: Pagination token from a previous response.

        Returns:
            Paginated :class:`AuditQueryResult`.
        """
        client = await self._get_client()
        kwargs: dict[str, Any] = {
            "TableName": self._records_table,
            "IndexName": "status-index",
            "KeyConditionExpression": (
                "final_status = :s AND created_at BETWEEN :f AND :t"
            ),
            "ExpressionAttributeValues": {
                ":s": {"S": status},
                ":f": {"S": from_dt.isoformat()},
                ":t": {"S": to_dt.isoformat()},
            },
            "Limit": limit,
            "ScanIndexForward": False,
        }
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key

        response = await client.query(**kwargs)
        items = response.get("Items", [])
        records = [from_dynamo_item(item) for item in items]
        next_key = response.get("LastEvaluatedKey")

        return AuditQueryResult(
            records=records,
            total_returned=len(records),
            has_more=next_key is not None,
            next_key=next_key,
        )

    async def query_by_reviewer_status(
        self,
        reviewer_status: str,
        limit: int = 50,
        last_key: dict[str, Any] | None = None,
    ) -> AuditQueryResult:
        """Query audit records by their reviewer lifecycle state.

        Uses **GSI-2** (``reviewer-index``).  Commonly used to surface
        records awaiting human review (``PENDING``).

        Args:
            reviewer_status: Reviewer state filter (``PENDING`` /
                ``REVIEWED`` / ``OVERRIDDEN``).
            limit: Maximum records per page.
            last_key: Pagination token from a previous response.

        Returns:
            Paginated :class:`AuditQueryResult`.
        """
        client = await self._get_client()
        kwargs: dict[str, Any] = {
            "TableName": self._records_table,
            "IndexName": "reviewer-index",
            "KeyConditionExpression": "reviewer_status = :rs",
            "ExpressionAttributeValues": {":rs": {"S": reviewer_status}},
            "Limit": limit,
            "ScanIndexForward": False,
        }
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key

        response = await client.query(**kwargs)
        items = response.get("Items", [])
        records = [from_dynamo_item(item) for item in items]
        next_key = response.get("LastEvaluatedKey")

        return AuditQueryResult(
            records=records,
            total_returned=len(records),
            has_more=next_key is not None,
            next_key=next_key,
        )

    async def query_by_date_range(
        self,
        from_dt: datetime,
        to_dt: datetime,
        limit: int = 50,
        last_key: dict[str, Any] | None = None,
    ) -> AuditQueryResult:
        """Query audit records within a date range across all statuses.

        Uses a table **Scan** with ``FilterExpression`` — there is no
        GSI that covers open-ended date-range queries across all
        partition keys.  This is acceptable for audit use cases where
        latency is not critical.

        Args:
            from_dt: Start of the date range (inclusive).
            to_dt: End of the date range (inclusive).
            limit: Maximum records per page.
            last_key: Pagination token from a previous response.

        Returns:
            Paginated :class:`AuditQueryResult`.
        """
        client = await self._get_client()
        kwargs: dict[str, Any] = {
            "TableName": self._records_table,
            "FilterExpression": "created_at BETWEEN :f AND :t",
            "ExpressionAttributeValues": {
                ":f": {"S": from_dt.isoformat()},
                ":t": {"S": to_dt.isoformat()},
            },
            "Limit": limit,
        }
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key

        response = await client.scan(**kwargs)
        items = response.get("Items", [])
        records = [from_dynamo_item(item) for item in items]
        next_key = response.get("LastEvaluatedKey")

        return AuditQueryResult(
            records=records,
            total_returned=len(records),
            has_more=next_key is not None,
            next_key=next_key,
        )

    async def query_by_correlation_id(
        self, correlation_id: str
    ) -> list[AuditRecord]:
        """Fetch all audit records sharing a correlation ID.

        Uses **GSI-3** (``correlation-index``).  No pagination —
        correlation groups are expected to be small (typically 1–5
        records for a single distributed transaction).

        Args:
            correlation_id: The distributed-tracing correlation
                identifier.

        Returns:
            List of matching ``AuditRecord`` objects (possibly empty).
        """
        client = await self._get_client()
        response = await client.query(
            TableName=self._records_table,
            IndexName="correlation-index",
            KeyConditionExpression="correlation_id = :cid",
            ExpressionAttributeValues={":cid": {"S": correlation_id}},
        )
        items = response.get("Items", [])
        return [from_dynamo_item(item) for item in items]

    # ── Override operation ─────────────────────────────────────────────────

    async def apply_override(
        self,
        request_id: str,
        override: OverrideRecord,
    ) -> AuditRecord:
        """Apply a human reviewer override to an existing audit record.

        Updates the record's ``override`` field and sets
        ``reviewer_status`` to ``OVERRIDDEN``.  The original
        ``content_hash`` and ``chain_hash`` are **never** modified —
        the override is appended data that proves the original AI
        decision while tracking the human correction.

        A ``ConditionExpression`` prevents double-overrides: once a
        record is overridden, further override attempts are rejected.

        Args:
            request_id: The ``request_id`` of the record to override.
            override: Validated override details.

        Returns:
            The updated ``AuditRecord`` with override attached.

        Raises:
            AuditNotFoundError: No record exists for *request_id*.
            AuditAlreadyOverriddenError: The record has already been
                overridden.
        """
        existing = await self.get_by_request_id(request_id)
        if existing is None:
            raise AuditNotFoundError(
                f"No audit record found for request_id={request_id}"
            )

        override_data = _floats_to_decimal(override.model_dump(mode="json"))
        override_dynamo = _serializer.serialize(override_data)

        client = await self._get_client()
        try:
            response = await client.update_item(
                TableName=self._records_table,
                Key={
                    "request_id": {"S": existing.request_id},
                    "created_at": {"S": existing.created_at.isoformat()},
                },
                UpdateExpression="SET #ov = :ov, reviewer_status = :rs",
                ConditionExpression=(
                    "attribute_exists(request_id) "
                    "AND reviewer_status <> :already_overridden"
                ),
                ExpressionAttributeNames={"#ov": "override"},
                ExpressionAttributeValues={
                    ":ov": override_dynamo,
                    ":rs": {"S": ReviewerStatus.OVERRIDDEN.value},
                    ":already_overridden": {"S": ReviewerStatus.OVERRIDDEN.value},
                },
                ReturnValues="ALL_NEW",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise AuditAlreadyOverriddenError(
                    f"Record {request_id} has already been overridden"
                ) from exc
            raise

        updated = from_dynamo_item(response["Attributes"])
        log.info(
            "Override applied",
            extra={
                "audit_id": updated.audit_id,
                "request_id": request_id,
                "override_id": override.override_id,
                "operation": "apply_override",
            },
        )
        return updated

    # ── Chain verification ────────────────────────────────────────────────

    async def verify_chain_integrity(
        self,
        from_sequence: int = 0,
        to_sequence: int | None = None,
    ) -> VerificationResult:
        """Verify the integrity of the audit hash chain.

        Walks the chain table in sequence order, fetches the full
        ``AuditRecord`` for each entry via ``GetItem`` (using the
        ``request_id`` + ``created_at`` stored alongside the chain
        entry), then delegates to :meth:`HashChainEngine.verify_chain`
        for cryptographic verification.

        Args:
            from_sequence: Starting sequence number (inclusive).
            to_sequence: Ending sequence number (inclusive).  ``None``
                means verify through the latest record.

        Returns:
            :class:`VerificationResult` indicating whether the chain is
            intact and, if broken, the index of the first inconsistency.
        """
        client = await self._get_client()

        if to_sequence is not None:
            key_expr = (
                "chain_id = :cid "
                "AND sequence_number BETWEEN :from_seq AND :to_seq"
            )
            expr_values: dict[str, Any] = {
                ":cid": {"S": "MAIN"},
                ":from_seq": {"N": str(from_sequence)},
                ":to_seq": {"N": str(to_sequence)},
            }
        else:
            key_expr = "chain_id = :cid AND sequence_number >= :from_seq"
            expr_values = {
                ":cid": {"S": "MAIN"},
                ":from_seq": {"N": str(from_sequence)},
            }

        chain_entries: list[dict[str, Any]] = []
        last_key: dict[str, Any] | None = None

        while True:
            kwargs: dict[str, Any] = {
                "TableName": self._chain_table,
                "KeyConditionExpression": key_expr,
                "ExpressionAttributeValues": expr_values,
                "ScanIndexForward": True,
            }
            if last_key:
                kwargs["ExclusiveStartKey"] = last_key

            response = await client.query(**kwargs)
            chain_entries.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break

        if not chain_entries:
            return VerificationResult(
                valid=True,
                first_broken_at=None,
                total_records=0,
                verified_records=0,
            )

        records: list[AuditRecord] = []
        for entry in chain_entries:
            rid = _deserializer.deserialize(entry["request_id"])
            cat = _deserializer.deserialize(entry["created_at"])

            resp = await client.get_item(
                TableName=self._records_table,
                Key={
                    "request_id": {"S": rid},
                    "created_at": {"S": cat},
                },
            )
            item = resp.get("Item")
            if item is None:
                aid = _deserializer.deserialize(entry.get("audit_id", {"S": "?"}))
                log.error(
                    "Chain entry references missing audit record",
                    extra={
                        "audit_id": aid,
                        "request_id": rid,
                        "operation": "verify_chain_integrity",
                    },
                )
                return VerificationResult(
                    valid=False,
                    first_broken_at=len(records),
                    total_records=len(chain_entries),
                    verified_records=len(records),
                )
            records.append(from_dynamo_item(item))

        return await HashChainEngine.verify_chain(records)


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_store_instance: AuditStore | None = None
_store_lock = asyncio.Lock()


async def get_audit_store() -> AuditStore:
    """Return the singleton :class:`AuditStore`, creating it on first call.

    Uses ``asyncio.Lock`` to guarantee only one instance is created even
    when multiple coroutines race on startup.
    """
    global _store_instance
    if _store_instance is not None:
        return _store_instance

    async with _store_lock:
        if _store_instance is None:
            _store_instance = AuditStore()
    return _store_instance
