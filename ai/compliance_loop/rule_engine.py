"""
Runtime-configurable compliance rule engine for the NBFC AI system.

Rules that were previously hardcoded in individual agents (FOIR threshold,
required document types, fuzzy-match score, expiry warning days, etc.) are
centralised here and backed by DynamoDB so they can be updated via API
without redeployment.

Architecture
------------
* **Seeded defaults** — every rule has a ``DEFAULT_RULES`` entry that is
  used when the DynamoDB table is empty or a specific rule is missing.
* **In-process cache** — rules are held in a ``dict`` with a 60-second TTL.
  Cache refresh is serialised by an ``asyncio.Lock`` to prevent thundering
  herd on expiry.
* **Typed convenience getters** — agents call ``await engine.foir_limit()``
  instead of parsing raw values themselves.
* **Audited updates** — every rule change is written to both the rules
  table and a separate changelog table, with mandatory justification.

DynamoDB tables (env-configurable)::

    nbfc-compliance-rules      PK: rule_id (S)
    nbfc-rule-changelog        PK: rule_id (S)  SK: changed_at (S)
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import uuid4

import aiobotocore.session
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from pydantic import BaseModel, Field, model_validator

from ai.observability.logger import get_logger

log = get_logger("ai.compliance_loop.rule_engine")

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RuleCategory(str, Enum):
    """Functional area that a compliance rule belongs to."""

    TRANSACTION = "TRANSACTION"
    DOCUMENT = "DOCUMENT"
    SANCTIONS = "SANCTIONS"
    TEMPORAL = "TEMPORAL"
    DECISION = "DECISION"


class RuleValueType(str, Enum):
    """Data type of a rule's value, used for validation on updates."""

    FLOAT = "FLOAT"
    INT = "INT"
    STRING_LIST = "STRING_LIST"
    BOOL = "BOOL"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ComplianceRule(BaseModel):
    """A single compliance rule with its current and default values.

    The ``default_value`` is the original hardcoded constant and is
    **never** changeable via API — it exists so regulators can see
    what the system shipped with.
    """

    rule_id: str = Field(description="Unique rule identifier, e.g. FOIR_LIMIT.")
    category: RuleCategory = Field(description="Functional area this rule belongs to.")
    value_type: RuleValueType = Field(description="Expected data type of current_value.")
    current_value: Any = Field(description="Active rule value used at runtime.")
    default_value: Any = Field(description="Original hardcoded value; immutable via API.")
    min_value: float | None = Field(default=None, description="Lower bound for numeric rules.")
    max_value: float | None = Field(default=None, description="Upper bound for numeric rules.")
    description: str = Field(description="Human-readable explanation of the rule.")
    rbi_reference: str | None = Field(
        default=None,
        description="RBI regulation citation, e.g. 'RBI/DNBR/2016-17/45 §4.2'.",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp of the last update.",
    )
    updated_by: str = Field(default="system", description="Reviewer ID who last changed this rule.")
    version: int = Field(default=1, description="Monotonically increasing version counter.")

    @model_validator(mode="after")
    def validate_value_type_and_bounds(self) -> ComplianceRule:
        """Enforce that ``current_value`` matches ``value_type`` and respects bounds."""
        val = self.current_value

        if self.value_type == RuleValueType.FLOAT:
            if not isinstance(val, (int, float)):
                raise ValueError(f"Rule {self.rule_id}: expected float, got {type(val).__name__}")
            val = float(val)
            self.current_value = val
            if self.min_value is not None and val < self.min_value:
                raise ValueError(
                    f"Rule {self.rule_id}: {val} < min_value {self.min_value}"
                )
            if self.max_value is not None and val > self.max_value:
                raise ValueError(
                    f"Rule {self.rule_id}: {val} > max_value {self.max_value}"
                )

        elif self.value_type == RuleValueType.INT:
            if not isinstance(val, int):
                raise ValueError(f"Rule {self.rule_id}: expected int, got {type(val).__name__}")
            if self.min_value is not None and val < self.min_value:
                raise ValueError(
                    f"Rule {self.rule_id}: {val} < min_value {self.min_value}"
                )
            if self.max_value is not None and val > self.max_value:
                raise ValueError(
                    f"Rule {self.rule_id}: {val} > max_value {self.max_value}"
                )

        elif self.value_type == RuleValueType.STRING_LIST:
            if not isinstance(val, list) or not all(isinstance(v, str) for v in val):
                raise ValueError(
                    f"Rule {self.rule_id}: expected list[str], got {type(val).__name__}"
                )

        elif self.value_type == RuleValueType.BOOL:
            if not isinstance(val, bool):
                raise ValueError(f"Rule {self.rule_id}: expected bool, got {type(val).__name__}")

        return self


class RuleUpdate(BaseModel):
    """Payload for updating a compliance rule's value."""

    rule_id: str = Field(description="Which rule to update.")
    new_value: Any = Field(description="Proposed new value.")
    updated_by: str = Field(description="Reviewer ID performing the change.")
    justification: str = Field(
        min_length=20,
        description="Mandatory explanation for the change (min 20 chars).",
    )
    rbi_reference: str | None = Field(
        default=None,
        description="Optional RBI clause motivating the change.",
    )


class RuleChangeLog(BaseModel):
    """Immutable record of a single rule change, stored in the changelog table."""

    change_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique identifier for this changelog entry.",
    )
    rule_id: str = Field(description="The rule that was changed.")
    old_value: Any = Field(description="Value before the change.")
    new_value: Any = Field(description="Value after the change.")
    updated_by: str = Field(description="Reviewer ID who made the change.")
    justification: str = Field(description="Reason for the change.")
    rbi_reference: str | None = Field(default=None, description="RBI clause cited.")
    changed_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp when the change was applied.",
    )


# ---------------------------------------------------------------------------
# Seeded defaults
# ---------------------------------------------------------------------------

DEFAULT_RULES: dict[str, ComplianceRule] = {
    "FOIR_LIMIT": ComplianceRule(
        rule_id="FOIR_LIMIT",
        category=RuleCategory.TRANSACTION,
        value_type=RuleValueType.FLOAT,
        current_value=0.50,
        default_value=0.50,
        min_value=0.30,
        max_value=0.65,
        description="Maximum Fixed Obligation to Income Ratio allowed for any applicant",
        rbi_reference="RBI Master Direction DNBR.PD.008/03.10.119/2016-17 §4.2",
    ),
    "REQUIRED_DOC_TYPES": ComplianceRule(
        rule_id="REQUIRED_DOC_TYPES",
        category=RuleCategory.DOCUMENT,
        value_type=RuleValueType.STRING_LIST,
        current_value=["pan_card", "aadhaar", "bank_statement", "salary_slip", "itr", "form_16"],
        default_value=["pan_card", "aadhaar", "bank_statement", "salary_slip", "itr", "form_16"],
        description="Document types that must be present for KYC verification",
        rbi_reference="RBI Master Direction KYC/2016 §38",
    ),
    "FUZZY_MATCH_THRESHOLD": ComplianceRule(
        rule_id="FUZZY_MATCH_THRESHOLD",
        category=RuleCategory.SANCTIONS,
        value_type=RuleValueType.INT,
        current_value=85,
        default_value=85,
        min_value=70,
        max_value=100,
        description="Minimum fuzzy-match score (0-100) to flag a sanctions list hit",
        rbi_reference="RBI/DPSS/2018/CO.DPSS.POLC.No.3/02.01.001/2018-19",
    ),
    "EXPIRY_WARNING_DAYS": ComplianceRule(
        rule_id="EXPIRY_WARNING_DAYS",
        category=RuleCategory.TEMPORAL,
        value_type=RuleValueType.INT,
        current_value=30,
        default_value=30,
        min_value=7,
        max_value=90,
        description="Number of days before document expiry to raise a warning flag",
        rbi_reference=None,
    ),
    "CONFIDENCE_PENALTY_PER_ERROR": ComplianceRule(
        rule_id="CONFIDENCE_PENALTY_PER_ERROR",
        category=RuleCategory.DECISION,
        value_type=RuleValueType.FLOAT,
        current_value=0.15,
        default_value=0.15,
        min_value=0.05,
        max_value=0.30,
        description="Confidence score reduction applied per non-recoverable agent error",
        rbi_reference=None,
    ),
    "MAX_FOIR_FOR_APPROVAL": ComplianceRule(
        rule_id="MAX_FOIR_FOR_APPROVAL",
        category=RuleCategory.TRANSACTION,
        value_type=RuleValueType.FLOAT,
        current_value=0.45,
        default_value=0.45,
        min_value=0.30,
        max_value=0.60,
        description="FOIR threshold for APPROVED vs REVIEW split (below FOIR_LIMIT)",
        rbi_reference="RBI Master Direction DNBR.PD.008/03.10.119/2016-17 §4.2",
    ),
}


# ---------------------------------------------------------------------------
# Serialization helpers (same pattern as ai/audit/store.py)
# ---------------------------------------------------------------------------

_serializer = TypeSerializer()
_deserializer = TypeDeserializer()


def _floats_to_decimal(obj: Any) -> Any:
    """Recursively convert ``float`` to ``Decimal`` for DynamoDB."""
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


def _rule_to_dynamo(rule: ComplianceRule) -> dict[str, Any]:
    """Serialize a ``ComplianceRule`` to DynamoDB wire format."""
    data = rule.model_dump(mode="json")
    prepared = _floats_to_decimal(data)
    return {k: _serializer.serialize(v) for k, v in prepared.items()}


def _rule_from_dynamo(item: dict[str, Any]) -> ComplianceRule:
    """Deserialize a DynamoDB item back to a ``ComplianceRule``."""
    raw = {k: _deserializer.deserialize(v) for k, v in item.items()}
    data = _decimals_to_float(raw)
    return ComplianceRule.model_validate(data, strict=False)


def _changelog_to_dynamo(entry: RuleChangeLog) -> dict[str, Any]:
    """Serialize a ``RuleChangeLog`` to DynamoDB wire format."""
    data = entry.model_dump(mode="json")
    prepared = _floats_to_decimal(data)
    return {k: _serializer.serialize(v) for k, v in prepared.items()}


def _changelog_from_dynamo(item: dict[str, Any]) -> RuleChangeLog:
    """Deserialize a DynamoDB item back to a ``RuleChangeLog``."""
    raw = {k: _deserializer.deserialize(v) for k, v in item.items()}
    data = _decimals_to_float(raw)
    return RuleChangeLog.model_validate(data, strict=False)


# ---------------------------------------------------------------------------
# Rule engine
# ---------------------------------------------------------------------------

RULES_TABLE = os.getenv("COMPLIANCE_RULES_TABLE", "nbfc-compliance-rules")
CHANGELOG_TABLE = os.getenv("COMPLIANCE_CHANGELOG_TABLE", "nbfc-rule-changelog")


class RuleEngine:
    """DynamoDB-backed, in-process-cached compliance rule engine.

    Agents query this engine at runtime instead of using hardcoded constants.
    Rules are cached for :attr:`CACHE_TTL_SECONDS` to avoid per-request
    DynamoDB reads.  Updates are written through immediately and the cache
    is invalidated so the next read picks up the new value.

    Usage from an agent::

        engine = await get_rule_engine()
        limit = await engine.foir_limit()
        if foir > limit:
            ...
    """

    CACHE_TTL_SECONDS: int = 60

    def __init__(
        self,
        rules_table: str | None = None,
        changelog_table: str | None = None,
        region: str | None = None,
    ) -> None:
        self._rules_table = rules_table or RULES_TABLE
        self._changelog_table = changelog_table or CHANGELOG_TABLE
        self._region = region or os.getenv("AWS_REGION", "ap-south-1")
        self._session = aiobotocore.session.get_session()
        self._client: Any = None
        self._client_ctx: Any = None
        self._cache: dict[str, ComplianceRule] = {}
        self._cache_loaded_at: float | None = None
        self._lock = asyncio.Lock()

    async def _get_client(self) -> Any:
        """Return a cached async DynamoDB client."""
        if self._client is None:
            self._client_ctx = self._session.create_client(
                "dynamodb", region_name=self._region
            )
            self._client = await self._client_ctx.__aenter__()
        return self._client

    async def close(self) -> None:
        """Release the aiobotocore client session."""
        if self._client_ctx is not None:
            await self._client_ctx.__aexit__(None, None, None)
            self._client = None
            self._client_ctx = None

    # ── Cache management ──────────────────────────────────────────────────

    async def _load_from_dynamo(self) -> dict[str, ComplianceRule]:
        """Scan the rules table and merge with seeded defaults.

        Any rule present in ``DEFAULT_RULES`` but missing from DynamoDB
        is filled in from the defaults.  This guarantees the engine always
        has a complete rule set even on first boot before any rules have
        been persisted.
        """
        client = await self._get_client()
        rules: dict[str, ComplianceRule] = {}

        try:
            last_key: dict[str, Any] | None = None
            while True:
                kwargs: dict[str, Any] = {"TableName": self._rules_table}
                if last_key:
                    kwargs["ExclusiveStartKey"] = last_key

                response = await client.scan(**kwargs)
                for item in response.get("Items", []):
                    rule = _rule_from_dynamo(item)
                    rules[rule.rule_id] = rule

                last_key = response.get("LastEvaluatedKey")
                if not last_key:
                    break
        except Exception as exc:
            log.warning(
                "Failed to load rules from DynamoDB, using defaults: %s",
                exc,
                extra={"operation": "_load_from_dynamo"},
            )

        for rule_id, default in DEFAULT_RULES.items():
            if rule_id not in rules:
                rules[rule_id] = default

        return rules

    async def _refresh_cache_if_stale(self) -> None:
        """Reload from DynamoDB if the cache is expired or uninitialised.

        Uses ``asyncio.Lock`` so only one coroutine refreshes at a time;
        others wait and then see the freshly loaded data.
        """
        now = time.monotonic()
        if (
            self._cache_loaded_at is not None
            and (now - self._cache_loaded_at) < self.CACHE_TTL_SECONDS
        ):
            return

        async with self._lock:
            if (
                self._cache_loaded_at is not None
                and (now - self._cache_loaded_at) < self.CACHE_TTL_SECONDS
            ):
                return
            self._cache = await self._load_from_dynamo()
            self._cache_loaded_at = time.monotonic()

    # ── Read operations ───────────────────────────────────────────────────

    async def get_rule(self, rule_id: str) -> ComplianceRule:
        """Return a single rule by ID, refreshing the cache if stale.

        Raises:
            KeyError: If ``rule_id`` is not a known rule.
        """
        await self._refresh_cache_if_stale()
        if rule_id not in self._cache:
            raise KeyError(f"Unknown rule: {rule_id}")
        return self._cache[rule_id]

    async def get_value(self, rule_id: str) -> Any:
        """Shorthand to fetch only the ``current_value`` of a rule."""
        rule = await self.get_rule(rule_id)
        return rule.current_value

    async def get_all_rules(self) -> list[ComplianceRule]:
        """Return all rules as a list, refreshing the cache if stale."""
        await self._refresh_cache_if_stale()
        return list(self._cache.values())

    # ── Typed convenience getters (what agents call) ──────────────────────

    async def foir_limit(self) -> float:
        """Maximum FOIR allowed for any applicant."""
        return await self.get_value("FOIR_LIMIT")

    async def required_doc_types(self) -> list[str]:
        """Document types required for KYC verification."""
        return await self.get_value("REQUIRED_DOC_TYPES")

    async def fuzzy_match_threshold(self) -> int:
        """Minimum fuzzy-match score to flag a sanctions hit."""
        return await self.get_value("FUZZY_MATCH_THRESHOLD")

    async def expiry_warning_days(self) -> int:
        """Days before document expiry to raise a warning."""
        return await self.get_value("EXPIRY_WARNING_DAYS")

    async def confidence_penalty_per_error(self) -> float:
        """Confidence reduction per non-recoverable agent error."""
        return await self.get_value("CONFIDENCE_PENALTY_PER_ERROR")

    async def max_foir_for_approval(self) -> float:
        """FOIR threshold below which auto-approval is permitted."""
        return await self.get_value("MAX_FOIR_FOR_APPROVAL")

    # ── Write operations ──────────────────────────────────────────────────

    async def update_rule(
        self, update: RuleUpdate
    ) -> tuple[ComplianceRule, RuleChangeLog]:
        """Apply a validated rule change and log it to the changelog table.

        Steps:

        1. Fetch the current rule from cache.
        2. Build a new ``ComplianceRule`` with the updated value (Pydantic
           validation enforces type and bounds).
        3. Write the updated rule to DynamoDB.
        4. Write the ``RuleChangeLog`` entry.
        5. Invalidate the in-process cache so the next read picks up the
           new value.

        Args:
            update: The proposed change.

        Returns:
            ``(updated_rule, changelog_entry)`` tuple.

        Raises:
            KeyError: If ``rule_id`` is unknown.
            ValueError: If the new value fails type/bounds validation.
        """
        current_rule = await self.get_rule(update.rule_id)

        updated_rule = current_rule.model_copy(
            update={
                "current_value": update.new_value,
                "updated_at": datetime.now(UTC),
                "updated_by": update.updated_by,
                "version": current_rule.version + 1,
                "rbi_reference": update.rbi_reference or current_rule.rbi_reference,
            }
        )
        # Re-validate (model_copy does not re-run validators)
        updated_rule = ComplianceRule.model_validate(updated_rule.model_dump())

        changelog = RuleChangeLog(
            rule_id=update.rule_id,
            old_value=current_rule.current_value,
            new_value=update.new_value,
            updated_by=update.updated_by,
            justification=update.justification,
            rbi_reference=update.rbi_reference,
        )

        client = await self._get_client()

        rule_item = _rule_to_dynamo(updated_rule)
        await client.put_item(TableName=self._rules_table, Item=rule_item)

        changelog_item = _changelog_to_dynamo(changelog)
        await client.put_item(TableName=self._changelog_table, Item=changelog_item)

        self._cache_loaded_at = None

        log.info(
            "Rule updated",
            extra={
                "rule_id": update.rule_id,
                "old_value": str(current_rule.current_value),
                "new_value": str(update.new_value),
                "updated_by": update.updated_by,
                "version": updated_rule.version,
                "operation": "update_rule",
            },
        )

        return updated_rule, changelog

    async def get_changelog(
        self,
        rule_id: str | None = None,
        limit: int = 50,
    ) -> list[RuleChangeLog]:
        """Fetch changelog entries, optionally filtered by ``rule_id``.

        When ``rule_id`` is provided, queries the changelog table partition
        key.  Otherwise, scans the full table (acceptable for audit use
        cases where latency is not critical).

        Args:
            rule_id: Filter to a specific rule.  ``None`` returns all.
            limit: Maximum entries to return.

        Returns:
            List of ``RuleChangeLog`` entries, newest first.
        """
        client = await self._get_client()

        if rule_id is not None:
            response = await client.query(
                TableName=self._changelog_table,
                KeyConditionExpression="rule_id = :rid",
                ExpressionAttributeValues={":rid": {"S": rule_id}},
                ScanIndexForward=False,
                Limit=limit,
            )
        else:
            response = await client.scan(
                TableName=self._changelog_table,
                Limit=limit,
            )

        items = response.get("Items", [])
        return [_changelog_from_dynamo(item) for item in items]


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_engine: RuleEngine | None = None
_engine_lock = asyncio.Lock()


async def get_rule_engine() -> RuleEngine:
    """Return the singleton :class:`RuleEngine`, creating it on first call.

    Uses ``asyncio.Lock`` to guarantee only one instance is created even
    when multiple coroutines race on startup.
    """
    global _engine
    if _engine is not None:
        return _engine

    async with _engine_lock:
        if _engine is None:
            _engine = RuleEngine()
    return _engine


# ---------------------------------------------------------------------------
# Agent integration pattern (documentation only)
# ---------------------------------------------------------------------------
#
# The following shows how each agent should be updated to use the rule engine.
# These changes are NOT applied in this file — they belong in a separate PR
# that rewires the agents.
#
# ┌─ transaction_agent.py ─────────────────────────────────────────────────┐
# │  BEFORE:                                                               │
# │      if foir > 0.50:                                                   │
# │  AFTER:                                                                │
# │      from ai.compliance_loop.rule_engine import get_rule_engine        │
# │      engine = await get_rule_engine()                                  │
# │      limit = await engine.foir_limit()                                 │
# │      if foir > limit:                                                  │
# └────────────────────────────────────────────────────────────────────────┘
#
# ┌─ document_agent.py ────────────────────────────────────────────────────┐
# │  BEFORE:                                                               │
# │      REQUIRED = ["pan_card", ...]                                      │
# │  AFTER:                                                                │
# │      engine = await get_rule_engine()                                  │
# │      REQUIRED = await engine.required_doc_types()                      │
# └────────────────────────────────────────────────────────────────────────┘
#
# ┌─ sanctions_agent.py ───────────────────────────────────────────────────┐
# │  BEFORE:                                                               │
# │      if fuzz.token_sort_ratio(...) >= 85:                              │
# │  AFTER:                                                                │
# │      threshold = await engine.fuzzy_match_threshold()                  │
# │      if fuzz.token_sort_ratio(...) >= threshold:                       │
# └────────────────────────────────────────────────────────────────────────┘
#
# ┌─ temporal_agent.py ────────────────────────────────────────────────────┐
# │  BEFORE:                                                               │
# │      if days_remaining < 30:                                           │
# │  AFTER:                                                                │
# │      warning_days = await engine.expiry_warning_days()                 │
# │      if days_remaining < warning_days:                                 │
# └────────────────────────────────────────────────────────────────────────┘
